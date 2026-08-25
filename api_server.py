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




def _overlay_narration_audio(video_path: str, narration_path: str, transition_style: str = "fade"):
    """
    Overlays the continuous narration track onto the assembled video, with
    blank (black/white) padding at the start and end, and fades between the
    padding and the real footage.

    The padding absorbs any narration OVERFLOW: if the TTS runs longer than
    the video, the extra time is covered by blank padding rather than
    truncating the audio (which silently cut off the final sentences) or
    freezing on a dead final frame. When there is no overflow, the padding
    collapses to a minimal, nearly invisible amount.

    Narration starts just after the opening fade and ends shortly before the
    closing fade, so it sits snugly rather than floating in dead air.

    Padding colour follows the job's transition_style (white if the style
    mentions white, otherwise black).
    """
    from moviepy import VideoFileClip, AudioFileClip, ColorClip, CompositeAudioClip, concatenate_videoclips
    from moviepy.video.fx import FadeIn, FadeOut
    from narration import LEAD_SECS, TRAIL_SECS  # 2026-07-17: single source of
    # truth shared with calculate_scene_durations()'s target_total math --
    # was two independent hardcoded values (1.5s here vs 2.5s there) that
    # could silently drift apart. See narration.py for detail.

    FADE_SECS  = 0.5    # fade into / out of the blank padding

    pad_colour = (255, 255, 255) if "white" in (transition_style or "").lower() else (0, 0, 0)

    video = VideoFileClip(video_path)
    narration = AudioFileClip(narration_path)
    fps = video.fps or 24

    # Time the narration needs in total: lead-in + speech + trail-out
    needed   = LEAD_SECS + narration.duration + TRAIL_SECS
    overflow = max(0.0, needed - video.duration)

    lead_pad  = LEAD_SECS
    trail_pad = TRAIL_SECS + overflow   # trailing padding absorbs the overflow

    lead_clip  = ColorClip(size=video.size, color=pad_colour, duration=lead_pad).with_fps(fps)
    trail_clip = ColorClip(size=video.size, color=pad_colour, duration=trail_pad).with_fps(fps)

    faded = video.with_effects([FadeIn(FADE_SECS), FadeOut(FADE_SECS)])
    padded = concatenate_videoclips([lead_clip, faded, trail_clip])

    narration = narration.with_start(lead_pad)

    log.info(
        f"[Narration] video={video.duration:.1f}s narration={narration.duration:.1f}s "
        f"lead={lead_pad:.2f}s trail={trail_pad:.2f}s overflow_absorbed={overflow:.2f}s "
        f"pad={'white' if pad_colour == (255,255,255) else 'black'} "
        f"final={padded.duration:.1f}s"
    )

    # 2026-07-23: .with_audio() ignores an audio clip's own .start offset
    # unless that clip is wrapped in a CompositeAudioClip -- confirmed via
    # an isolated moviepy test (a shifted clip attached directly played
    # from t=0, completely ignoring with_start()). This was a REAL bug:
    # the lead/trail buffer above was computed correctly and logged
    # correctly, but never actually took effect in the rendered file.
    final = padded.with_audio(CompositeAudioClip([narration]))
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




app = FastAPI(title="Real Estate Video Generator", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Generation pause / kill-switch ────────────────────────────────────────────
# Persisted to disk so an accidental restart can't silently unpause and let
# jobs sneak through before deliberately resumed. Visible in the UI as a
# banner + toggle, not a hidden admin-only mechanism - the point is that
# anyone using the app can SEE generation is paused, not be confused by
# what would otherwise look like a broken submit button.
GENERATION_PAUSE_FILE = BASE_DIR / "generation_pause.json"

def _get_generation_pause_state() -> dict:
    if GENERATION_PAUSE_FILE.exists():
        try:
            return json.loads(GENERATION_PAUSE_FILE.read_text())
        except Exception:
            pass
    return {"paused": False, "message": "", "paused_at": None}

def _set_generation_pause_state(paused: bool, message: str = "") -> dict:
    state = {
        "paused": paused,
        "message": message,
        "paused_at": datetime.utcnow().isoformat() if paused else None,
    }
    GENERATION_PAUSE_FILE.write_text(json.dumps(state, indent=2))
    return state

def _raise_if_generation_paused():
    state = _get_generation_pause_state()
    if state.get("paused"):
        raise HTTPException(
            status_code=423,
            detail=f"Generazione video in pausa: {state.get('message') or 'manutenzione in corso'}. Riprova più tardi.",
        )

@app.get("/admin/generation-status")
async def get_generation_status():
    state = _get_generation_pause_state()
    active_count = sum(1 for j in JOBS.values() if j.get("status") in ("running", "queued"))
    return {**state, "active_jobs": active_count}

@app.post("/admin/pause-generation")
async def pause_generation(message: str = Form("Manutenzione in corso")):
    state = _set_generation_pause_state(True, message)
    log.info(f"[Admin] Generation PAUSED: {message}")
    return state

@app.post("/admin/resume-generation")
async def resume_generation():
    state = _set_generation_pause_state(False)
    log.info("[Admin] Generation RESUMED")
    return state


# ── Rate limiting ──────────────────────────────────────────────────────────────
# ── Cost reporting endpoints ──────────────────────────────────────────────────
import cost_model

def _jobs_with_ids():
    out = []
    for jid, j in JOBS.items():
        d = dict(j); d['job_id'] = jid; out.append(d)
    return out

@app.get('/agencies')
async def list_agencies_ep():
    return {'agencies': cost_model.list_agencies()}

@app.post('/agencies')
async def create_agency_ep(name: str = Form(...), notes: str = Form('')):
    return cost_model.create_agency(name, notes)

@app.post('/agencies/{agency_id}')
async def update_agency_ep(agency_id: str, name: str = Form(None), notes: str = Form(None)):
    if not cost_model.get_agency(agency_id):
        raise HTTPException(status_code=404, detail='Agency not found')
    return cost_model.update_agency(agency_id, name=name, notes=notes)

@app.get('/sales')
async def list_sales_ep():
    return {'sales': cost_model.list_sales(), 'agencies': cost_model.list_agencies()}

@app.post('/sales')
async def create_sale_ep(agency_id: str = Form(...), videos_sold: int = Form(...), price_eur: float = Form(...), description: str = Form('')):
    return cost_model.create_sale(agency_id, videos_sold, price_eur, description)

@app.delete('/sales/{sale_id}')
async def delete_sale_ep(sale_id: str):
    cost_model.delete_sale(sale_id)
    return {'deleted': sale_id}

@app.post('/sales/{sale_id}')
async def update_sale_ep(sale_id: str, videos_sold: int = Form(None), price_eur: float = Form(None), description: str = Form(None)):
    updated = cost_model.update_sale(sale_id, videos_sold=videos_sold, price_eur=price_eur, description=description)
    if updated is None:
        raise HTTPException(status_code=404, detail='Sale not found')
    return updated

@app.get('/reports/enterprise')
async def report_enterprise_ep():
    return cost_model.enterprise_report(_jobs_with_ids())


@app.get('/investment')
async def get_investment_ep():
    return cost_model.get_investment()


@app.post('/investment')
async def add_investment_entry_ep(note: str = Form(...), amount_eur: float = Form(...)):
    return cost_model.add_investment_entry(note, amount_eur)


@app.delete('/investment/{index}')
async def delete_investment_entry_ep(index: int):
    return cost_model.delete_investment_entry(index)

@app.get('/reports/agencies')
async def report_agencies_ep():
    return {'agencies': cost_model.agency_report(_jobs_with_ids())}

@app.get('/reports/jobs')
async def report_jobs_ep():
    jobs = _jobs_with_ids()
    fins = [cost_model.job_financials(j) for j in jobs]
    by_id = {j['job_id']: j for j in jobs}
    for f in fins:
        j = by_id.get(f['job_id'], {})
        f['property_name'] = j.get('property_name','')
        f['status'] = j.get('status','')
        f['created_at'] = j.get('created_at','')
    fins.sort(key=lambda f: f.get('created_at',''), reverse=True)
    return {'jobs': fins}

@app.post('/jobs/{job_id}/commercial')
async def set_job_commercial_ep(job_id: str, classification: str = Form(...), agency_id: str = Form(None), property_name: str = Form(None)):
    """2026-07-22 (backlog item 39): also accepts an optional property_name
    to assign/reassign this job's Property link post-creation -- "assign at
    creation, still editable after" per explicit product decision.
    Idempotent create-or-match, same as at job creation."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail='Job not found')
    if classification not in cost_model.JOB_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail='bad classification')
    JOBS[job_id]['classification'] = classification
    JOBS[job_id]['agency_id'] = agency_id or None
    if property_name:
        prop = cost_model.create_property(property_name, agency_id=agency_id or None)
        JOBS[job_id]['property_id'] = prop['property_id']
    _save_job(job_id)
    return {'job_id': job_id, 'classification': classification, 'agency_id': agency_id, 'property_id': JOBS[job_id].get('property_id')}


@app.get('/properties')
async def list_properties_ep():
    return {'properties': cost_model.list_properties()}


@app.post('/properties')
async def create_property_ep(name: str = Form(...), agency_id: str = Form(None)):
    return cost_model.create_property(name, agency_id)


@app.get('/reports/properties')
async def report_properties_ep():
    return {'properties': cost_model.property_report(_jobs_with_ids())}


@app.post('/agencies/{agency_id}/logo')
async def upload_agency_logo_ep(agency_id: str, logo: UploadFile = File(...)):
    """2026-07-22 (backlog item 7): uploads a logo for client-video
    overlay. Requires an alpha channel (transparent background) --
    rejected with a clear error otherwise, since this composites as a
    subtle bottom-right brand mark, not an opaque box over the video."""
    agency = cost_model.get_agency(agency_id)
    if not agency:
        raise HTTPException(status_code=404, detail='Agency not found')
    content = await logo.read()
    if not _validate_image_bytes(content):
        raise HTTPException(status_code=400, detail='Invalid image file')
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(content))
    if img.mode not in ('RGBA', 'LA') and 'transparency' not in img.info:
        raise HTTPException(status_code=400, detail='Logo must have an alpha channel (transparent background) -- upload a PNG with transparency')
    logos_dir = BASE_DIR / 'clients' / agency_id
    logos_dir.mkdir(parents=True, exist_ok=True)
    logo_path = logos_dir / 'logo.png'
    img.convert('RGBA').save(logo_path, format='PNG')
    cost_model.set_agency_logo(agency_id, str(logo_path))
    return {'agency_id': agency_id, 'logo_path': str(logo_path)}


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


def _get_image_dimensions(content: bytes):
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(content))
    return img.size


def _decide_job_format_from_bytes(contents: list) -> str:
    """
    Majority vote across a job's photos: 'landscape' or 'portrait'
    (2026-07-17, per explicit product decision). Exactly two canonical
    output formats -- not one-per-photo-ratio -- so a mixed-orientation
    property still gets one consistent video canvas. Ties, or any photo
    that fails to read, default to landscape.
    """
    landscape_count = 0
    portrait_count = 0
    for c in contents:
        try:
            w, h = _get_image_dimensions(c)
            if w >= h:
                landscape_count += 1
            else:
                portrait_count += 1
        except Exception:
            landscape_count += 1
    return "portrait" if portrait_count > landscape_count else "landscape"


def _normalize_photo_to_format(image_bytes: bytes, target_format: str) -> bytes:
    """
    Crops a photo to match the job's chosen canonical output format --
    "landscape" (16:9) or "portrait" (9:16) -- so every photo in a job
    ends up exactly the same shape before generation, and video_assembly.py
    can use one fixed canvas per job matching that format (2026-07-17,
    per explicit product decision after a real client portrait-photo
    distortion issue -- forcing every clip through a hardcoded 16:9
    canvas was stretching portrait footage).

    Crop direction depends on which way the source differs from target:
      - Source is taller/narrower than target (needs height cropped,
        e.g. a portrait photo going into a landscape job): TOP-BIASED
        crop, not centered -- confirmed via a real side-by-side test
        against an actual client photo that starting the crop window
        ~15% down from the top keeps more of the informative ceiling/
        window content real estate portrait shots are usually framed
        for, cropping more from the floor instead.
      - Source is wider than target (needs width cropped, e.g. a
        landscape photo going into a portrait job): plain CENTER crop --
        no equivalent left/right framing bias for typical room photos.
    """
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    target_ratio = (16 / 9) if target_format == "landscape" else (9 / 16)
    current_ratio = w / h

    if abs(current_ratio - target_ratio) / target_ratio < 0.02:
        return image_bytes  # already an effective match, don't bother cropping

    if current_ratio < target_ratio:
        new_h = min(int(w / target_ratio), h)
        top = int((h - new_h) * 0.26)  # 2026-07-17: proportional to actual crop amount, not a fixed % of original height
        top = max(0, min(top, h - new_h))
        cropped = img.crop((0, top, w, top + new_h))
    else:
        new_w = min(int(h * target_ratio), w)
        left = (w - new_w) // 2
        cropped = img.crop((left, 0, left + new_w, h))

    buf = io.BytesIO()
    cropped.save(buf, format='JPEG', quality=95)
    return buf.getvalue()


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

    # Detect real content type by extension — this endpoint originally only
    # served test video clips (hardcoded video/mp4), which silently broke
    # when used for test images (the browser gets real JPEG bytes but a
    # video/mp4 header, so it renders a blank video player instead).
    ext = Path(filename).suffix.lower()
    media_types = {
        ".mp4": "video/mp4", ".mov": "video/quicktime",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".mp3": "audio/mpeg", ".wav": "audio/wav",
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(str(test_path), media_type=media_type)




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
        # Prefer job_meta.json's own mtime (rewritten by _save_job() on
        # every real state change). If no job_meta.json exists at all —
        # an orphaned directory from a job creation that crashed before
        # its first save — fall back to the directory's own mtime. Either
        # way, no metadata + old age means it can never load into JOBS or
        # appear in the UI regardless, so there's no reason to keep it.
        try:
            if meta.exists():
                last_activity = datetime.utcfromtimestamp(meta.stat().st_mtime)
            else:
                last_activity = datetime.utcfromtimestamp(job_dir.stat().st_mtime)
            if last_activity < cutoff:
                size_mb = sum(
                    f.stat().st_size for f in job_dir.rglob("*") if f.is_file()
                ) / (1024**2)
                shutil.rmtree(str(job_dir), ignore_errors=True)
                job_id = job_dir.name
                JOBS.pop(job_id, None)
                cleaned  += 1
                freed_mb += size_mb
            elif meta.exists():
                # 2026-07-21 diagnostic (backlog item 32): a real incident
                # (July 16 2026) found two jobs whose mtime-based
                # last_activity looked suspiciously recent relative to
                # their real age, delaying (not permanently blocking)
                # cleanup. Root cause was never confirmed -- the original
                # hypothesis (that _load_jobs_from_disk() resaves every
                # job on startup) was checked directly and is FALSE, that
                # function is read-only. Flags any job whose own
                # created_at is meaningfully older than its file's mtime,
                # so a recurrence leaves real evidence instead of having
                # to be reconstructed after the fact.
                try:
                    with open(meta) as f:
                        job_data = json.load(f)
                    created_str = job_data.get("created_at", "")
                    if created_str:
                        created_at = datetime.fromisoformat(created_str)
                        gap_days = (last_activity - created_at).total_seconds() / 86400
                        age_days = (datetime.utcnow() - last_activity).total_seconds() / 86400
                        if gap_days > 3 and age_days < 7:
                            log.warning(
                                f"[Cleanup] Job {job_dir.name}: created_at is {gap_days:.1f} days "
                                f"before its file mtime, and mtime is only {age_days:.1f} days old -- "
                                f"possible stale-mtime pattern (backlog item 32), watching for recurrence."
                            )
                except Exception:
                    pass
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
    output_format: str = Form(None),          # 2026-07-17: "landscape"/"portrait" override, or None to auto-detect
    agency_id: str = Form(None),              # 2026-07-22: client this job belongs to (backlog item 39), optional
):
    # Rate limit check
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Maximum 5 jobs per hour. Please wait before submitting again."
        )

    _raise_if_generation_paused()

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


    # ── Pass 1: validate + read every photo, before deciding anything ────
    validated = []
    for i, upload in enumerate(images):
        content = await upload.read()

        if len(content) > 20 * 1024 * 1024:
            shutil.rmtree(str(job_dir), ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Image {i+1} exceeds 20MB limit")

        if not _validate_image_bytes(content):
            shutil.rmtree(str(job_dir), ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Image {i+1} is not a valid image file")

        ext = Path(upload.filename).suffix.lower() or ".jpg"
        if upload.content_type == "image/jpeg": ext = ".jpg"
        elif upload.content_type == "image/png":  ext = ".png"
        elif upload.content_type == "image/webp": ext = ".webp"

        validated.append((content, ext))

    # ── Decide the job's canonical output format (2026-07-17): exactly
    # two formats, landscape or portrait -- majority vote across the real
    # photos, unless the caller explicitly overrode it. ──
    if output_format in ("landscape", "portrait"):
        job_format = output_format
    else:
        job_format = _decide_job_format_from_bytes([c for c, _ in validated])

    # ── Pass 2: normalize every photo to match job_format, then save ─────
    saved_images = []
    for i, (content, ext) in enumerate(validated):
        content = _normalize_photo_to_format(content, job_format)
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


    # 2026-07-22 (backlog item 39): link this job to a Property record --
    # shared entity with cost reporting, single data model per the
    # architecture-discipline principle (no separate "library-only"
    # property concept). Reuses the SAME property_name value already
    # captured above for display purposes, rather than adding a second,
    # redundant form field. create_property() is idempotent per
    # (name, agency_id), so repeated jobs for the same property+client
    # correctly link to one shared record instead of duplicating it.
    _prop = cost_model.create_property(property_name, agency_id=agency_id)

    JOBS[job_id] = {
        "status":           "draft" if not start_generation else "queued",
        "progress":         0,
        "message":          "Scene salvate — pronto per narrazione" if not start_generation else "Job queued",
        "scenes":           [],
        "scenes_config":    scenes_config,  # needed by narration endpoints even in draft mode
        "output_path":      None,
        "output_format":    job_format,
        "created_at":       datetime.utcnow().isoformat(),
        "property_name":    property_name,
        "agency_id":        agency_id,
        "property_id":      _prop["property_id"],
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
            output_format=job_format,  # 2026-07-27 URGENT FIX: run_pipeline() now needs this explicitly
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
    _raise_if_generation_paused()
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
        output_format=job.get("output_format", "landscape"),  # 2026-07-27 URGENT FIX: run_pipeline() now needs this explicitly
    )


    return {"job_id": job_id, "status": "queued"}




# ══════════════════════════════════════════════════════════════════════════════
# NARRATION SYSTEM — single continuous voiceover, decoupled from video timing
# ══════════════════════════════════════════════════════════════════════════════
# Step A ("Genera voiceover") — cheap, TTS-only. Measures actual duration,
# calculates required scene durations BEFORE any video generation.
# Step B ("Genera video") — only runs once duration is confirmed correct.
# This prevents ever paying for a wrongly-timed video clip.


@app.post("/jobs/{job_id}/draft/resync")
async def resync_draft(
    job_id: str,
    images: list[UploadFile] = File(...),
    config: str = Form(...),
):
    """
    Re-syncs an existing DRAFT job's scenes_config and images to match
    whatever is currently in the browser -- needed because generateNarration()
    only creates the draft job on the FIRST click; if the user adds/removes
    scenes afterward and clicks "Genera voiceover" again, without this the
    server-side scenes_config stays frozen at the original count while the
    UI's live cost panel reflects the new count (2026-07-13 fix: this was the
    exact cause of the cost panel showing 10 scenes while the narration
    duration distribution still showed 5).

    Only allowed while status == "draft" -- a job that has moved past draft
    (generation started or completed) must never have its scenes_config
    silently overwritten, since scenes/clips would then no longer line up
    with scenes_config.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    if job.get("status") != "draft":
        raise HTTPException(status_code=400, detail="Job is no longer in draft status -- cannot resync scenes")

    if len(images) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 images per job")

    try:
        scenes_config = json.loads(config)
        if not isinstance(scenes_config, list):
            raise ValueError("config must be a JSON array")
        scenes_config = _ensure_scene_ids(scenes_config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config JSON: {e}")

    if len(images) != len(scenes_config):
        raise HTTPException(
            status_code=400,
            detail=f"Images ({len(images)}) must match scene configs ({len(scenes_config)})"
        )

    job_dir = JOBS_DIR / job_id
    img_dir = job_dir / "images"
    # Safe to wipe and rewrite -- draft jobs have no generated clips/audio
    # yet that reference these image paths.
    shutil.rmtree(str(img_dir), ignore_errors=True)
    img_dir.mkdir(parents=True)

    # ── Pass 1: validate + read every photo ──────────────────────────────
    validated = []
    for i, upload in enumerate(images):
        content = await upload.read()

        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"Image {i+1} exceeds 20MB limit")

        if not _validate_image_bytes(content):
            raise HTTPException(status_code=400, detail=f"Image {i+1} is not a valid image file")

        ext = Path(upload.filename).suffix.lower() or ".jpg"
        if upload.content_type == "image/jpeg": ext = ".jpg"
        elif upload.content_type == "image/png":  ext = ".png"
        elif upload.content_type == "image/webp": ext = ".webp"

        validated.append((content, ext))

    # 2026-07-17: re-decide the job's format from the current full photo
    # set -- this is still pre-generation, so re-voting is correct here
    # (unlike add_scene/redo_scenes_batch, which inherit an already-locked
    # format from a job that's already generated).
    job_format = _decide_job_format_from_bytes([c for c, _ in validated])
    job["output_format"] = job_format

    # ── Pass 2: normalize + save ──────────────────────────────────────────
    for i, (content, ext) in enumerate(validated):
        content = _normalize_photo_to_format(content, job_format)
        dest = img_dir / f"scene_{i:03d}{ext}"
        with open(dest, "wb") as f:
            f.write(content)

    from cost_tracker import estimate_job_cost, format_cost_display
    rolling_jobs = _get_rolling_monthly_job_count()
    cost_estimate = estimate_job_cost(
        scenes_config,
        do_upscale=job.get("upscale_images", True),
        do_video_upscale=job.get("do_video_upscale", True),
        do_vision_qc=job.get("enable_vision_qc", True),
        model_tier=job.get("model_tier", "standard"),
        actual_monthly_jobs=rolling_jobs,
    )

    job["scenes_config"] = scenes_config
    job["total_scenes"]  = len(images)
    job["cost_estimate"] = format_cost_display(cost_estimate)
    job["message"] = "Scene aggiornate — pronto per narrazione"
    _save_job(job_id)

    return {"job_id": job_id, "scenes_config": scenes_config, "total_scenes": len(images)}




@app.post("/jobs/{job_id}/narration")
async def generate_narration(
    job_id: str,
    narration_text: str = Form(...),
    voice_id: str = Form(""),
    extra_secs_needed: float = Form(0),
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


        from narration import generate_narration_audio, calculate_scene_durations, suggest_pause_padding, SENTENCE_PAUSE_MS

        # Pause-padding persistence (2026-07-16 fix): "Aggiungi pause" used to
        # just regenerate identical audio with the default pause, so the
        # "too short" warning could never clear -- nothing connected the
        # frontend's computed gap to the actual TTS call. Now a boosted
        # pause value sticks on the job until the narration TEXT changes.
        if job.get("narration_text") != narration_text:
            job.pop("sentence_pause_ms", None)

        base_pause_ms = job.get("sentence_pause_ms", SENTENCE_PAUSE_MS)
        if extra_secs_needed and extra_secs_needed > 0:
            sentence_pause_ms = suggest_pause_padding(
                narration_text, extra_secs_needed, sentence_pause_ms=base_pause_ms
            )
        else:
            sentence_pause_ms = base_pause_ms

        result = await asyncio.to_thread(
            generate_narration_audio, narration_text, narration_path,
            voice_id or None, sentence_pause_ms
        )


        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=result.get("error", "Narration generation failed"))


        scenes_config = job.get("scenes_config", [])
        n_scenes = len(scenes_config)
        current_durations = [int(s.get("duration", 6)) for s in scenes_config] or [6] * n_scenes

        # BUG FIXED: calculate_scene_durations() previously defaulted to a
        # tier-blind union [4,5,6,8,9] of Veo+Luma valid values, so it could
        # (and did) propose "4s" for a Luma job - invalid, Luma only accepts
        # 5s/9s. Now mirrors the same tier logic already used for the UI
        # sliders (getDurationRangeForTier in ui.html).
        _tier = job.get("model_tier", "standard")
        if _tier == "luma":
            _valid_durations = [5, 9]
        elif _tier == "eco":
            _valid_durations = [6, 8, 10, 12, 14, 16, 18, 20]
        else:  # premium / premium_veo / standard (all Veo-backed)
            _valid_durations = [4, 6, 8]

        distribution = calculate_scene_durations(
            narration_duration_secs=result["duration_secs"],
            scene_count=n_scenes,
            current_durations=current_durations,
            valid_durations=_valid_durations,
        )


        job["narration_text"] = narration_text
        job["narration_path"] = narration_path
        job["narration_duration_secs"] = result["duration_secs"]
        job["narration_sentence_timings"] = result.get("sentence_timings", [])
        job["sentence_pause_ms"] = sentence_pause_ms

        # 2026-07-24: real cost-tracking gap -- this endpoint makes a real,
        # billable ElevenLabs TTS call every time it runs, but never
        # recorded that cost anywhere. A rework that regenerated narration
        # (a real, ongoing cost every time the user tweaks the text) showed
        # no TTS cost at all in the job's cost_actual. Reuses the SAME
        # rework-cost pattern (calculate_rework_cost + format_cost_display)
        # already used for scene reworks and the audio-only-rework feature,
        # rather than a separate, parallel cost calculation.
        from cost_tracker import calculate_rework_cost, format_cost_display
        narration_cost = calculate_rework_cost(
            scenes_redone=[],
            models_used=[],
            redo_video=False,
            redo_audio=True,
            audio_chars=len(narration_text),
            model_tier=job.get("model_tier", "premium"),
        )
        job.setdefault("reworks", []).append(narration_cost)
        original_raw = job.get("cost_actual_raw")
        if original_raw:
            job["cost_actual"] = format_cost_display(original_raw, previous_reworks=job["reworks"])
        else:
            legacy_total = (job.get("cost_actual") or {}).get("grand_total_eur", 0)
            pseudo_raw = {"type": "actual", "total_eur": legacy_total, "model_tier": job.get("model_tier", "premium")}
            job["cost_actual"] = format_cost_display(pseudo_raw, previous_reworks=job["reworks"])

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




# ── Automated URL-to-video workflow (Phase 1: human-in-the-loop) ──────────────
# Runs the full scrape -> narration -> scene-count -> photo-selection chain
# (listing_scraper.py) and creates a job in "draft" status with everything
# pre-populated — narration text, scenes_config, downloaded+dewatermarked
# images already in place in the job's own directory. Deliberately does NOT
# trigger real video generation automatically — the agent reviews in the UI
# and presses "Generate Video" manually via the EXISTING /start-generation
# endpoint, same as any other draft job. Phase 2 (fully automatic, no
# manual review step) is a later addition, not built yet.

@app.post("/jobs/from-url")
async def create_job_from_url(
    request: Request,
    property_name: str = Form(""),
    voice_id: str = Form(""),
    model_tier: str = Form("luma"),
    url: str = Form(...),
    agency_id: str = Form(None),   # 2026-07-22: client this job belongs to (backlog item 39), optional
    premium: bool = Form(False),   # 2026-07-24: premium ~1-min template (backlog item 35), URL-scrape only, manual per-job toggle
):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429,
                             detail="Too many requests. Maximum 5 jobs per hour. Please wait before submitting again.")

    _raise_if_generation_paused()

    import listing_scraper as scraper
    scraper.reset_claude_usage()   # reset token counter for THIS job

    # CRITICAL: every one of these does real, slow, blocking I/O (web
    # fetches, Claude API calls with images, TTS generation, fal.ai object
    # removal) — wrapped in asyncio.to_thread so this endpoint doesn't
    # freeze the ENTIRE server's event loop for the 30-90+ seconds this
    # takes, the way it did before this fix (confirmed: caused a false
    # "server not responding" alert, since even the health check couldn't
    # get through while this ran synchronously).
    extraction = await asyncio.to_thread(scraper.extract_listing, url)
    if not extraction["ok"]:
        raise HTTPException(status_code=400, detail=f"Could not read listing: {extraction['error']}")
    extraction["photos"] = await asyncio.to_thread(scraper.resolve_uncategorized_photos, extraction["photos"])

    narration = await asyncio.to_thread(
        scraper.generate_narration_and_derive_scenes,
        extraction["description"], extraction["address"], extraction["price"], voice_id or None,
        premium,
    )
    if not narration["ok"]:
        raise HTTPException(status_code=500, detail=f"Narration generation failed: {narration['error']}")

    # 2026-07-24 (backlog item 35): premium uses a dedicated selection
    # function (wider scene-count target, expanded taxonomy including
    # laundry/office/garage, outdoor split across an early + closing
    # slot) -- kept separate rather than branching deeply inside the
    # existing one, since the sequencing logic is genuinely different,
    # not just a wider number range.
    if premium:
        selection = await asyncio.to_thread(
            scraper.select_photos_for_scene_count_premium, extraction["photos"], narration["scene_count"]
        )
    else:
        selection = await asyncio.to_thread(
            scraper.select_photos_for_scene_count, extraction["photos"], narration["scene_count"]
        )

    job_id = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    img_dir = job_dir / "images"
    img_dir.mkdir(parents=True)

    selection = await asyncio.to_thread(scraper.download_selected_photos, selection, img_dir)
    # BUG FIXED: this check previously only looked at selection["gaps"],
    # computed BEFORE the download attempt. Confirmed real case: a
    # listing's entire photo CDN batch returned 404 during download -
    # the pre-download gaps check passed silently and the job was
    # created reporting "success" with 0 actual scenes.
    total_downloaded = sum(len(photos) for photos in selection["selected"].values())
    if selection["gaps"] or total_downloaded == 0:
        shutil.rmtree(str(job_dir), ignore_errors=True)
        if selection["gaps"]:
            gap_desc = "; ".join(selection["gaps"])
        else:
            n_failed = len(selection.get("download_failures", []))
            gap_desc = f"All {n_failed} selected photo(s) failed to download - source images may be temporarily unavailable"
        # 2026-07-24: explicit product decision -- if premium's full
        # 3-tier fallback still can't fill the sequence, suggest the
        # concrete alternatives (standard format, or manual upload)
        # rather than a bare failure message.
        suggestion = (" This listing may not have enough photos for the premium template -- "
                      "try the standard ~30s format, or upload manually."
                      if premium else " Try again in a moment, or upload manually.")
        raise HTTPException(status_code=422,
                             detail=f"Not enough usable photos for this listing: {gap_desc}.{suggestion}")

    # 2026-07-24: premium's selected dict has outdoor_early/outdoor_late
    # pseudo-category keys (see select_photos_for_scene_count_premium),
    # not real categories -- map back to "outdoor" before requesting
    # captions, which are keyed by real category name.
    if premium:
        selected_categories = list({
            ("outdoor" if cat in ("outdoor_early", "outdoor_late") else cat)
            for cat, photos in selection["selected"].items() if photos
        })
    else:
        selected_categories = [cat for cat, photos in selection["selected"].items() if photos]
    captions = await asyncio.to_thread(
        scraper.generate_captions_for_categories, extraction["description"], selected_categories
    )

    # 2026-07-21 unification fix (architecture assessment item 6): this
    # used to bake lead/trail silence directly into the audio via
    # scraper.build_final_audio_track(), and assembly's
    # _overlay_narration_audio() then added its OWN separate lead/trail
    # blank-video padding on top -- confirmed real double-padding on
    # every scraped job. Now stores the bare narration audio, exactly
    # like manual jobs, so the one shared assembly-time function applies
    # padding once, uniformly, for both workflows.
    job_narration_path = str(job_dir / "narration.mp3")
    shutil.copy2(narration["audio_path"], job_narration_path)

    if premium:
        scenes_config = scraper.build_premium_video_scenes_config(selection, captions,
                                                                    clip_duration_secs=scraper.SCENE_CLIP_SECS)
    else:
        scenes_config = scraper.build_standard_video_scenes_config(selection, captions,
                                                                     clip_duration_secs=scraper.SCENE_CLIP_SECS)
    scenes_config = _ensure_scene_ids(scenes_config)

    # Rename downloaded images to the scene_NNN.ext convention — this is
    # what /jobs/{id}/image/{i} (used by the UI's editJob() to populate the
    # editable form) actually expects, and what /start-generation's fallback
    # lookup also supports. NOT scene_id-based naming, which editJob's
    # image-loading loop has no way to resolve (it fetches by index, not ID).
    scene_image_paths = []
    for i, scene in enumerate(scenes_config):
        src = scene.pop("local_image_path", None)
        dest_path = None
        if src and os.path.exists(src):
            src_path = Path(src)
            dest_path = img_dir / f"scene_{i:03d}{src_path.suffix}"
            shutil.move(src, str(dest_path))
        scene_image_paths.append(dest_path)

    # 2026-07-21 fix: apply the same landscape/portrait format detection
    # and normalization that manually-uploaded jobs get via create_job() --
    # this was a known architecture gap (assessment item 3): scraped jobs
    # never went through _normalize_photo_to_format() at all, meaning a
    # portrait source photo here would still hit the exact distortion
    # issue manual uploads had before that fix was built.
    valid_img_paths = [p for p in scene_image_paths if p and p.exists()]
    if valid_img_paths:
        job_format = _decide_job_format_from_bytes([p.read_bytes() for p in valid_img_paths])
        for p in valid_img_paths:
            p.write_bytes(_normalize_photo_to_format(p.read_bytes(), job_format))
    else:
        job_format = "landscape"

    # Real per-photo vision analysis — BUG FIXED July 10 2026: scenes were
    # previously getting space_type/pov_movement from a static category-name
    # lookup table (e.g. all "bedrooms" always got the same movement),
    # never actually looking at the photo itself. Manually-uploaded photos
    # already get real analysis via analyse_input() (the /analyse-image
    # endpoint) — this brings scraped photos to the same standard instead
    # of a simplified stand-in. Falls back to the static table only if
    # analysis fails for a specific photo.
    from vision_analysis import analyse_input

    # BUG FIXED July 10 2026: confirmed via the real /analyse-image response
    # shape (used by manual uploads) that the actual keys are
    # "v7_space_type" and "suggested_movement" — NOT "space_type"/
    # "pov_movement" as originally written here. That meant real per-photo
    # movement analysis NEVER actually fired even once; the static
    # category table was silently doing 100% of the work the whole time.
    # Also normalizes space_type's raw technical values (e.g.
    # "large_interior", "ground_exterior") to the plain vocabulary
    # SPACE_OPTS actually uses in the UI dropdown — mirrors the exact
    # equivalence already used by ui.html's own spaceLabel() function,
    # rather than inventing a new mapping.
    _SPACE_TYPE_NORMALIZE = {
        "large_interior": "large", "medium_interior": "medium", "small_interior": "small",
        "ground_exterior": "outdoor",
    }

    for i, scene in enumerate(scenes_config):
        dest_path = scene_image_paths[i]
        if not dest_path or not dest_path.exists():
            continue
        try:
            analysis = await asyncio.to_thread(analyse_input, str(dest_path))
            raw_space = analysis.get("v7_space_type") or analysis.get("space_type")
            if raw_space:
                scene["space_type"] = _SPACE_TYPE_NORMALIZE.get(raw_space, raw_space)
            raw_movement = analysis.get("suggested_movement") or analysis.get("pov_movement")
            if raw_movement:
                scene["pov_movement"] = raw_movement
        except Exception as e:
            log.warning(f"[URL workflow] Vision analysis failed for scene {i}, "
                        f"keeping category-based default: {e}")

    claude_usage = scraper.get_claude_cost()
    log.info(f"[URL workflow] Claude API: {claude_usage['calls']} calls, "
             f"{claude_usage['input_tokens']} in / {claude_usage['output_tokens']} out tokens, "
             f"EUR {claude_usage['cost_eur']}")

    property_name_final = property_name.strip() or extraction.get("address") or "Property"

    # 2026-07-22 (backlog item 39): same Property-linking treatment as
    # create_job() -- single shared data model, reusing property_name_final
    # (already computed above) rather than a separate field.
    _prop = cost_model.create_property(property_name_final, agency_id=agency_id)

    # Cost estimate — was missing entirely before this fix, which is why
    # the UI's cost box disappeared for jobs created this way. Matches the
    # same computation every manually-created job already gets.
    from cost_tracker import estimate_job_cost, format_cost_display
    rolling_jobs = _get_rolling_monthly_job_count()
    cost_estimate = estimate_job_cost(
        scenes_config, do_upscale=True, do_video_upscale=True, do_vision_qc=True,
        model_tier=model_tier, actual_monthly_jobs=rolling_jobs,
        claude_cost_eur=claude_usage.get("cost_eur", 0.0),
    )

    JOBS[job_id] = {
        "status": "draft",
        "progress": 0,
        "output_format": job_format,
        "message": "Creato automaticamente da URL — rivedi e premi Genera Video",
        "scenes": [],
        "scenes_config": scenes_config,
        "output_path": None,
        "created_at": datetime.utcnow().isoformat(),
        "property_name": property_name_final,
        "agency_id": agency_id,
        "is_premium": premium,   # 2026-07-24 (backlog item 35): premium ~1-min template flag, for classification/reporting
        "property_id": _prop["property_id"],
        "total_scenes": len(scenes_config),
        "transition_style": "fade",
        "enable_vision_qc": True,
        "do_video_upscale": True,
        "model_tier": model_tier,
        "lighting": "bright_natural",
        "intensity": "natural_pace",
        "voice_id": voice_id,
        "enhance_images": True,
        "upscale_images": True,
        "cost_estimate": format_cost_display(cost_estimate),
        "cost_actual": None,
        "claude_usage": claude_usage,
        "reworks": [],
        "qc_results": [],
        "awaiting_scenes": [],
        "narration_text": narration["narration_text"],
        "narration_path": job_narration_path,
        "narration_duration_secs": narration["video_duration_secs"],
        "source_url": url,
        "source_price": extraction.get("price"),
        "source_address": extraction.get("address"),
    }
    _save_job(job_id)

    return {
        "job_id": job_id,
        "status": "draft",
        "property_name": property_name_final,
        "narration_text": narration["narration_text"],
        "scene_count": narration["scene_count"],
        "video_duration_secs": narration["video_duration_secs"],
        "scenes_config": scenes_config,
        "cost_estimate": format_cost_display(cost_estimate),
        "source_price": extraction.get("price"),
        "source_address": extraction.get("address"),
    }


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
            "agency_id":    job.get("agency_id"),
            "property_id":  job.get("property_id"),
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
        # 2026-07-21 migration: this was the ONE remaining live call into
        # the legacy run_rework() (sibling-directory model) -- and it's hit
        # by ordinary, common usage (any first-time generation where QC
        # flags a scene), meaning every such job was silently missing this
        # session's cost tracking, locking, and single-directory-model
        # guarantees, without anyone realizing it. Now uses the same batch
        # redo mechanism as the manual "Rifai questa scena" button.
        scenes_config_now = job.get("scenes_config", [])
        redo_scene_ids = []
        for idx in redo_scenes:
            if 0 <= idx < len(scenes_config_now):
                sid = scenes_config_now[idx].get("scene_id")
                if sid:
                    redo_scene_ids.append(sid)

        if not _acquire_job_lock(job_id, f"QC redo {len(redo_scene_ids)} scene(s)"):
            lock = _job_lock_status(job_id)
            raise HTTPException(
                status_code=409,
                detail=f"Job is currently being modified ({lock.get('operation')}) — please wait and try again."
            )

        JOBS[job_id]["status"]  = "running"
        JOBS[job_id]["message"] = f"Rework: rigenerazione di {len(redo_scene_ids)} scena/e in corso…"
        background_tasks.add_task(run_redo_scenes_batch, job_id=job_id, scene_ids=redo_scene_ids)
    else:
        # All approved — proceed to assembly
        # 2026-07-21 consolidation: was run_assembly(), now the single
        # unified assembly implementation (see run_pipeline for detail).
        JOBS[job_id]["status"]  = "running"
        JOBS[job_id]["message"] = "Assembling final video…"
        background_tasks.add_task(run_reassemble_only, job_id=job_id)


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




# 2026-07-21: the dedicated /jobs/{id}/scenes/{scene_id}/redo endpoint was
# removed here -- confirmed via direct grep zero remaining callers in
# ui.html. Its underlying function run_redo_scene() stays (add_scene()
# below still genuinely depends on it internally).
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

    # 2026-07-17: normalize to the job's already-established output_format
    # -- inherit, don't re-vote, since this job's canvas is already locked in
    content = _normalize_photo_to_format(content, job.get("output_format", "landscape"))

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
            update("running", 15, f"Rework: rigenero voiceover…")
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
        # BUG FIXED: jobs created before the scene_id naming convention store
        # their images as legacy scene_NNN.ext (index-based) instead of
        # {scene_id}.ext. Confirmed real: redo always failed with "No source
        # image found" on any older job. Fall back to the legacy name and
        # self-heal by copying it to the new name, same pattern already used
        # correctly in run_reassemble_only for clips/audio.
        if not source_img:
            for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                legacy_candidate = img_dir / f"scene_{scene_idx:03d}{ext}"
                if legacy_candidate.exists():
                    new_name = img_dir / f"{scene_id}{ext}"
                    shutil.copy2(str(legacy_candidate), str(new_name))
                    source_img = new_name
                    log.info(f"[Job {job_id}] Migrated legacy image scene_{scene_idx:03d}{ext} → {scene_id}{ext}")
                    break
        if not source_img:
            raise ValueError(f"No source image found for scene {scene_id}")


        enhanced_img = enhanced_dir / f"{scene_id}_enhanced.jpg"
        if not enhanced_img.exists():
            from image_enhance import enhance_image
            update("running", 25, "Rework: miglioro immagine…")
            await asyncio.to_thread(enhance_image, str(source_img), str(enhanced_img), True, True)
        img_for_generation = str(enhanced_img) if enhanced_img.exists() else str(source_img)


        # ── Step 3: video generation ───────────────────────────────────────
        clips_dir = job_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        clip_out = str(clips_dir / f"{scene_id}.mp4")


        update("running", 40, f"Rework: rigenero clip ({actual_duration}s)…")
        from video_generation import generate_video_single
        ok_video = await asyncio.to_thread(
            generate_video_single,
            img_for_generation, actual_duration, clip_out,
            space_type=scene.get("space_type", "large"),
            pov_movement=scene.get("pov_movement", "walk_in_explore"),
            lighting=lighting,
            intensity=intensity,
            model_tier=model_tier,
            output_format=job.get("output_format", "landscape"),  # 2026-07-27, backlog item 37
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

        # ── Rework cost tracking ─────────────────────────────────────────
        # Prices this redo the same way a fresh clip in this job's tier
        # would be priced, then folds it into a running total alongside
        # the original job cost (cost_tracker.calculate_rework_cost).
        from cost_tracker import calculate_rework_cost, format_cost_display
        pricing_scene = dict(scene)
        pricing_scene["duration"] = actual_duration
        rework_cost = calculate_rework_cost(
            scenes_redone=[pricing_scene],
            models_used=[model_tier],
            redo_video=True,
            redo_audio=bool(voiceover),
            audio_chars=len(voiceover) if voiceover else 0,
            model_tier=model_tier,
        )
        job.setdefault("reworks", []).append(rework_cost)
        original_raw = job.get("cost_actual_raw")
        if original_raw:
            job["cost_actual"] = format_cost_display(original_raw, previous_reworks=job["reworks"])
        else:
            # Job predates cost_actual_raw being stored -- fall back to its
            # existing formatted total as a single baseline so the rework
            # still shows a running total instead of silently vanishing.
            legacy_total = (job.get("cost_actual") or {}).get("grand_total_eur", 0)
            pseudo_raw = {"type": "actual", "total_eur": legacy_total, "model_tier": model_tier}
            job["cost_actual"] = format_cost_display(pseudo_raw, previous_reworks=job["reworks"])
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
        # 2026-07-22 (backlog item 7): resolve this job's client logo, if
        # any, from the shared agency record -- reads job["agency_id"]
        # (already set at creation, see backlog item 39), no separate
        # per-job logo field needed.
        _logo_path = None
        _job_agency_id = job.get("agency_id")
        if _job_agency_id:
            _agency = cost_model.get_agency(_job_agency_id)
            if _agency and _agency.get("logo_path") and os.path.exists(_agency["logo_path"]):
                _logo_path = _agency["logo_path"]
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
            output_format=job.get("output_format", "landscape"),
            logo_path=_logo_path,
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
            await asyncio.to_thread(_overlay_narration_audio, output_path, narration_path, job.get("transition_style", "fade"))
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
# Batch redo (NEW SOLID JOB MODEL) — multiple scenes, one locked operation,
# one reassembly. Replaces the legacy /rework endpoint below for the main
# "Genera video" button's rework path (2026-07-16 migration). Duplicates
# run_redo_scene's per-scene steps rather than sharing code with it, so the
# already-tested single-scene redo path can't regress from this change.
# ══════════════════════════════════════════════════════════════════════════════


@app.post("/jobs/{job_id}/scenes/redo-audio-only")
async def redo_audio_only(
    job_id: str,
    background_tasks: BackgroundTasks,
    scene_ids: str = Form(...),
):
    """2026-07-23: regenerates ONLY the TTS audio for the given scenes,
    reusing their existing video clips untouched -- no Luma/Veo cost at
    all, just the cheap ElevenLabs charge. Built for fixing or testing
    audio timing (e.g. the lead/trail buffer) without paying to
    regenerate video that was already fine."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]

    if job.get("status") not in ("done", "failed", "awaiting_approval"):
        raise HTTPException(
            status_code=400,
            detail=f"Job must be completed before an audio-only rework (current status: {job.get('status')})"
        )

    try:
        ids = json.loads(scene_ids)
        if not isinstance(ids, list):
            raise ValueError("scene_ids must be a JSON array")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    if not _acquire_job_lock(job_id, f"audio-only redo {len(ids)} scene(s)"):
        lock = _job_lock_status(job_id)
        raise HTTPException(
            status_code=409,
            detail=f"Job is currently being modified ({lock.get('operation')}) -- please wait and try again."
        )

    job["status"]  = "running"
    job["message"] = f"Rework audio: rigenerazione di {len(ids)} scena/e in corso..."
    _save_job(job_id)

    background_tasks.add_task(run_redo_audio_only, job_id=job_id, scene_ids=ids)
    return {"job_id": job_id, "status": "running", "scenes_to_redo": ids}


@app.post("/jobs/{job_id}/scenes/redo-batch")
async def redo_scenes_batch(
    job_id: str,
    background_tasks: BackgroundTasks,
    scenes_config: str = Form(...),
    redo_scene_ids: str = Form(...),
    new_images: list[UploadFile] = File(default=[]),
    new_image_indices: list[str] = Form(default=[]),
    transition_style: str = Form(None),
):
    """
    Batches multiple scene redos into ONE locked operation with ONE final
    reassembly, and persists the FULL current scene list (captions/voiceover
    for every scene, not just the ones being redone) -- matching what the
    legacy endpoint did, but in-place in this job's own directory with no
    sibling job ever created.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]

    # SAFETY NET (2026-07-17 fix): the frontend has a known pre-existing gap
    # where a freshly-created draft job's currentJobStatus can incorrectly
    # read as not-draft, misrouting a narration-triggered duration change
    # into a rework call for a job that was never actually generated. The
    # legacy /rework endpoint always caught this with a clear error; this
    # endpoint didn't, and would silently misprocess a draft job as if it
    # were a rework. Restoring that same guard here.
    if job.get("status") not in ("done", "failed", "awaiting_approval"):
        raise HTTPException(
            status_code=400,
            detail=f"Job must be completed before rework (current status: {job.get('status')})"
        )

    try:
        new_scenes_config = json.loads(scenes_config)
        redo_ids = json.loads(redo_scene_ids)
        if not isinstance(new_scenes_config, list) or not isinstance(redo_ids, list):
            raise ValueError("scenes_config and redo_scene_ids must be JSON arrays")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    if not _acquire_job_lock(job_id, f"batch redo {len(redo_ids)} scene(s)"):
        lock = _job_lock_status(job_id)
        raise HTTPException(
            status_code=409,
            detail=f"Job is currently being modified ({lock.get('operation')}) — please wait and try again."
        )

    try:
        new_scenes_config = _ensure_scene_ids(new_scenes_config)

        job_dir = JOBS_DIR / job_id
        img_dir = job_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)

        for upload, idx_str in zip(new_images, new_image_indices):
            try:
                idx = int(idx_str)
                if idx >= len(new_scenes_config):
                    continue
                content = await upload.read()
                if len(content) > 20 * 1024 * 1024:
                    log.warning(f"[BatchRedo] New image at index {idx} exceeds 20MB, skipping")
                    continue
                if not _validate_image_bytes(content):
                    log.warning(f"[BatchRedo] New image at index {idx} failed validation, skipping")
                    continue
                # 2026-07-17: normalize to the job's already-established
                # output_format -- inherit, don't re-vote, since this job
                # already has generated scenes locked to a specific canvas
                content = _normalize_photo_to_format(content, job.get("output_format", "landscape"))
                new_scene_id = new_scenes_config[idx]["scene_id"]
                ext = Path(upload.filename).suffix.lower() or ".jpg"
                if upload.content_type == "image/jpeg": ext = ".jpg"
                elif upload.content_type == "image/png":  ext = ".png"
                elif upload.content_type == "image/webp": ext = ".webp"
                dest = img_dir / f"{new_scene_id}{ext}"
                with open(dest, "wb") as f:
                    f.write(content)
                if new_scene_id not in redo_ids:
                    redo_ids.append(new_scene_id)
            except Exception as e:
                log.error(f"[BatchRedo] Failed to save new image at index {idx_str}: {e}")

        valid_ids = {s.get("scene_id") for s in new_scenes_config}
        redo_ids = [rid for rid in redo_ids if rid in valid_ids]

        if transition_style:
            job["transition_style"] = transition_style

        job["scenes_config"] = new_scenes_config
        job["total_scenes"]  = len(new_scenes_config)
        job["status"]  = "running"
        job["message"] = f"Rework: rigenerazione di {len(redo_ids)} scena/e in corso…"
        _save_job(job_id)
    except Exception:
        _release_job_lock(job_id)
        raise

    background_tasks.add_task(run_redo_scenes_batch, job_id=job_id, scene_ids=redo_ids)
    return {"job_id": job_id, "status": "running", "scenes_to_redo": redo_ids}


async def run_redo_scenes_batch(job_id: str, scene_ids: list):
    """Regenerates MULTIPLE scenes in one locked operation, then reassembles
    once at the end. See redo_scenes_batch() above for context.
    """
    def update(status, progress, message):
        JOBS[job_id].update({"status": status, "progress": progress, "message": message})
        _save_job(job_id)
        log.info(f"[Job {job_id}] {progress}% — {message}")

    try:
        job = JOBS[job_id]
        job_dir = JOBS_DIR / job_id
        scenes_config = job.get("scenes_config", [])
        lighting  = job.get("lighting", "bright_natural")
        intensity = job.get("intensity", "natural_pace")
        model_tier = job.get("model_tier", "premium")
        do_video_upscale = job.get("do_video_upscale", True)

        n = max(len(scene_ids), 1)
        redone_results = []
        statuses = job.get("scenes", [])

        for idx, scene_id in enumerate(scene_ids):
            scene_idx = next((i for i, s in enumerate(scenes_config) if s.get("scene_id") == scene_id), None)
            if scene_idx is None:
                log.warning(f"[Job {job_id}] Batch redo: scene {scene_id} not found, skipping")
                continue
            scene = scenes_config[scene_idx]

            voiceover = scene.get("voiceover", "").strip()
            user_duration = int(scene.get("duration", 10))
            actual_duration = user_duration

            audio_dir = job_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_out = str(audio_dir / f"{scene_id}.mp3")

            if voiceover:
                update("running", int(5 + (idx/n)*80), f"Rework: rigenero voiceover ({idx+1}/{n})…")
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
                    except Exception as e:
                        log.warning(f"[Job {job_id}] Could not measure audio for {scene_id}: {e}")

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
                for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                    legacy_candidate = img_dir / f"scene_{scene_idx:03d}{ext}"
                    if legacy_candidate.exists():
                        new_name = img_dir / f"{scene_id}{ext}"
                        shutil.copy2(str(legacy_candidate), str(new_name))
                        source_img = new_name
                        break
            if not source_img:
                log.error(f"[Job {job_id}] Batch redo: no source image for scene {scene_id}, skipping")
                continue

            enhanced_img = enhanced_dir / f"{scene_id}_enhanced.jpg"
            if not enhanced_img.exists():
                from image_enhance import enhance_image
                update("running", int(10 + (idx/n)*80), f"Rework: miglioro immagine ({idx+1}/{n})…")
                await asyncio.to_thread(enhance_image, str(source_img), str(enhanced_img), True, True)
            img_for_generation = str(enhanced_img) if enhanced_img.exists() else str(source_img)

            clips_dir = job_dir / "clips"
            clips_dir.mkdir(exist_ok=True)
            clip_out = str(clips_dir / f"{scene_id}.mp4")

            update("running", int(15 + (idx/n)*80), f"Rework: rigenero clip {idx+1}/{n} ({actual_duration}s)…")
            from video_generation import generate_video_single
            ok_video = await asyncio.to_thread(
                generate_video_single,
                img_for_generation, actual_duration, clip_out,
                space_type=scene.get("space_type", "large"),
                pov_movement=scene.get("pov_movement", "walk_in_explore"),
                lighting=lighting,
                intensity=intensity,
                model_tier=model_tier,
                output_format=job.get("output_format", "landscape"),  # 2026-07-27, backlog item 37
                do_video_upscale=do_video_upscale,
            )
            if not ok_video:
                log.error(f"[Job {job_id}] Batch redo: video generation failed for scene {scene_id}")
                continue

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

            redone_results.append({
                "duration": actual_duration,
                "had_voiceover": bool(voiceover),
                "voiceover_chars": len(voiceover) if voiceover else 0,
            })

        job["scenes"] = statuses
        _save_job(job_id)

        if redone_results:
            from cost_tracker import calculate_rework_cost, format_cost_display
            pricing_scenes = [{"duration": r["duration"]} for r in redone_results]
            total_voiceover_chars = sum(r["voiceover_chars"] for r in redone_results)
            any_voiceover = any(r["had_voiceover"] for r in redone_results)
            rework_cost = calculate_rework_cost(
                scenes_redone=pricing_scenes,
                models_used=[model_tier] * len(pricing_scenes),
                redo_video=True,
                redo_audio=any_voiceover,
                audio_chars=total_voiceover_chars,
                model_tier=model_tier,
            )
            job.setdefault("reworks", []).append(rework_cost)
            original_raw = job.get("cost_actual_raw")
            if original_raw:
                job["cost_actual"] = format_cost_display(original_raw, previous_reworks=job["reworks"])
            else:
                legacy_total = (job.get("cost_actual") or {}).get("grand_total_eur", 0)
                pseudo_raw = {"type": "actual", "total_eur": legacy_total, "model_tier": model_tier}
                job["cost_actual"] = format_cost_display(pseudo_raw, previous_reworks=job["reworks"])
            _save_job(job_id)

        await run_reassemble_only(job_id)

    except Exception as e:
        log.error(f"[Job {job_id}] batch redo failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Errore: {str(e)[:200]}"})
        _save_job(job_id)
    finally:
        _release_job_lock(job_id)


async def run_redo_audio_only(job_id: str, scene_ids: list):
    """2026-07-23: regenerates ONLY the TTS audio for the given scenes,
    reusing their EXISTING video clips untouched -- no Luma/Veo cost at
    all, just the cheap ElevenLabs TTS charge. Mirrors the relevant slice
    of run_redo_scenes_batch() above but skips every video-generation
    step entirely, and reassembles via the SAME shared
    run_reassemble_only() every other path uses -- no separate assembly
    logic, per the architecture-discipline principle.
    """
    def update(status, progress, message):
        JOBS[job_id].update({"status": status, "progress": progress, "message": message})
        _save_job(job_id)
        log.info(f"[Job {job_id}] {progress}% -- {message}")

    try:
        job = JOBS[job_id]
        job_dir = JOBS_DIR / job_id
        scenes_config = job.get("scenes_config", [])
        statuses = job.get("scenes", [])

        n = max(len(scene_ids), 1)
        redone_results = []

        for idx, scene_id in enumerate(scene_ids):
            scene_idx = next((i for i, s in enumerate(scenes_config) if s.get("scene_id") == scene_id), None)
            if scene_idx is None:
                log.warning(f"[Job {job_id}] Audio-only redo: scene {scene_id} not found, skipping")
                continue
            scene = scenes_config[scene_idx]
            voiceover = scene.get("voiceover", "").strip()

            if not voiceover:
                log.warning(f"[Job {job_id}] Audio-only redo: scene {scene_id} has no voiceover text, nothing to regenerate, skipping")
                continue

            audio_dir = job_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_out = str(audio_dir / f"{scene_id}.mp3")

            update("running", int(10 + (idx/n)*80), f"Rework audio: rigenero voiceover ({idx+1}/{n})...")
            from voice_generation import generate_speech as generate_voice
            ok_audio = await asyncio.to_thread(
                generate_voice, voiceover, audio_out,
                voice_id=os.getenv("DEFAULT_VOICE_ID") or None
            )
            if not ok_audio or not Path(audio_out).exists():
                log.error(f"[Job {job_id}] Audio-only redo: TTS generation failed for scene {scene_id}")
                continue

            found = False
            for s in statuses:
                if s.get("scene_id") == scene_id:
                    s["audio"] = "ok"
                    found = True
                    break
            if not found:
                statuses.append({
                    "scene_id": scene_id, "index": scene_idx,
                    "caption": scene.get("caption", ""), "video": "ok",
                    "audio": "ok", "qc_verdict": "pass",
                })

            redone_results.append({"voiceover_chars": len(voiceover)})

        job["scenes"] = statuses
        _save_job(job_id)

        if redone_results:
            from cost_tracker import calculate_rework_cost, format_cost_display
            total_voiceover_chars = sum(r["voiceover_chars"] for r in redone_results)
            rework_cost = calculate_rework_cost(
                scenes_redone=[],
                models_used=[],
                redo_video=False,
                redo_audio=True,
                audio_chars=total_voiceover_chars,
                model_tier=job.get("model_tier", "premium"),
            )
            job.setdefault("reworks", []).append(rework_cost)
            original_raw = job.get("cost_actual_raw")
            if original_raw:
                job["cost_actual"] = format_cost_display(original_raw, previous_reworks=job["reworks"])
            else:
                legacy_total = (job.get("cost_actual") or {}).get("grand_total_eur", 0)
                pseudo_raw = {"type": "actual", "total_eur": legacy_total, "model_tier": job.get("model_tier", "premium")}
                job["cost_actual"] = format_cost_display(pseudo_raw, previous_reworks=job["reworks"])
            _save_job(job_id)

        await run_reassemble_only(job_id)

    except Exception as e:
        log.error(f"[Job {job_id}] audio-only redo failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Errore: {str(e)[:200]}"})
        _save_job(job_id)
    finally:
        _release_job_lock(job_id)


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY sibling-directory rework model — kept only for any old in-flight jobs.
# Do not build new features on this. Use the endpoints above instead.
# ══════════════════════════════════════════════════════════════════════════════


# 2026-07-21: the legacy /jobs/{id}/rework endpoint (sibling-directory
# model) was removed here, along with run_rework() (see the end of this
# file) -- confirmed via direct grep zero remaining callers in ui.html.
# Fully superseded by /jobs/{id}/scenes/redo-batch.
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
    output_format:    str  = "landscape",  # 2026-07-27 URGENT FIX: was incorrectly job.get(...) with no local job variable
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
        # 2026-07-27: real bug -- a TTS failure here (e.g. an invalid
        # voice ID) previously fell through to the exact same audio_paths
        # None as a scene with NO voiceover text at all, silently, with
        # no log warning and no way for the UI to distinguish "nothing to
        # say" from "tried to generate audio and it failed" -- both
        # showed as "skipped". This list tracks the real failures so both
        # get labeled correctly and surfaced.
        tts_failed_scenes = []


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
                    log.warning(f"[Job {job_id}] TTS generation FAILED for scene {i} "
                                f"(voiceover: {voiceover[:60]!r}) -- audio will be missing for this scene")
                    tts_failed_scenes.append(i)
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
                output_format=output_format,  # 2026-07-27 URGENT FIX: use the local parameter, not a nonexistent job dict
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
                "audio":           "ok" if audio_paths[i] else ("failed" if i in tts_failed_scenes else "skipped"),
                "qc_verdict":      video_verdict,
            })


        JOBS[job_id]["scenes"]     = scene_statuses
        JOBS[job_id]["qc_results"] = qc_results
        if tts_failed_scenes:
            JOBS[job_id]["tts_failures"] = tts_failed_scenes
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
        # 2026-07-21 consolidation: run_assembly() and run_reassemble_only()
        # were near-duplicate "assemble the final video" implementations --
        # this one lacked the legacy-clip self-heal fallback the other had.
        # Now uses the single, more robust implementation everywhere.
        await run_reassemble_only(job_id)


        # ── Actual cost ───────────────────────────────────────────────────
        # 2026-07-21 fix (architecture assessment item 31): fold in real
        # Claude API cost for scraped jobs (stored on the job dict at
        # creation time by create_job_from_url) -- was captured but never
        # actually counted in the displayed total. Absent/0 for manual
        # jobs, which never call Claude at all.
        claude_cost_eur = JOBS[job_id].get("claude_usage", {}).get("cost_eur", 0.0)
        from cost_tracker import calculate_actual_cost, format_cost_display
        actual = calculate_actual_cost(
            scenes_config, models_used, audio_chars,
            do_upscale=do_upscale, do_vision_qc=enable_vision_qc,
            model_tier=model_tier, claude_cost_eur=claude_cost_eur,
        )
        JOBS[job_id]["cost_actual_raw"] = actual
        JOBS[job_id]["cost_actual"] = format_cost_display(actual, previous_reworks=JOBS[job_id].get("reworks", []))
        _save_job(job_id)


        check_and_alert(job_id=job_id, property_name=property_name)


    except Exception as e:
        log.error(f"[Job {job_id}] Pipeline failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Error: {str(e)}"})
        _save_job(job_id)




# ── Assembly: run_assembly() removed 2026-07-21 -- was a near-duplicate of
# run_reassemble_only() (see that function, above run_pipeline), which is
# now the single implementation used by run_pipeline, /approve, and every
# redo/rework path. Removed rather than left unused, per an explicit
# decision to keep the architecture simple -- no duplicate paths unless
# strictly necessary, and this one wasn't. Rollback: git revert to commit
# af826498c462729d0b5b1e31c8a3661ad5145b62 if this causes a real problem.


# ── Rework runner: run_rework() removed 2026-07-21 -- along with the
# /jobs/{id}/rework endpoint that called it (confirmed via direct grep:
# zero references anywhere in ui.html). This was the legacy sibling-
# directory rework model, fully superseded by run_redo_scenes_batch()
# and the single-directory job model. Removed rather than left unused,
# per the same architecture-discipline decision as run_assembly()'s
# removal earlier the same day.
