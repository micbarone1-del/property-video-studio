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

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

JOBS: dict = {}

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

if (BASE_DIR / "ui.html").exists():
    @app.get("/", response_class=FileResponse)
    def serve_ui():
        return FileResponse(BASE_DIR / "ui.html")


# ── Utility endpoints ──────────────────────────────────────────────────────────

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

    # Auto-cleanup: remove job folders older than 7 days
    cutoff     = datetime.utcnow() - timedelta(days=7)
    cleaned    = 0
    freed_mb   = 0
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        meta = job_dir / "job_meta.json"
        if not meta.exists():
            continue
        try:
            with open(meta) as f:
                data = json.load(f)
            created = datetime.fromisoformat(data.get("created_at", "2000-01-01"))
            if created < cutoff and data.get("status") in ["done", "failed"]:
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
    img_dir.mkdir(parents=True, exist_ok=True)

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

    # Cost estimate
    from cost_tracker import estimate_job_cost, format_cost_display
    cost_estimate = estimate_job_cost(
        scenes_config,
        do_upscale=upscale_images,
        do_vision_qc=enable_vision_qc,
    )

    JOBS[job_id] = {
        "status":           "queued",
        "progress":         0,
        "message":          "Job queued",
        "scenes":           [],
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
        "cost_estimate":    format_cost_display(cost_estimate),
        "cost_actual":      None,
        "reworks":          [],
        "qc_results":       [],
        "awaiting_scenes":  [],
    }
    _save_job(job_id)

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
        "status":       "queued",
        "cost_estimate": format_cost_display(cost_estimate),
    }


# ── Job status & download ──────────────────────────────────────────────────────

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id].copy()
    job.pop("output_path", None)
    return job


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    if job["status"] not in ["done"]:
        raise HTTPException(status_code=400, detail=f"Job not ready (status: {job['status']})")
    output_path = job.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    filename = f"{job.get('property_name','property').replace(' ','_')}_video.mp4"
    return FileResponse(output_path, media_type="video/mp4", filename=filename)


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

    redo_scenes = data.get("redo_scenes", [])

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

@app.post("/jobs/{job_id}/rework")
async def rework_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    rework_config: str = Form(...),
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

    rework_id = f"{job_id}_rw{str(uuid.uuid4())[:4]}"
    JOBS[rework_id] = {
        "status":        "queued",
        "progress":      0,
        "message":       f"Rework of job {job_id} queued",
        "parent_job_id": job_id,
        "output_path":   None,
        "created_at":    datetime.utcnow().isoformat(),
        "property_name": original["property_name"],
        "total_scenes":  original["total_scenes"],
        "cost_actual":   None,
    }

    background_tasks.add_task(run_rework, rework_id=rework_id, parent_job_id=job_id, cfg=cfg)
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

        # ── Stage 1: Image enhancement ────────────────────────────────────
        from image_enhance import enhance_image
        for i, img_path in enumerate(image_paths):
            update("running", int(5 + (i/n)*15), f"Enhancing image {i+1} of {n}…")
            out    = str(enhanced_dir / f"scene_{i:03d}_enhanced.jpg")
            result = await asyncio.to_thread(enhance_image, img_path, out, do_lighting, do_upscale)
            enhanced_paths.append(result)

        # ── Stage 2: TTS audio + TTS QC ──────────────────────────────────
        from voice_generation import generate_speech as generate_voice
        from vision_analysis  import analyse_tts

        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            voiceover = scene.get("voiceover", "").strip()
            audio_out = str(audio_dir / f"scene_{i:03d}.mp3")
            update("running", int(20 + (i/n)*15), f"Generating audio {i+1} of {n}…")

            if voiceover:
                ok = await asyncio.to_thread(
                    generate_voice, voiceover, audio_out,
                    voice_id=voice_id or None
                )
                if ok:
                    # TTS QC
                    tts_qc = await asyncio.to_thread(analyse_tts, audio_out, voiceover)
                    log.info(f"[Job {job_id}] TTS QC scene {i}: {tts_qc['verdict']}")
                    if tts_qc["verdict"] == "reject":
                        log.warning(f"[Job {job_id}] TTS rejected scene {i}: {tts_qc['issues']}")
                        audio_paths.append(None)
                    else:
                        audio_paths.append(audio_out)
                    qc_results.append({"scene": i, "type": "tts", **tts_qc})
                else:
                    audio_paths.append(None)
                audio_chars.append({"chars": len(voiceover)})
            else:
                audio_paths.append(None)
                audio_chars.append({"chars": 0})

        # ── Stage 3: Video generation + Vision QC ─────────────────────────
        from video_generation  import generate_video_single
        from vision_analysis   import analyse_output

        flagged_scenes  = []
        rejected_scenes = []

        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            clip_out     = str(video_clips_dir / f"scene_{i:03d}.mp4")
            duration     = int(scene.get("duration", 8))
            caption      = scene.get("caption", "")
            space_type   = scene.get("space_type",   "large")
            pov_movement = scene.get("pov_movement", "walk_in_explore")
            update("running", int(35 + (i/n)*40), f"Generating video clip {i+1} of {n}…")

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
                update("running", int(35 + (i/n)*40), f"QC check on clip {i+1} of {n}…")
                original_img = image_paths[i]
                vid_qc = await asyncio.to_thread(analyse_output, clip_out, original_img)
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
                "index":        i,
                "caption":      caption,
                "space_type":   space_type,
                "pov_movement": pov_movement,
                "video":        "ok" if ok else "failed",
                "audio":        "ok" if audio_paths[i] else "skipped",
                "qc_verdict":   video_verdict,
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
            do_upscale=do_upscale, do_vision_qc=enable_vision_qc
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

        JOBS[job_id]["output_path"] = output_path
        update("done", 100, "Video ready for download")
        _save_job(job_id)

    except Exception as e:
        log.error(f"[Assembly {job_id}] Failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Assembly error: {str(e)}"})
        _save_job(job_id)


# ── Rework runner ──────────────────────────────────────────────────────────────

async def run_rework(rework_id: str, parent_job_id: str, cfg: dict):
    def update(status, progress, message):
        JOBS[rework_id].update({"status": status, "progress": progress, "message": message})
        log.info(f"[Rework {rework_id}] {progress}% — {message}")

    try:
        parent     = JOBS[parent_job_id]
        parent_dir = JOBS_DIR / parent_job_id
        rework_dir = JOBS_DIR / rework_id
        rework_dir.mkdir(exist_ok=True)

        for sub in ["enhanced", "audio", "clips"]:
            src = parent_dir / sub
            dst = rework_dir / sub
            if src.exists():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            else:
                (rework_dir / sub).mkdir(exist_ok=True)

        scenes_to_redo = cfg.get("scenes", [])
        redo_video     = cfg.get("redo_video", True)
        redo_audio     = cfg.get("redo_audio", False)
        updated_scenes = cfg.get("updated_scenes", [])
        then_assemble  = cfg.get("then_assemble", False)
        n              = len(scenes_to_redo)

        update("running", 5, f"Reworking {n} scene(s)…")

        from voice_generation import generate_speech as generate_voice
        from video_generation import generate_video_single

        for idx, scene_index in enumerate(scenes_to_redo):
            scene = updated_scenes[scene_index] if scene_index < len(updated_scenes) else {}

            if redo_audio and scene.get("voiceover", "").strip():
                audio_out = str(rework_dir / "audio" / f"scene_{scene_index:03d}.mp3")
                update("running", int(10 + (idx/n)*30), f"Regenerating audio scene {scene_index+1}…")
                await asyncio.to_thread(
                    generate_voice, scene["voiceover"], audio_out,
                    voice_id=os.getenv("DEFAULT_VOICE_ID") or None
                )

            if redo_video:
                enhanced_img = str(rework_dir / "enhanced" / f"scene_{scene_index:03d}_enhanced.jpg")
                if not Path(enhanced_img).exists():
                    enhanced_img = str(parent_dir / "images" / f"scene_{scene_index:03d}.jpg")
                clip_out    = str(rework_dir / "clips" / f"scene_{scene_index:03d}.mp4")
                duration    = int(scene.get("duration", 8))
                caption     = scene.get("caption", "")
                camera_hint = scene.get("camera_hint", "auto")
                update("running", int(40 + (idx/n)*40), f"Regenerating clip scene {scene_index+1}…")
                await asyncio.to_thread(
                    generate_video_single, enhanced_img, duration, clip_out, caption, camera_hint
                )

        update("running", 85, "Reassembling final video…")
        output_path = str(rework_dir / f"{parent['property_name'].replace(' ','_')}_rework.mp4")
        clip_paths  = sorted((rework_dir / "clips").glob("scene_*.mp4"))
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
            raise RuntimeError("Rework assembly failed")

        JOBS[rework_id]["output_path"] = output_path
        update("done", 100, "Rework video ready for download")
        _save_job(rework_id)

    except Exception as e:
        log.error(f"[Rework {rework_id}] Failed: {e}", exc_info=True)
        JOBS[rework_id].update({"status": "failed", "message": f"Error: {str(e)}"})
        _save_job(rework_id)
