"""
api_server.py v3
─────────────────
New in v3:
  - POST /analyse-image endpoint for vision AI space detection
  - Vision QC after each video clip (Florence-2 via fal.ai)
  - TTS QC after each audio generation
  - Job pauses at "awaiting_approval" if QC flags any scene
  - POST /jobs/{id}/approve to approve flagged scenes and proceed to assembly
  - Cost estimation returned with job creation
  - Actual cost tracked after completion
  - GET /diagnostics endpoint with disk, API health, job stats, auto-cleanup
  - GET/POST /maintenance/* endpoints — scheduled health-check report + editable alert recipient list
  - Security: 20MB file size limit, max 20 images, rate limit 5 jobs/hour/IP
  - File type validation by magic bytes
  - Job persistence to disk (survives server restart) — preserved from v2
"""


import os
import uuid
import json
import shutil
import asyncio
import logging
import time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict


from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Request, Header
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv


load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ── Access key auth ────────────────────────────────────────────────────────────
UI_ACCESS_KEY = os.getenv("UI_ACCESS_KEY", "").strip()


def _check_access(request: Request) -> bool:
    """Returns True if request is authorised. Always True if no key configured."""
    if not UI_ACCESS_KEY:
        return True  # no key set — open access (backward compat)
    key = request.headers.get("X-Access-Key", "").strip()
    return key == UI_ACCESS_KEY


BASE_DIR = Path(__file__).parent
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)


JOBS: dict = {}


# ── Job locks — prevent concurrent modification of the same job ───────────────
# Solves the "parallel processing corrupted things" issue: any operation that
# modifies a job (redo scene, add scene, initial generation) must hold this
# lock. A second request for the same job while locked gets a clear 409 error
# instead of racing against the first and corrupting shared files.
_JOB_LOCKS: dict = {}   # job_id -> {"locked": bool, "since": iso timestamp, "operation": str}


def _acquire_job_lock(job_id: str, operation: str) -> bool:
    """Returns True if lock acquired, False if job is already locked."""
    existing = _JOB_LOCKS.get(job_id)
    if existing and existing.get("locked"):
        return False
    _JOB_LOCKS[job_id] = {
        "locked": True,
        "since": datetime.utcnow().isoformat(),
        "operation": operation,
    }
    return True


def _release_job_lock(job_id: str):
    if job_id in _JOB_LOCKS:
        _JOB_LOCKS[job_id]["locked"] = False


def _job_lock_status(job_id: str) -> dict:
    return _JOB_LOCKS.get(job_id, {"locked": False})




# ── Stable scene IDs ────────────────────────────────────────────────────────────
# Scenes are identified by a permanent short ID, never by array position.
# This means "redo this scene" always means the same scene regardless of how
# many times the property has been edited, reordered, or had scenes added.
def _new_scene_id() -> str:
    return "sc_" + uuid.uuid4().hex[:8]


def _ensure_scene_ids(scenes_config: list) -> list:
    """Assigns a stable scene_id to any scene that doesn't have one yet.
    Called on job creation and whenever scenes_config is saved, so old
    jobs migrate forward automatically the next time they're touched."""
    for scene in scenes_config:
        if "scene_id" not in scene or not scene["scene_id"]:
            scene["scene_id"] = _new_scene_id()
    return scenes_config




def _get_rolling_monthly_job_count() -> int:
    """
    Counts actual completed jobs (status=done) from the last 30 days,
    based on JOBS in-memory data and job_meta.json files on disk. Used to
    calculate a REAL infrastructure cost per video, rather than a static
    guess — adapts automatically as production volume changes.
    """
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)
    count = 0
    for job in JOBS.values():
        if job.get("status") != "done":
            continue
        created_str = job.get("created_at", "")
        try:
            created = datetime.fromisoformat(created_str)
            if created >= cutoff:
                count += 1
        except (ValueError, TypeError):
            continue
    return count




def _overlay_narration_audio(video_path: str, narration_path: str):
    """
    Replaces whatever audio is currently on the assembled video with the
    single continuous narration track. Video runs its full length; if
    narration is shorter, the video continues in silence after it ends
    (narration duration was already used to size the video correctly at
    generation time, so this should rarely trigger in practice — it's a
    safety net, not the primary timing mechanism).
    """
    from moviepy import VideoFileClip, AudioFileClip
    video = VideoFileClip(video_path)
    narration = AudioFileClip(narration_path)


    final = video.with_audio(narration)
    tmp_output = video_path + ".narration_tmp.mp4"
    final.write_videofile(
        tmp_output,
        codec="libx264",
        audio_codec="aac",
        bitrate="4000k",
        audio_bitrate="128k",
        preset="medium",
        fps=video.fps or 24,
        logger=None,
    )
    video.close()
    narration.close()
    final.close()
    os.replace(tmp_output, video_path)




# ── Rate limiting ──────────────────────────────────────────────────────────────
_RATE_LIMIT_WINDOW = 3600   # 1 hour in seconds
_RATE_LIMIT_MAX    = 5      # max job submissions per IP per hour
_rate_tracker: dict = defaultdict(list)


def _check_rate_limit(ip: str) -> bool:
    """Returns True if the IP is within the rate limit."""
    now = time.time()
    _rate_tracker[ip] = [t for t in _rate_tracker[ip] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_tracker[ip]) >= _RATE_LIMIT_MAX:
        return False
    _rate_tracker[ip].append(now)
    return True


# ── File type validation (magic bytes) ────────────────────────────────────────
_IMAGE_SIGNATURES = {
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG':      'image/png',
    b'RIFF':         'image/webp',
    b'GIF8':         'image/gif',
}


def _validate_image_bytes(data: bytes) -> bool:
    for sig in _IMAGE_SIGNATURES:
        if data[:len(sig)] == sig:
            return True
    return False


# ── Job persistence ────────────────────────────────────────────────────────────
def _save_job(job_id: str):
    try:
        job = JOBS.get(job_id)
        if not job:
            return
        meta_path = JOBS_DIR / job_id / "job_meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w") as f:
            json.dump(job, f)
    except Exception as e:
        log.warning(f"[Jobs] Could not save job meta for {job_id}: {e}")


def _load_jobs_from_disk():
    loaded = 0
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        meta_path = job_dir / "job_meta.json"
        if not meta_path.exists():
            continue
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            job_id = job_dir.name
            if job_id not in JOBS:
                JOBS[job_id] = meta
                loaded += 1
        except Exception as e:
            log.warning(f"[Jobs] Could not reload {job_dir.name}: {e}")
    if loaded:
        log.info(f"[Jobs] Restored {loaded} jobs from disk.")


_load_jobs_from_disk()


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Real Estate Video Generator", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protect all non-static endpoints with access key when UI_ACCESS_KEY is set."""
    path = request.url.path
    # Always allow: root UI, health check, static assets, clip previews
    # Clip previews need to be exempt because browsers can't send headers for <video src>
    if (path in ("/", "", "/health")
            or path.startswith("/static")
            or path.startswith("/test-scratch/")
            or "/clip/" in path
            or path.endswith("/download")
            or "/image/" in path):
        return await call_next(request)
    if not _check_access(request):
        return Response(
            content='{"detail":"Unauthorized — invalid access key"}',
            status_code=403,
            media_type="application/json"
        )
    return await call_next(request)


if (BASE_DIR / "ui.html").exists():
    @app.get("/", response_class=FileResponse)
    def serve_ui():
        return FileResponse(BASE_DIR / "ui.html")




# ── Utility endpoints ──────────────────────────────────────────────────────────


@app.get("/test-scratch/{filename}")
def serve_test_scratch(filename: str):
    """Serves files ONLY from jobs/_test_scratch/ — a dedicated directory
    for depth-rendering (or any other) test output that is NEVER touched
    by production job assembly code. This exists specifically so testing
    can never again contaminate a real client job's clips folder, which
    happened once already and corrupted a delivered video.
    """
    # Reject any path traversal attempt
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    test_path = JOBS_DIR / "_test_scratch" / filename
    if not test_path.exists():
        raise HTTPException(status_code=404, detail="Test file not found")
    return FileResponse(str(test_path), media_type="video/mp4")




@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}




@app.get("/credits")
def get_credits():
    from credit_monitor import get_all_credits
    return get_all_credits()




@app.get("/diagnostics")
def diagnostics():
    """System health check, disk space, API reachability, auto-cleanup of old jobs."""
    import shutil as _shutil
    import requests as _requests


    # Disk space
    disk   = _shutil.disk_usage(str(BASE_DIR))
    disk_free_gb = round(disk.free / (1024**3), 1)


    # Job stats
    total_jobs     = len(JOBS)
    done_jobs      = sum(1 for j in JOBS.values() if j.get("status") == "done")
    failed_jobs    = sum(1 for j in JOBS.values() if j.get("status") == "failed")
    running_jobs   = sum(1 for j in JOBS.values() if j.get("status") == "running")


    # Auto-cleanup: remove ALL job folders (any status — done, failed, or
    # stuck/abandoned mid-workflow) with no activity in the last 7 days.
    # Cutoff is based on job_meta.json's own filesystem last-modified time,
    # not the created_at field inside it — job_meta.json is rewritten by
    # _save_job() on every meaningful state change (progress updates,
    # narration steps, rework, etc.), so its mtime is an accurate "last
    # touched" timestamp. This is safer than created_at for not deleting
    # something that's old but was actually worked on recently.
    cutoff     = datetime.utcnow() - timedelta(days=7)
    cleaned    = 0
    freed_mb   = 0
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir() or job_dir.name == "_test_scratch":
            continue
        meta = job_dir / "job_meta.json"
        if not meta.exists():
            continue
        try:
            last_activity = datetime.utcfromtimestamp(meta.stat().st_mtime)
            if last_activity < cutoff:
                size_mb = sum(
                    f.stat().st_size for f in job_dir.rglob("*") if f.is_file()
                ) / (1024**2)
                shutil.rmtree(str(job_dir), ignore_errors=True)
                job_id = job_dir.name
                JOBS.pop(job_id, None)
                cleaned  += 1
                freed_mb += size_mb
        except Exception:
            pass


    # API reachability
    def _ping(url, headers=None, timeout=5):
        try:
            r = _requests.get(url, headers=headers, timeout=timeout)
            return r.status_code < 500
        except Exception:
            return False


    fal_key = os.getenv("FAL_KEY", "")
    el_key  = os.getenv("ELEVENLABS_API_KEY", "")


    fal_ok = _ping(
        "https://api.fal.ai/billing/credits",
        headers={"Authorization": f"Key {fal_key}"} if fal_key else None
    )
    el_ok = _ping(
        "https://api.elevenlabs.io/v1/user/subscription",
        headers={"xi-api-key": el_key} if el_key else None
    )


    return {
        "server_time":      datetime.utcnow().isoformat(),
        "disk_free_gb":     disk_free_gb,
        "jobs_total":       total_jobs,
        "jobs_done":        done_jobs,
        "jobs_failed":      failed_jobs,
        "jobs_running":     running_jobs,
        "fal_reachable":    fal_ok,
        "elevenlabs_reachable": el_ok,
        "cleaned_jobs":     cleaned,
        "freed_mb":         round(freed_mb, 1),
    }




# ── Maintenance scheduler endpoints ────────────────────────────────────────────
# The actual checks run on a daily cron via maintenance_scheduler.py (standalone
# script, not part of the request path). These endpoints just expose the latest
# report and let the alert-recipient list be edited from the UI.


@app.get("/maintenance/status")
def get_maintenance_status():
    """Returns the latest maintenance report for the UI panel."""
    import maintenance_scheduler
    if not maintenance_scheduler.STATUS_FILE.exists():
        return {"timestamp": None, "checks": [], "cleanup": {}, "any_red": False,
                "note": "No maintenance run has completed yet."}
    return json.loads(maintenance_scheduler.STATUS_FILE.read_text())


@app.get("/maintenance/alert-emails")
def get_alert_emails():
    import maintenance_scheduler
    return {"emails": maintenance_scheduler.load_alert_emails()}


@app.post("/maintenance/alert-emails")
def set_alert_emails(payload: dict):
    """Body: {"emails": ["a@x.com", "b@y.com"]}. Replaces the full list."""
    import maintenance_scheduler
    emails = payload.get("emails", [])
    if not isinstance(emails, list) or not all(isinstance(e, str) for e in emails):
        raise HTTPException(status_code=400, detail="emails must be a list of strings")
    maintenance_scheduler.save_alert_emails(emails)
    return {"emails": emails}




# ── Vision analysis endpoint ───────────────────────────────────────────────────


@app.post("/analyse-image")
async def analyse_image(image: UploadFile = File(...)):
    """
    Analyses an uploaded image using Florence-2 via fal.ai.
    Returns space type, depth, and recommended camera movement.
    Called from the UI immediately after each photo is uploaded.
    """
    # Validate file size
    MAX_SIZE = 20 * 1024 * 1024  # 20MB
    content  = await image.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 20MB)")


    # Validate file type
    if not _validate_image_bytes(content):
        raise HTTPException(status_code=400, detail="Invalid image file")


    # Save to temp file
    tmp_path = str(JOBS_DIR / f"tmp_analyse_{uuid.uuid4().hex[:8]}.jpg")
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)


        from vision_analysis import analyse_input
        result = await asyncio.to_thread(analyse_input, tmp_path)
        return result


    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass




# ── Job submission ─────────────────────────────────────────────────────────────


@app.post("/jobs/")
async def create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    config: str = Form(...),
    property_name: str = Form("Property"),
    voice_id: str = Form(""),
    enhance_images: bool = Form(True),
    upscale_images: bool = Form(True),
    do_video_upscale: bool = Form(True),
    transition_style: str = Form("fade"),
    enable_vision_qc: bool = Form(True),
    model_tier: str = Form("standard"),       # eco / standard / premium
    lighting: str = Form("bright_natural"),   # property-level lighting
    intensity: str = Form("natural_pace"),    # property-level motion intensity
    start_generation: bool = Form(True),      # False = draft mode, no video cost yet
):
    # Rate limit check
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Maximum 5 jobs per hour. Please wait before submitting again."
        )


    # Max images check
    if len(images) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 images per job")


    try:
        scenes_config = json.loads(config)
        if not isinstance(scenes_config, list):
            raise ValueError("config must be a JSON array")
        scenes_config = _ensure_scene_ids(scenes_config)  # assign permanent IDs
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config JSON: {e}")


    if len(images) != len(scenes_config):
        raise HTTPException(
            status_code=400,
            detail=f"Images ({len(images)}) must match scene configs ({len(scenes_config)})"
        )


    job_id  = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    img_dir = job_dir / "images"
    img_dir.mkdir(parents=True)


    saved_images = []
    for i, upload in enumerate(images):
        content = await upload.read()


        # Size check per image
        if len(content) > 20 * 1024 * 1024:
            shutil.rmtree(str(job_dir), ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Image {i+1} exceeds 20MB limit")


        # Type check by magic bytes
        if not _validate_image_bytes(content):
            shutil.rmtree(str(job_dir), ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Image {i+1} is not a valid image file")


        ext = Path(upload.filename).suffix.lower() or ".jpg"
        if upload.content_type == "image/jpeg": ext = ".jpg"
        elif upload.content_type == "image/png":  ext = ".png"
        elif upload.content_type == "image/webp": ext = ".webp"


        dest = img_dir / f"scene_{i:03d}{ext}"
        with open(dest, "wb") as f:
            f.write(content)
        saved_images.append(str(dest))


    # Cost estimate — uses ACTUAL rolling 30-day job count for infra cost,
    # not a static guess, so it adapts automatically as volume changes
    from cost_tracker import estimate_job_cost, format_cost_display
    rolling_jobs = _get_rolling_monthly_job_count()
    cost_estimate = estimate_job_cost(
        scenes_config,
        do_upscale=upscale_images,
        do_video_upscale=do_video_upscale,
        do_vision_qc=enable_vision_qc,
        model_tier=model_tier,
        actual_monthly_jobs=rolling_jobs,
    )


    JOBS[job_id] = {
        "status":           "draft" if not start_generation else "queued",
        "progress":         0,
        "message":          "Scene salvate — pronto per narrazione" if not start_generation else "Job queued",
        "scenes":           [],
        "scenes_config":    scenes_config,  # needed by narration endpoints even in draft mode
        "output_path":      None,
        "created_at":       datetime.utcnow().isoformat(),
        "property_name":    property_name,
        "total_scenes":     len(images),
        "transition_style": transition_style,
        "enable_vision_qc": enable_vision_qc,
        "do_video_upscale": do_video_upscale,
        "model_tier":       model_tier,
        "lighting":         lighting,
        "intensity":        intensity,
        "voice_id":         voice_id,
        "enhance_images":   enhance_images,
        "upscale_images":   upscale_images,
        "cost_estimate":    format_cost_display(cost_estimate),
        "cost_actual":      None,
        "reworks":          [],
        "qc_results":       [],
        "awaiting_scenes":  [],
    }
    _save_job(job_id)


    if start_generation:
        background_tasks.add_task(
            run_pipeline,
            job_id=job_id,
            job_dir=job_dir,
            image_paths=saved_images,
            scenes_config=scenes_config,
            property_name=property_name,
            voice_id=voice_id,
            do_lighting=enhance_images,
            do_upscale=upscale_images,
            transition_style=transition_style,
            enable_vision_qc=enable_vision_qc,
            do_video_upscale=do_video_upscale,
            model_tier=model_tier,
            lighting=lighting,
            intensity=intensity,
        )


    return {
        "job_id":       job_id,
        "status":       JOBS[job_id]["status"],
        "cost_estimate": format_cost_display(cost_estimate),
    }




@app.post("/jobs/{job_id}/start-generation")
async def start_generation_for_draft(job_id: str, background_tasks: BackgroundTasks):
    """
    Triggers actual video generation for a job that was created in draft
    mode (start_generation=False) — the second half of the narration-first
    workflow: photos + scenes were saved with no cost, narration was
    generated and durations confirmed, and NOW generation actually starts
    with the correct, already-verified durations. No rework ever needed
    purely for timing reasons.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    if job.get("status") != "draft":
        raise HTTPException(status_code=400, detail=f"Job is not in draft state (status: {job.get('status')})")


    if not _acquire_job_lock(job_id, "start generation"):
        lock = _job_lock_status(job_id)
        raise HTTPException(status_code=409, detail=f"Job is busy ({lock.get('operation')})")


    job_dir = JOBS_DIR / job_id
    scenes_config = job.get("scenes_config", [])
    image_paths = []
    for scene in scenes_config:
        sid = scene.get("scene_id")
        for ext in [".jpg", ".jpeg", ".png", ".webp"]:
            candidate = job_dir / "images" / f"{sid}{ext}"
            if candidate.exists():
                image_paths.append(str(candidate))
                break
        else:
            # Fallback to old index-based naming for the same scene
            idx = scenes_config.index(scene)
            for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                candidate = job_dir / "images" / f"scene_{idx:03d}{ext}"
                if candidate.exists():
                    image_paths.append(str(candidate))
                    break


    job["status"]  = "queued"
    job["message"] = "Generazione avviata"
    _save_job(job_id)
    _release_job_lock(job_id)  # run_pipeline manages its own lock internally via its update() calls


    background_tasks.add_task(
        run_pipeline,
        job_id=job_id,
        job_dir=job_dir,
        image_paths=image_paths,
        scenes_config=scenes_config,
        property_name=job.get("property_name", "Property"),
        voice_id=job.get("voice_id", ""),
        do_lighting=job.get("enhance_images", True),
        do_upscale=job.get("upscale_images", True),
        transition_style=job.get("transition_style", "fade"),
        enable_vision_qc=job.get("enable_vision_qc", True),
        do_video_upscale=job.get("do_video_upscale", True),
        model_tier=job.get("model_tier", "premium"),
        lighting=job.get("lighting", "bright_natural"),
        intensity=job.get("intensity", "natural_pace"),
    )


    return {"job_id": job_id, "status": "queued"}




# ══════════════════════════════════════════════════════════════════════════════
# NARRATION SYSTEM — single continuous voiceover, decoupled from video timing
# ══════════════════════════════════════════════════════════════════════════════
# Step A ("Genera voiceover") — cheap, TTS-only. Measures actual duration,
# calculates required scene durations BEFORE any video generation.
# Step B ("Genera video") — only runs once duration is confirmed correct.
# This prevents ever paying for a wrongly-timed video clip.


@app.post("/jobs/{job_id}/narration")
async def generate_narration(
    job_id: str,
    narration_text: str = Form(...),
    voice_id: str = Form(""),
):
    """
    Step A: generates the narration audio ONLY (cheap — ElevenLabs cost
    only, no Veo/Luma cost). Measures the actual duration and returns
    the calculated scene duration distribution for the UI to display
    BEFORE any video generation happens.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]


    if not _acquire_job_lock(job_id, "generate narration"):
        lock = _job_lock_status(job_id)
        raise HTTPException(status_code=409, detail=f"Job is busy ({lock.get('operation')})")


    try:
        job_dir = JOBS_DIR / job_id
        narration_path = str(job_dir / "narration.mp3")


        from narration import generate_narration_audio, calculate_scene_durations
        result = await asyncio.to_thread(
            generate_narration_audio, narration_text, narration_path,
            voice_id or None
        )


        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=result.get("error", "Narration generation failed"))


        scenes_config = job.get("scenes_config", [])
        n_scenes = len(scenes_config)
        current_durations = [int(s.get("duration", 6)) for s in scenes_config] or [6] * n_scenes


        distribution = calculate_scene_durations(
            narration_duration_secs=result["duration_secs"],
            scene_count=n_scenes,
            current_durations=current_durations,
        )


        job["narration_text"] = narration_text
        job["narration_path"] = narration_path
        job["narration_duration_secs"] = result["duration_secs"]
        job["narration_sentence_timings"] = result.get("sentence_timings", [])
        _save_job(job_id)


        return {
            "job_id": job_id,
            "narration_duration_secs": result["duration_secs"],
            "sentence_count": result.get("sentence_count", 0),
            **distribution,
        }
    finally:
        _release_job_lock(job_id)




@app.post("/jobs/{job_id}/narration/apply-durations")
async def apply_narration_durations(job_id: str, new_durations: str = Form(...)):
    """
    Applies the calculated (or user-adjusted) scene durations to the job's
    scenes_config BEFORE video generation — the final confirmation step
    of the "calculate first, generate once" flow.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]


    try:
        durations = json.loads(new_durations)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid durations: {e}")


    scenes_config = job.get("scenes_config", [])
    for i, d in enumerate(durations):
        if i < len(scenes_config):
            scenes_config[i]["duration"] = d
    job["scenes_config"] = scenes_config
    _save_job(job_id)


    return {"job_id": job_id, "scenes_config": scenes_config}




@app.post("/jobs/{job_id}/narration/reassemble")
async def reassemble_with_narration(job_id: str, background_tasks: BackgroundTasks):
    """
    Cheap path for when narration text changed but scene durations did
    NOT — no video regeneration needed, just re-run assembly with the
    latest narration audio overlaid. Zero Veo/Luma cost, just re-encoding
    the already-generated clips with new audio.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]


    if not job.get("narration_path"):
        raise HTTPException(status_code=400, detail="No narration generated yet for this job")


    if not _acquire_job_lock(job_id, "reassemble with narration"):
        lock = _job_lock_status(job_id)
        raise HTTPException(status_code=409, detail=f"Job is busy ({lock.get('operation')})")


    job["status"] = "running"
    job["message"] = "Riassemblaggio con nuova narrazione…"
    _save_job(job_id)


    background_tasks.add_task(run_reassemble_only, job_id)
    return {"job_id": job_id, "status": "running"}




# ── Job status & download ──────────────────────────────────────────────────────


@app.get("/jobs/")
def list_jobs():
    """Returns all jobs sorted by creation date, newest first."""
    jobs = []
    for job_id, job in JOBS.items():
        # Skip rework child jobs — show only parent jobs and completed reworks
        is_rework = "_rw" in job_id
        jobs.append({
            "job_id":       job_id,
            "is_rework":    is_rework,
            "parent_job_id": job.get("parent_job_id"),
            "property_name": job.get("property_name", "Property"),
            "status":       job.get("status", "unknown"),
            "progress":     job.get("progress", 0),
            "total_scenes": job.get("total_scenes", 0),
            "model_tier":   job.get("model_tier", "premium"),
            "created_at":   job.get("created_at", ""),
            "cost_estimate": job.get("cost_estimate"),
            "has_video":    bool(job.get("output_path") and Path(job["output_path"]).exists()),
        })
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return {"jobs": jobs, "total": len(jobs)}




@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id].copy()
    job.pop("output_path", None)
    return job




@app.get("/jobs/{job_id}/image/{scene_index}")
def get_scene_image(job_id: str, scene_index: int):
    """Serves the source image for a scene — used to rebuild scene cards
    when loading a past job from the library. Must return the ORIGINAL
    uploaded image, not the enhanced/upscaled version — the enhanced
    version is 30-50MB after aura-sr upscaling and would exceed the
    20MB upload limit when re-submitted as a fresh generation.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job_dir = JOBS_DIR / job_id


    # Original upload FIRST — enhanced version only as last-resort fallback
    candidates = []
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        candidates.append(job_dir / "images" / f"scene_{scene_index:03d}{ext}")
    candidates.append(job_dir / "enhanced" / f"scene_{scene_index:03d}_enhanced.jpg")


    for path in candidates:
        if path.exists():
            return FileResponse(
                str(path),
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"}
            )


    raise HTTPException(status_code=404, detail="Image not found")




@app.get("/jobs/{job_id}/clip/{scene_index}")
async def get_clip(job_id: str, scene_index: int, request: Request):
    """Serves a generated clip with range request support for fast browser preview.
    Range requests allow the browser to start playing immediately without downloading the full file.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    clip_path = JOBS_DIR / job_id / "clips" / f"scene_{scene_index:03d}.mp4"
    if not clip_path.exists():
        for job_dir in JOBS_DIR.glob(f"{job_id}*"):
            candidate = job_dir / "clips" / f"scene_{scene_index:03d}.mp4"
            if candidate.exists():
                clip_path = candidate
                break
    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")


    file_size = clip_path.stat().st_size
    range_header = request.headers.get("range")


    if range_header:
        # Parse range header e.g. "bytes=0-1023"
        from fastapi.responses import StreamingResponse
        import re
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end   = int(match.group(2)) if match.group(2) else file_size - 1
            end   = min(end, file_size - 1)
            chunk_size = end - start + 1


            def iter_file(path, start, chunk):
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = chunk
                    while remaining > 0:
                        data = f.read(min(65536, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data


            return StreamingResponse(
                iter_file(str(clip_path), start, chunk_size),
                status_code=206,
                media_type="video/mp4",
                headers={
                    "Content-Range":  f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges":  "bytes",
                    "Content-Length": str(chunk_size),
                    "Cache-Control":  "public, max-age=3600",
                }
            )


    return FileResponse(
        str(clip_path),
        media_type="video/mp4",
        headers={
            "Cache-Control":  "public, max-age=3600",
            "Accept-Ranges":  "bytes",
            "Content-Length": str(file_size),
        }
    )




@app.post("/jobs/{job_id}/stop")
def stop_job(job_id: str):
    """Marks a job as cancelled. The pipeline checks this flag between scenes
    and stops before starting the next one — already-generated clips are kept.
    Cannot interrupt a Veo API call already in progress for the current scene.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    JOBS[job_id]["cancel_requested"] = True
    _save_job(job_id)
    return {
        "job_id": job_id,
        "message": "Cancellazione richiesta — si fermerà dopo la scena corrente."
    }




@app.get("/jobs/{job_id}/download")
async def download_job(job_id: str, request: Request):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    if job["status"] not in ["done"]:
        raise HTTPException(status_code=400, detail=f"Job not ready (status: {job['status']})")
    output_path = job.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    filename = f"{job.get('property_name','property').replace(' ','_')}_video.mp4"


    file_size = Path(output_path).stat().st_size
    range_header = request.headers.get("range")


    if range_header:
        import re as _re
        from fastapi.responses import StreamingResponse
        match = _re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end   = int(match.group(2)) if match.group(2) else file_size - 1
            end   = min(end, file_size - 1)
            chunk_size = end - start + 1


            def _iter(path, s, c):
                with open(path, "rb") as f:
                    f.seek(s)
                    remaining = c
                    while remaining > 0:
                        data = f.read(min(65536, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data


            return StreamingResponse(
                _iter(output_path, start, chunk_size),
                status_code=206,
                media_type="video/mp4",
                headers={
                    "Content-Range":  f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges":  "bytes",
                    "Content-Length": str(chunk_size),
                    "Content-Disposition": f'attachment; filename="{filename}"',
                }
            )


    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=filename,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)}
    )




# ── QC approval gate ───────────────────────────────────────────────────────────


@app.post("/jobs/{job_id}/approve")
async def approve_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    approval: str = Form(...),
):
    """
    Called when user approves flagged scenes in the QC review panel.
    approval is a JSON object:
    {
      "approved_scenes": [0, 2],    <- scene indices user approved
      "redo_scenes":     [1],       <- scene indices user wants to redo
    }
    Only called when job status is "awaiting_approval".
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    if job["status"] != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Job is not awaiting approval")


    try:
        data = json.loads(approval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid approval JSON: {e}")


    redo_scenes     = data.get("redo_scenes", [])
    approved_scenes = data.get("approved_scenes", [])


    # Update qc_verdict for manually approved scenes so the library
    # preview reflects the accurate final status, not the stale AI verdict
    if approved_scenes:
        scenes = JOBS[job_id].get("scenes", [])
        for s in scenes:
            if s.get("index") in approved_scenes:
                s["qc_verdict"] = "approved"  # was reject/flag, now human-approved
        JOBS[job_id]["scenes"] = scenes


    if redo_scenes:
        # Mark job as needing rework for rejected scenes
        JOBS[job_id]["status"]  = "queued"
        JOBS[job_id]["message"] = f"Rework queued for {len(redo_scenes)} scene(s)"
        # Trigger rework for just the rejected scenes
        background_tasks.add_task(
            run_rework,
            rework_id=job_id,
            parent_job_id=job_id,
            cfg={
                "scenes":          redo_scenes,
                "redo_video":      True,
                "redo_audio":      False,
                "updated_scenes":  job.get("scenes_config", []),
                "then_assemble":   True,
            },
        )
    else:
        # All approved — proceed to assembly
        JOBS[job_id]["status"]  = "running"
        JOBS[job_id]["message"] = "Assembling final video…"
        job_dir = JOBS_DIR / job_id
        background_tasks.add_task(
            run_assembly,
            job_id=job_id,
            job_dir=job_dir,
        )


    _save_job(job_id)
    return {"job_id": job_id, "status": JOBS[job_id]["status"]}




# ── Rework endpoint ────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# NEW SOLID JOB MODEL — single directory per property, stable scene IDs, locking
# ══════════════════════════════════════════════════════════════════════════════
# This replaces the old sibling-directory rework model (kept below for any
# in-flight old jobs). All NEW edits should use these endpoints.
#
# Key guarantees:
#   - One job = one directory, forever. No more "_rw1234" siblings.
#   - Scenes identified by permanent scene_id, never by array index.
#   - Job lock prevents two operations touching the same job at once.
#   - Every operation either fully succeeds (job_meta.json updated) or fully
#     fails (job_meta.json untouched) — no partial/corrupted states.


@app.get("/jobs/{job_id}/lock-status")
def get_lock_status(job_id: str):
    return _job_lock_status(job_id)




@app.post("/jobs/{job_id}/scenes/{scene_id}/redo")
async def redo_scene(
    job_id: str,
    scene_id: str,
    background_tasks: BackgroundTasks,
    scene_update: str = Form(...),   # JSON: {caption, voiceover, space_type, pov_movement}
):
    """Regenerates exactly one scene, in place, in the job's own directory.
    No sibling job is created. Uses a lock to prevent concurrent edits.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    scenes_config = job.get("scenes_config", [])
    scene_idx = next((i for i, s in enumerate(scenes_config) if s.get("scene_id") == scene_id), None)
    if scene_idx is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found in this job")


    if not _acquire_job_lock(job_id, f"redo scene {scene_id}"):
        lock = _job_lock_status(job_id)
        raise HTTPException(
            status_code=409,
            detail=f"Job is currently being modified ({lock.get('operation')}) — please wait and try again."
        )


    try:
        updates = json.loads(scene_update)
    except Exception as e:
        _release_job_lock(job_id)
        raise HTTPException(status_code=400, detail=f"Invalid scene_update: {e}")


    # Apply the text/config updates to this scene now (before background task,
    # so the UI reflects the edit immediately even while generation is running)
    scenes_config[scene_idx].update({
        "caption":      updates.get("caption", scenes_config[scene_idx].get("caption", "")),
        "voiceover":    updates.get("voiceover", scenes_config[scene_idx].get("voiceover", "")),
        "space_type":   updates.get("space_type", scenes_config[scene_idx].get("space_type", "large")),
        "pov_movement": updates.get("pov_movement", scenes_config[scene_idx].get("pov_movement", "walk_in_explore")),
    })
    job["scenes_config"] = scenes_config
    job["status"] = "running"
    job["message"] = f"Rigenerazione scena in corso…"
    _save_job(job_id)


    background_tasks.add_task(run_redo_scene, job_id=job_id, scene_id=scene_id)
    return {"job_id": job_id, "scene_id": scene_id, "status": "running"}




@app.post("/jobs/{job_id}/scenes")
async def add_scene(
    job_id: str,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    scene_config: str = Form(...),   # JSON: {caption, voiceover, space_type, pov_movement, duration}
):
    """Adds one new scene to an existing job, in place. Saves the image
    directly into this job's own images/ folder — no ambiguity about
    where the source photo lives, ever.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]


    if not _acquire_job_lock(job_id, "add scene"):
        lock = _job_lock_status(job_id)
        raise HTTPException(
            status_code=409,
            detail=f"Job is currently being modified ({lock.get('operation')}) — please wait and try again."
        )


    try:
        cfg = json.loads(scene_config)
    except Exception as e:
        _release_job_lock(job_id)
        raise HTTPException(status_code=400, detail=f"Invalid scene_config: {e}")


    content = await image.read()
    if len(content) > 20 * 1024 * 1024:
        _release_job_lock(job_id)
        raise HTTPException(status_code=400, detail="Image exceeds 20MB limit")
    if not _validate_image_bytes(content):
        _release_job_lock(job_id)
        raise HTTPException(status_code=400, detail="Invalid image file")


    scene_id = _new_scene_id()
    new_scene = {
        "scene_id":     scene_id,
        "caption":      cfg.get("caption", ""),
        "voiceover":    cfg.get("voiceover", ""),
        "space_type":   cfg.get("space_type", "large"),
        "pov_movement": cfg.get("pov_movement", "walk_in_explore"),
        "duration":     cfg.get("duration", 8),
    }


    job_dir = JOBS_DIR / job_id
    img_dir = job_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)


    ext = ".jpg"
    if image.content_type == "image/png":  ext = ".png"
    elif image.content_type == "image/webp": ext = ".webp"
    dest = img_dir / f"{scene_id}{ext}"
    with open(dest, "wb") as f:
        f.write(content)
    log.info(f"[AddScene] Saved new scene image: {dest}")


    scenes_config = job.get("scenes_config", [])
    scenes_config.append(new_scene)
    job["scenes_config"]  = scenes_config
    job["total_scenes"]   = len(scenes_config)
    job["status"] = "running"
    job["message"] = "Generazione nuova scena in corso…"
    _save_job(job_id)


    background_tasks.add_task(run_redo_scene, job_id=job_id, scene_id=scene_id)
    return {"job_id": job_id, "scene_id": scene_id, "status": "running"}




@app.delete("/jobs/{job_id}/scenes/{scene_id}")
async def delete_scene(job_id: str, background_tasks: BackgroundTasks):
    """Removes a scene from the job and re-assembles, in place."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]


    if not _acquire_job_lock(job_id, "delete scene"):
        lock = _job_lock_status(job_id)
        raise HTTPException(status_code=409, detail=f"Job is currently being modified ({lock.get('operation')})")


    scenes_config = job.get("scenes_config", [])
    scenes_config = [s for s in scenes_config if s.get("scene_id") != scene_id]
    job["scenes_config"] = scenes_config
    job["total_scenes"]  = len(scenes_config)
    job["status"] = "running"
    job["message"] = "Riassemblaggio dopo rimozione scena…"
    _save_job(job_id)


    background_tasks.add_task(run_reassemble_only, job_id=job_id)
    return {"job_id": job_id, "status": "running"}




async def run_redo_scene(job_id: str, scene_id: str):
    """Regenerates ONE scene in place, then reassembles the whole job.
    Everything happens inside the job's own directory — no siblings.
    """
    def update(status, progress, message):
        JOBS[job_id].update({"status": status, "progress": progress, "message": message})
        _save_job(job_id)
        log.info(f"[Job {job_id}] {progress}% — {message}")


    try:
        job = JOBS[job_id]
        job_dir = JOBS_DIR / job_id
        scenes_config = job.get("scenes_config", [])
        scene_idx = next((i for i, s in enumerate(scenes_config) if s.get("scene_id") == scene_id), None)
        if scene_idx is None:
            raise ValueError(f"Scene {scene_id} not found")
        scene = scenes_config[scene_idx]


        lighting  = job.get("lighting", "bright_natural")
        intensity = job.get("intensity", "natural_pace")
        model_tier = job.get("model_tier", "premium")
        do_video_upscale = job.get("do_video_upscale", True)


        voiceover = scene.get("voiceover", "").strip()
        user_duration = int(scene.get("duration", 10))
        actual_duration = user_duration


        # ── Step 1: TTS ──────────────────────────────────────────────────
        audio_dir = job_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        audio_out = str(audio_dir / f"{scene_id}.mp3")


        if voiceover:
            update("running", 15, f"Rigenero voiceover…")
            from voice_generation import generate_speech as generate_voice
            ok_audio = await asyncio.to_thread(
                generate_voice, voiceover, audio_out,
                voice_id=os.getenv("DEFAULT_VOICE_ID") or None
            )
            if ok_audio and Path(audio_out).exists():
                try:
                    from pydub import AudioSegment
                    seg = AudioSegment.from_file(audio_out)
                    audio_secs = len(seg) / 1000.0
                    buffered   = audio_secs + 2.0
                    actual_duration = max(4, min(8, int(((buffered + 1.99) // 2) * 2)))
                    log.info(f"[Job {job_id}] Scene {scene_id}: audio={audio_secs:.1f}s → clip={actual_duration}s")
                except Exception as e:
                    log.warning(f"[Job {job_id}] Could not measure audio: {e}")


        # ── Step 2: find or create enhanced source image ──────────────────
        img_dir = job_dir / "images"
        enhanced_dir = job_dir / "enhanced"
        enhanced_dir.mkdir(exist_ok=True)


        source_img = None
        for ext in [".jpg", ".jpeg", ".png", ".webp"]:
            candidate = img_dir / f"{scene_id}{ext}"
            if candidate.exists():
                source_img = candidate
                break
        if not source_img:
            raise ValueError(f"No source image found for scene {scene_id}")


        enhanced_img = enhanced_dir / f"{scene_id}_enhanced.jpg"
        if not enhanced_img.exists():
            from image_enhance import enhance_image
            update("running", 25, "Miglioro immagine…")
            await asyncio.to_thread(enhance_image, str(source_img), str(enhanced_img), True, True)
        img_for_generation = str(enhanced_img) if enhanced_img.exists() else str(source_img)


        # ── Step 3: video generation ───────────────────────────────────────
        clips_dir = job_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        clip_out = str(clips_dir / f"{scene_id}.mp4")


        update("running", 40, f"Rigenero clip ({actual_duration}s)…")
        from video_generation import generate_video_single
        ok_video = await asyncio.to_thread(
            generate_video_single,
            img_for_generation, actual_duration, clip_out,
            space_type=scene.get("space_type", "large"),
            pov_movement=scene.get("pov_movement", "walk_in_explore"),
            lighting=lighting,
            intensity=intensity,
            model_tier=model_tier,
            do_video_upscale=do_video_upscale,
        )


        if not ok_video:
            raise RuntimeError("Video generation failed")


        # Update scene status
        statuses = job.get("scenes", [])
        found = False
        for s in statuses:
            if s.get("scene_id") == scene_id:
                s.update({"video": "ok", "audio": "ok" if voiceover else "skipped", "duration_used": actual_duration})
                found = True
                break
        if not found:
            statuses.append({
                "scene_id": scene_id, "index": scene_idx,
                "caption": scene.get("caption", ""), "video": "ok",
                "audio": "ok" if voiceover else "skipped",
                "duration_used": actual_duration, "qc_verdict": "pass",
            })
        job["scenes"] = statuses
        _save_job(job_id)


        # ── Step 4: reassemble using ALL current scenes ────────────────────
        await run_reassemble_only(job_id)


    except Exception as e:
        log.error(f"[Job {job_id}] redo_scene failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Errore: {str(e)[:200]}"})
        _save_job(job_id)
    finally:
        _release_job_lock(job_id)




async def run_reassemble_only(job_id: str):
    """Reassembles the final video from whatever clips currently exist for
    this job's scenes_config, in order. Does not regenerate anything —
    pure assembly step, using each scene's stable scene_id to find its clip.
    """
    def update(status, progress, message):
        JOBS[job_id].update({"status": status, "progress": progress, "message": message})
        _save_job(job_id)
        log.info(f"[Job {job_id}] {progress}% — {message}")


    try:
        job = JOBS[job_id]
        job_dir = JOBS_DIR / job_id
        scenes_config = job.get("scenes_config", [])


        update("running", 85, "Riassemblaggio video finale…")


        clip_paths  = []
        audio_paths = []
        for scene_idx, scene in enumerate(scenes_config):
            sid = scene.get("scene_id")
            clip_path  = job_dir / "clips" / f"{sid}.mp4"
            audio_path = job_dir / "audio" / f"{sid}.mp3"


            # FALLBACK: some jobs predate the scene_id architecture and
            # only have legacy scene_NNN.mp4 / scene_NNN.mp3 files. If the
            # scene_id-named file isn't found, fall back to the legacy
            # index-based name — and self-heal by copying it to the new
            # scene_id name, so this fallback is never needed again for
            # this job on future reassembly calls.
            if not clip_path.exists():
                legacy_clip = job_dir / "clips" / f"scene_{scene_idx:03d}.mp4"
                if legacy_clip.exists():
                    shutil.copy2(str(legacy_clip), str(clip_path))
                    log.info(f"[Job {job_id}] Migrated legacy clip scene_{scene_idx:03d}.mp4 → {sid}.mp4")


            if not audio_path.exists():
                legacy_audio = job_dir / "audio" / f"scene_{scene_idx:03d}.mp3"
                if legacy_audio.exists():
                    shutil.copy2(str(legacy_audio), str(audio_path))
                    log.info(f"[Job {job_id}] Migrated legacy audio scene_{scene_idx:03d}.mp3 → {sid}.mp3")


            if not clip_path.exists():
                log.warning(f"[Job {job_id}] Missing clip for scene {sid} (index {scene_idx}) — skipping from assembly")
                continue
            clip_paths.append(str(clip_path))
            audio_paths.append(str(audio_path) if audio_path.exists() else None)


        if not clip_paths:
            raise RuntimeError("Nessuna clip disponibile per l'assemblaggio")


        output_path = str(job_dir / f"{job.get('property_name','Property').replace(' ','_')}_final.mp4")
        from video_assembly import assemble_property_video
        ok = await asyncio.to_thread(
            assemble_property_video,
            scenes_config=scenes_config,
            video_clip_paths=clip_paths,
            audio_paths=audio_paths,
            image_paths=clip_paths,
            output_path=output_path,
            property_name=job.get("property_name", "Property"),
            transition_style=job.get("transition_style", "fade"),
        )
        if not ok:
            raise RuntimeError("Assemblaggio fallito")


        # Apply narration audio if this job has a single continuous
        # narration track — this is what makes "narration changed but
        # video durations unchanged" work correctly: reassembly still
        # runs and picks up the LATEST narration file every time.
        narration_path = job.get("narration_path")
        if narration_path and os.path.exists(narration_path):
            update("running", 95, "Applying narration audio…")
            await asyncio.to_thread(_overlay_narration_audio, output_path, narration_path)
            log.info(f"[Job {job_id}] Narration audio applied: {narration_path}")


        job["output_path"] = output_path
        update("done", 100, "Video pronto per il download")


    except Exception as e:
        log.error(f"[Job {job_id}] reassembly failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Errore assemblaggio: {str(e)[:200]}"})
        _save_job(job_id)
    finally:
        _release_job_lock(job_id)




# ══════════════════════════════════════════════════════════════════════════════
# LEGACY sibling-directory rework model — kept only for any old in-flight jobs.
# Do not build new features on this. Use the endpoints above instead.
# ══════════════════════════════════════════════════════════════════════════════


@app.post("/jobs/{job_id}/rework")
async def rework_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    rework_config: str = Form(...),
    new_images: list[UploadFile] = File(default=[]),
    new_image_indices: list[str] = Form(default=[]),
):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    original = JOBS[job_id]
    if original["status"] not in ["done", "failed", "awaiting_approval"]:
        raise HTTPException(status_code=400, detail="Job must be completed before rework")


    try:
        cfg = json.loads(rework_config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid rework_config: {e}")


    # Save any newly uploaded scene images (scenes added via "+ Aggiungi scena"
    # that don't exist yet in the original job's images/ directory)
    job_dir  = JOBS_DIR / job_id
    img_dir  = job_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)


    for upload, idx_str in zip(new_images, new_image_indices):
        try:
            idx = int(idx_str)
            content = await upload.read()
            if not _validate_image_bytes(content):
                log.warning(f"[Rework] New image for scene {idx} failed validation, skipping")
                continue
            ext = ".jpg"
            if upload.content_type == "image/png":  ext = ".png"
            elif upload.content_type == "image/webp": ext = ".webp"
            dest = img_dir / f"scene_{idx:03d}{ext}"
            with open(dest, "wb") as f:
                f.write(content)
            log.info(f"[Rework] Saved new scene image: {dest}")
        except Exception as e:
            log.error(f"[Rework] Failed to save new image for index {idx_str}: {e}")


    rework_id = f"{job_id}_rw{str(uuid.uuid4())[:4]}"
    updated_scene_count = len(cfg.get("updated_scenes", [])) or original["total_scenes"]
    JOBS[rework_id] = {
        "status":        "queued",
        "progress":      0,
        "message":       f"Rework of job {job_id} queued",
        "parent_job_id": job_id,
        "output_path":   None,
        "created_at":    datetime.utcnow().isoformat(),
        "property_name": original["property_name"],
        "total_scenes":  updated_scene_count,
        "cost_actual":   None,
    }


    background_tasks.add_task(run_rework, rework_id=rework_id, parent_job_id=job_id, cfg=cfg,
                              do_video_upscale=JOBS[job_id].get("do_video_upscale", True))
    return {"job_id": rework_id, "status": "queued", "parent_job_id": job_id}




# ── Pipeline runner ────────────────────────────────────────────────────────────


async def run_pipeline(
    job_id:           str,
    job_dir:          Path,
    image_paths:      list,
    scenes_config:    list,
    property_name:    str,
    voice_id:         str,
    do_lighting:      bool,
    do_upscale:       bool,
    transition_style: str  = "fade",
    enable_vision_qc: bool = True,
    do_video_upscale: bool = True,
    model_tier:       str  = "standard",
    lighting:         str  = "bright_natural",
    intensity:        str  = "natural_pace",
):
    def update(status, progress, message):
        JOBS[job_id].update({"status": status, "progress": progress, "message": message})
        log.info(f"[Job {job_id}] {progress}% — {message}")


    # Store scenes_config for approval step
    JOBS[job_id]["scenes_config"] = scenes_config


    try:
        update("running", 2, "Starting pipeline…")


        from credit_monitor import check_and_alert
        credit_status = check_and_alert(job_id=job_id, property_name=property_name)
        JOBS[job_id]["credits"] = credit_status


        enhanced_dir    = job_dir / "enhanced"
        audio_dir       = job_dir / "audio"
        video_clips_dir = job_dir / "clips"
        for d in [enhanced_dir, audio_dir, video_clips_dir]:
            d.mkdir(exist_ok=True)


        n              = len(image_paths)
        enhanced_paths = []
        audio_paths    = []
        video_clip_paths = []
        scene_statuses = []
        qc_results     = []
        models_used    = []
        audio_chars    = []


        # ── Stage 1: Watermark removal (explicit per-scene, AI-driven) ────
        # Only runs for scenes where the user explicitly checked the
        # "remove watermark" toggle — never automatic. If removal fails,
        # we fall back to the original image and flag it as a QC issue
        # rather than silently using a possibly-botched result.
        from watermark_removal import remove_watermark
        watermark_qc_issues = []
        working_image_paths = list(image_paths)  # may get swapped per-scene below


        for i, scene in enumerate(scenes_config):
            if not scene.get("remove_watermark"):
                continue
            update("running", int(2 + (i/n)*3), f"Rimozione watermark scena {i}…")
            wm_out = str(enhanced_dir / f"scene_{i:03d}_dewatermarked.jpg")
            wm_result = await asyncio.to_thread(remove_watermark, image_paths[i], wm_out)
            if wm_result.get("ok"):
                working_image_paths[i] = wm_out
                log.info(f"[Job {job_id}] Watermark removed for scene {i}")
            else:
                watermark_qc_issues.append(i)
                log.warning(f"[Job {job_id}] Watermark removal failed for scene {i} — "
                            f"using original image, flagged for QC review")


        # ── Stage 2: Image enhancement ────────────────────────────────────
        from image_enhance import enhance_image
        for i, img_path in enumerate(working_image_paths):
            update("running", int(5 + (i/n)*15), f"Enhancing image {i} of {n-1} (scene_{i:03d})…")
            out    = str(enhanced_dir / f"scene_{i:03d}_enhanced.jpg")
            result = await asyncio.to_thread(enhance_image, img_path, out, do_lighting, do_upscale)
            enhanced_paths.append(result)


        # Surface any watermark removal failures as QC issues now that
        # enhancement is done and qc_results exists to append into
        for i in watermark_qc_issues:
            qc_results.append({
                "scene": i, "type": "watermark",
                "verdict": "flag",
                "issues": ["Rimozione watermark non riuscita — immagine originale usata, watermark ancora presente"],
            })


        # ── Stage 3: TTS audio + TTS QC → sets actual clip duration ──────
        from voice_generation import generate_speech as generate_voice
        from vision_analysis  import analyse_tts


        actual_durations = []   # per scene — set from audio or user slider


        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            voiceover     = scene.get("voiceover", "").strip()
            audio_out     = str(audio_dir / f"scene_{i:03d}.mp3")
            user_duration = int(scene.get("duration", 10))
            update("running", int(20 + (i/n)*15), f"Generating audio {i} of {n-1} (scene_{i:03d})…")


            if voiceover:
                ok = await asyncio.to_thread(
                    generate_voice, voiceover, audio_out,
                    voice_id=voice_id or None
                )
                if ok:
                    # TTS QC — also measures actual duration
                    tts_qc = await asyncio.to_thread(analyse_tts, audio_out, voiceover)
                    log.info(f"[Job {job_id}] TTS QC scene {i}: {tts_qc['verdict']}")


                    if tts_qc["verdict"] == "reject":
                        log.warning(f"[Job {job_id}] TTS rejected scene {i}: {tts_qc['issues']}")
                        audio_paths.append(None)
                        actual_durations.append(user_duration)
                    else:
                        audio_paths.append(audio_out)
                        # Set clip duration = actual audio duration + 2s buffer
                        # Snap to nearest valid duration, minimum 6s
                        audio_secs   = tts_qc.get("duration_seconds", 0)
                        if audio_secs > 0:
                            buffered = audio_secs + 2.0
                            # Snap to even number, min 6, max 20
                            snapped  = max(6, min(20, int(round(buffered / 2) * 2)))
                            log.info(
                                f"[Job {job_id}] Scene {i}: audio={audio_secs:.1f}s "
                                f"→ clip duration={snapped}s"
                            )
                            actual_durations.append(snapped)
                        else:
                            actual_durations.append(user_duration)


                    qc_results.append({"scene": i, "type": "tts", **tts_qc})
                else:
                    audio_paths.append(None)
                    actual_durations.append(user_duration)
                audio_chars.append({"chars": len(voiceover)})
            else:
                audio_paths.append(None)
                audio_chars.append({"chars": 0})
                actual_durations.append(user_duration)


        # ── Stage 3: Video generation + Vision QC ─────────────────────────
        from video_generation  import generate_video_single
        from vision_analysis   import analyse_output


        flagged_scenes  = []
        rejected_scenes = []


        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            # Check for cancellation request between scenes
            if JOBS.get(job_id, {}).get("cancel_requested"):
                log.info(f"[Job {job_id}] Cancellation requested — stopping before scene {i}")
                update("stopped", int(35 + (i/n)*40),
                       f"Fermato dall'utente — {i} di {n} scene completate. "
                       f"Puoi riassemblare con le scene già pronte, o riavviare la generazione.")
                return


            clip_out     = str(video_clips_dir / f"scene_{i:03d}.mp4")
            # Use actual audio duration if available, fall back to user setting
            duration     = actual_durations[i] if i < len(actual_durations) else int(scene.get("duration", 10))
            caption      = scene.get("caption", "")
            space_type   = scene.get("space_type",   "large")
            pov_movement = scene.get("pov_movement", "walk_in_explore")
            update("running", int(35 + (i/n)*40), f"Generating video clip {i} of {n-1} (scene_{i:03d}, {duration}s)…")


            ok = await asyncio.to_thread(
                generate_video_single,
                img, duration, clip_out,
                space_type=space_type,
                pov_movement=pov_movement,
                lighting=lighting,
                intensity=intensity,
                model_tier=model_tier,
                do_video_upscale=do_video_upscale,
            )


            model = model_tier


            models_used.append(model)
            video_clip_paths.append(clip_out if ok else None)


            # Vision QC
            video_verdict = "pass"
            if ok and enable_vision_qc and Path(clip_out).exists():
                update("running", int(35 + (i/n)*40), f"QC check on clip {i} of {n-1} (scene_{i:03d})…")
                original_img = image_paths[i]
                vid_qc = await asyncio.to_thread(analyse_output, clip_out, original_img, space_type)
                video_verdict = vid_qc["verdict"]
                log.info(f"[Job {job_id}] Video QC scene {i}: {video_verdict}")
                qc_results.append({"scene": i, "type": "video", **vid_qc})


                if video_verdict == "reject":
                    rejected_scenes.append(i)
                elif video_verdict == "flag":
                    flagged_scenes.append(i)
            elif not ok:
                video_verdict = "failed"


            scene_statuses.append({
                "index":           i,
                "caption":         caption,
                "space_type":      space_type,
                "pov_movement":    pov_movement,
                "duration_used":   duration,
                "video":           "ok" if ok else "failed",
                "audio":           "ok" if audio_paths[i] else "skipped",
                "qc_verdict":      video_verdict,
            })


        JOBS[job_id]["scenes"]     = scene_statuses
        JOBS[job_id]["qc_results"] = qc_results
        _save_job(job_id)


        # ── QC gate: pause if any scenes rejected or flagged ──────────────
        if rejected_scenes or flagged_scenes:
            awaiting = {
                "rejected": rejected_scenes,
                "flagged":  flagged_scenes,
            }
            JOBS[job_id]["awaiting_scenes"]  = awaiting
            JOBS[job_id]["video_clip_paths"] = video_clip_paths
            JOBS[job_id]["audio_paths"]      = audio_paths
            JOBS[job_id]["enhanced_paths"]   = enhanced_paths
            update(
                "awaiting_approval", 75,
                f"QC review needed: {len(rejected_scenes)} rejected, "
                f"{len(flagged_scenes)} flagged. Please review before assembly."
            )
            _save_job(job_id)
            return   # pipeline pauses here — resumed by /approve endpoint


        # ── Stage 4: Assembly ─────────────────────────────────────────────
        JOBS[job_id]["video_clip_paths"] = video_clip_paths
        JOBS[job_id]["audio_paths"]      = audio_paths
        JOBS[job_id]["enhanced_paths"]   = enhanced_paths
        await run_assembly(job_id, job_dir)


        # ── Actual cost ───────────────────────────────────────────────────
        from cost_tracker import calculate_actual_cost, format_cost_display
        actual = calculate_actual_cost(
            scenes_config, models_used, audio_chars,
            do_upscale=do_upscale, do_vision_qc=enable_vision_qc,
            model_tier=model_tier,
        )
        JOBS[job_id]["cost_actual"] = format_cost_display(actual)
        _save_job(job_id)


        check_and_alert(job_id=job_id, property_name=property_name)


    except Exception as e:
        log.error(f"[Job {job_id}] Pipeline failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Error: {str(e)}"})
        _save_job(job_id)




# ── Assembly step (called from pipeline and from /approve) ────────────────────


async def run_assembly(job_id: str, job_dir: Path):
    def update(status, progress, message):
        JOBS[job_id].update({"status": status, "progress": progress, "message": message})
        log.info(f"[Job {job_id}] {progress}% — {message}")


    try:
        job              = JOBS[job_id]
        scenes_config    = job.get("scenes_config", [])
        video_clip_paths = job.get("video_clip_paths", [])
        audio_paths      = job.get("audio_paths", [])
        enhanced_paths   = job.get("enhanced_paths", [])
        property_name    = job.get("property_name", "Property")
        transition_style = job.get("transition_style", "fade")


        update("running", 82, "Assembling final video…")
        output_path = str(job_dir / f"{property_name.replace(' ','_')}_final.mp4")


        from video_assembly import assemble_property_video
        ok = await asyncio.to_thread(
            assemble_property_video,
            scenes_config=scenes_config,
            video_clip_paths=video_clip_paths,
            audio_paths=audio_paths,
            image_paths=enhanced_paths,
            output_path=output_path,
            property_name=property_name,
            transition_style=transition_style,
        )


        if not ok:
            raise RuntimeError("Assembly returned failure")


        # If a single continuous narration was generated (new decoupled
        # narration system), overlay it onto the finished video now — this
        # REPLACES any per-scene audio that assembly may have added, since
        # the new system is one continuous track, not per-scene snippets.
        # Done as a separate step so we never need to touch the existing
        # per-scene assembly logic in video_assembly.py.
        narration_path = job.get("narration_path")
        if narration_path and os.path.exists(narration_path):
            update("running", 95, "Applying narration audio…")
            await asyncio.to_thread(_overlay_narration_audio, output_path, narration_path)
            log.info(f"[Job {job_id}] Narration audio applied: {narration_path}")


        JOBS[job_id]["output_path"] = output_path
        update("done", 100, "Video ready for download")
        _save_job(job_id)


    except Exception as e:
        log.error(f"[Assembly {job_id}] Failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Assembly error: {str(e)}"})
        _save_job(job_id)




# ── Rework runner ──────────────────────────────────────────────────────────────


async def run_rework(rework_id: str, parent_job_id: str, cfg: dict, do_video_upscale: bool = True):
    def update(status, progress, message):
        JOBS[rework_id].update({"status": status, "progress": progress, "message": message})
        _save_job(rework_id)
        log.info(f"[Rework {rework_id}] {progress}% — {message}")


    try:
        if parent_job_id not in JOBS:
            raise ValueError(f"Parent job {parent_job_id} not found")


        parent     = JOBS[parent_job_id]
        parent_dir = JOBS_DIR / parent_job_id
        rework_dir = JOBS_DIR / rework_id
        rework_dir.mkdir(exist_ok=True)


        # Copy existing clips/audio/enhanced from parent job
        # Use dirs_exist_ok=True to avoid FileExistsError on retry
        for sub in ["enhanced", "audio", "clips"]:
            src = parent_dir / sub
            dst = rework_dir / sub
            if src.exists() and not dst.exists():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            elif not dst.exists():
                (rework_dir / sub).mkdir(exist_ok=True)


        scenes_to_redo = cfg.get("scenes", [])
        redo_video     = cfg.get("redo_video", True)
        redo_audio     = cfg.get("redo_audio", False)
        updated_scenes = cfg.get("updated_scenes", [])
        n              = max(len(scenes_to_redo), 1)


        # Get model settings from parent job
        model_tier  = parent.get("model_tier",  "premium")
        lighting    = parent.get("lighting",    "bright_natural")
        intensity   = parent.get("intensity",   "natural_pace")


        update("running", 5, f"Rework di {len(scenes_to_redo)} scena/e…")


        # Save the COMPLETE scene list for this job — not just the reworked ones.
        # This ensures opening this job later shows exactly what was produced,
        # with no ambiguity about which scenes came from where.
        JOBS[rework_id]["scenes_config"] = updated_scenes
        JOBS[rework_id]["total_scenes"]  = len(updated_scenes)
        _save_job(rework_id)


        from voice_generation import generate_speech as generate_voice
        from video_generation import generate_video_single
        from pydub import AudioSegment as _AudioSegment


        scene_statuses = list(parent.get("scenes", []))


        for idx, scene_index in enumerate(scenes_to_redo):
            # Check for cancellation request between scenes
            if JOBS.get(rework_id, {}).get("cancel_requested"):
                log.info(f"[Rework {rework_id}] Cancellation requested — stopping")
                update("failed", int(10 + (idx/n)*80), f"Fermato dall'utente dopo {idx} scene")
                return


            scene = updated_scenes[scene_index] if scene_index < len(updated_scenes) else {}
            voiceover    = scene.get("voiceover", "").strip()
            space_type   = scene.get("space_type",   "large")
            pov_movement = scene.get("pov_movement", "walk_in_explore")
            user_duration = int(scene.get("duration", 10))


            # ── Step 1: Generate TTS audio first ──────────────────────────────
            audio_out = str(rework_dir / "audio" / f"scene_{scene_index:03d}.mp3")
            actual_duration = user_duration  # fallback


            if voiceover:
                update("running", int(10 + (idx/n)*20), f"Rigenero audio scena {scene_index} (scene_{scene_index:03d})…")
                ok_audio = await asyncio.to_thread(
                    generate_voice, voiceover, audio_out,
                    voice_id=os.getenv("DEFAULT_VOICE_ID") or None
                )
                if ok_audio and Path(audio_out).exists():
                    try:
                        seg = _AudioSegment.from_file(audio_out)
                        audio_secs = len(seg) / 1000.0
                        buffered   = audio_secs + 2.0
                        actual_duration = max(4, min(20, int(((buffered + 1.99) // 2) * 2)))
                        log.info(f"[Rework] Scene {scene_index}: audio={audio_secs:.1f}s → clip={actual_duration}s")
                    except Exception as e:
                        log.warning(f"[Rework] Could not measure audio: {e}")


            # ── Step 2: Generate video at correct duration ────────────────────
            clip_out = str(rework_dir / "clips" / f"scene_{scene_index:03d}.mp4")


            # Find source image
            enhanced_img = str(rework_dir / "enhanced" / f"scene_{scene_index:03d}_enhanced.jpg")
            if not Path(enhanced_img).exists():
                enhanced_img = str(parent_dir / "enhanced" / f"scene_{scene_index:03d}_enhanced.jpg")
            if not Path(enhanced_img).exists():
                for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                    candidate = parent_dir / "images" / f"scene_{scene_index:03d}{ext}"
                    if candidate.exists():
                        enhanced_img = str(candidate)
                        break


            if not Path(enhanced_img).exists():
                log.error(f"[Rework] No source image for scene {scene_index}")
                update("running", int(30 + (idx/n)*50), f"Scena {scene_index} (scene_{scene_index:03d}): immagine non trovata")
                continue


            update("running", int(30 + (idx/n)*50), f"Rigenero clip scena {scene_index} (scene_{scene_index:03d}, {actual_duration}s)…")
            ok_video = await asyncio.to_thread(
                generate_video_single,
                enhanced_img, actual_duration, clip_out,
                space_type=space_type,
                pov_movement=pov_movement,
                lighting=lighting,
                intensity=intensity,
                model_tier=model_tier,
                do_video_upscale=do_video_upscale,
            )


            # Update scene status — append new entry if this scene index
            # doesn't exist yet (e.g. a newly added scene beyond the original count)
            found = False
            for s in scene_statuses:
                if s.get("index") == scene_index:
                    s["video"]      = "ok" if ok_video else "failed"
                    s["audio"]      = "ok" if voiceover else "skipped"
                    s["space_type"]   = space_type
                    s["pov_movement"] = pov_movement
                    s["qc_verdict"]   = s.get("qc_verdict", "pass")
                    found = True
                    break
            if not found:
                scene_statuses.append({
                    "index":        scene_index,
                    "caption":      scene.get("caption", ""),
                    "space_type":   space_type,
                    "pov_movement": pov_movement,
                    "duration_used": actual_duration,
                    "video":        "ok" if ok_video else "failed",
                    "audio":        "ok" if voiceover else "skipped",
                    "qc_verdict":   "pass",
                })


        scene_statuses.sort(key=lambda s: s.get("index", 0))
        JOBS[rework_id]["scenes"] = scene_statuses
        _save_job(rework_id)


        update("running", 85, "Riassemblaggio video finale…")
        output_path = str(rework_dir / f"{parent['property_name'].replace(' ','_')}_rework.mp4")


        # Copy clips for scenes NOT in scenes_to_redo (those were just regenerated above)
        # Always use the most recent clip across all related job directories
        dst_clips    = rework_dir / "clips"
        dst_clips.mkdir(exist_ok=True)
        base_job_id  = parent_job_id.split("_rw")[0]
        all_job_dirs = sorted(
            [d for d in JOBS_DIR.iterdir()
             if d.is_dir() and (d.name == base_job_id or d.name.startswith(base_job_id + "_rw"))],
            key=lambda d: d.stat().st_mtime, reverse=True  # newest first
        )
        n_scenes = parent.get("total_scenes", len(updated_scenes))
        for scene_idx in range(n_scenes):
            if scene_idx in scenes_to_redo:
                continue  # already regenerated
            clip_name = f"scene_{scene_idx:03d}.mp4"
            dst = dst_clips / clip_name
            if dst.exists():
                continue
            for job_dir in all_job_dirs:
                src = job_dir / "clips" / clip_name
                if src.exists():
                    shutil.copy2(str(src), str(dst))
                    log.info(f"[Rework] Scene {scene_idx}: reusing clip from {job_dir.name}")
                    break


        # CRITICAL FIX: only ever consider scene_NNN.mp4 files where NNN is
        # strictly within this job's actual scene count. An unrestricted
        # glob here would pick up ANY file matching the naming pattern —
        # including stray test/debug files that happen to sit in this
        # directory — regardless of whether they're legitimate scenes.
        # This was the root cause of test artifacts appearing as extra
        # scenes in client-facing videos.
        clip_paths = []
        for scene_idx in range(n_scenes):
            candidate = dst_clips / f"scene_{scene_idx:03d}.mp4"
            if candidate.exists():
                clip_paths.append(candidate)
            else:
                log.warning(f"[Rework] Scene {scene_idx} has no clip — will be missing from assembly")


        if not clip_paths:
            raise RuntimeError("Nessuna clip trovata per l'assemblaggio")


        audio_paths = []
        for cp in clip_paths:
            ap = rework_dir / "audio" / cp.name.replace(".mp4", ".mp3")
            audio_paths.append(str(ap) if ap.exists() else None)


        from video_assembly import assemble_property_video
        ok = await asyncio.to_thread(
            assemble_property_video,
            scenes_config=updated_scenes or [{}] * len(clip_paths),
            video_clip_paths=[str(p) for p in clip_paths],
            audio_paths=audio_paths,
            image_paths=[str(p) for p in clip_paths],
            output_path=output_path,
            property_name=parent["property_name"],
        )


        if not ok:
            raise RuntimeError("Assemblaggio rework fallito")


        JOBS[rework_id]["output_path"] = output_path
        update("done", 100, "Rework video pronto per il download")


    except Exception as e:
        log.error(f"[Rework {rework_id}] Failed: {e}", exc_info=True)
        JOBS[rework_id].update({
            "status":  "failed",
            "message": f"Errore rework: {str(e)[:200]}"
        })
        _save_job(rework_id)
