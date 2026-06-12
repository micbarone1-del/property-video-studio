"""
api_server.py
─────────────
FastAPI backend for the real estate video production pipeline.
Replaces the email-based interface with a simple REST API.

Endpoints:
  POST /jobs/              – Submit a new video job (multipart: images + JSON config)
  GET  /jobs/{id}          – Poll job status and progress
  GET  /jobs/{id}/download – Download the finished .mp4
  GET  /                   – Serves the UI (ui.html)
  GET  /health             – Health check

Run:
  uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import uuid
import json
import shutil
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── Directories ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
JOBS_DIR    = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

# ── In-memory job store (replace with SQLite/Redis for production) ─────────────
# Structure: { job_id: { status, progress, message, scenes, output_path, created_at } }
JOBS: dict = {}

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Real Estate Video Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the UI as a static file
if (BASE_DIR / "ui.html").exists():
    @app.get("/", response_class=FileResponse)
    def serve_ui():
        return FileResponse(BASE_DIR / "ui.html")


@app.get("/credits")
def get_credits():
    """Returns live credit balances for the UI banner."""
    from credit_monitor import get_all_credits
    return get_all_credits()


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ── Job submission ─────────────────────────────────────────────────────────────

@app.post("/jobs/")
async def create_job(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    config: str = Form(...),          # JSON string: list of scene configs
    property_name: str = Form("Property"),
    voice_id: str = Form(""),         # ElevenLabs voice ID, optional
    enhance_images: bool = Form(True),
    upscale_images: bool = Form(True),
):
    """
    Submit a new video generation job.

    config is a JSON array with one object per scene, in image order:
    [
      { "caption": "Bright open living room", "voiceover": "Welcome to this stunning...", "duration": 8 },
      { "caption": "Chef's kitchen", "voiceover": "The kitchen features...", "duration": 6 },
      ...
    ]
    """
    # Validate config
    try:
        scenes_config = json.loads(config)
        if not isinstance(scenes_config, list):
            raise ValueError("config must be a JSON array")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config JSON: {e}")

    if len(images) != len(scenes_config):
        raise HTTPException(
            status_code=400,
            detail=f"Number of images ({len(images)}) must match number of scene configs ({len(scenes_config)})"
        )

    # Create job workspace
    job_id   = str(uuid.uuid4())[:8]
    job_dir  = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    img_dir  = job_dir / "images"
    img_dir.mkdir()

    # Save uploaded images with correct extensions
    saved_images = []
    for i, upload in enumerate(images):
        ext = Path(upload.filename).suffix.lower() or ".jpg"
        # Detect actual type from content type header
        if upload.content_type == "image/jpeg":
            ext = ".jpg"
        elif upload.content_type == "image/png":
            ext = ".png"
        elif upload.content_type == "image/webp":
            ext = ".webp"
        dest = img_dir / f"scene_{i:03d}{ext}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        saved_images.append(str(dest))

    # Register job
    JOBS[job_id] = {
        "status":       "queued",
        "progress":     0,
        "message":      "Job queued",
        "scenes":       [],
        "output_path":  None,
        "created_at":   datetime.utcnow().isoformat(),
        "property_name": property_name,
        "total_scenes": len(images),
    }

    # Kick off background processing
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
    )

    return {"job_id": job_id, "status": "queued"}


# ── Job status polling ─────────────────────────────────────────────────────────

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id].copy()
    job.pop("output_path", None)   # don't expose local path
    return job


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail=f"Job not ready (status: {job['status']})")
    output_path = job.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    filename = f"{job.get('property_name', 'property').replace(' ', '_')}_video.mp4"
    return FileResponse(output_path, media_type="video/mp4", filename=filename)


# ── Pipeline runner (runs in background) ──────────────────────────────────────

async def run_pipeline(
    job_id: str,
    job_dir: Path,
    image_paths: list,
    scenes_config: list,
    property_name: str,
    voice_id: str,
    do_lighting: bool,
    do_upscale: bool,
):
    """
    Orchestrates the full pipeline for one job:
      1. Enhance images (lighting + upscale)
      2. Generate TTS audio per scene
      3. Generate AI video per scene
      4. Assemble final video
    """
    def update(status: str, progress: int, message: str):
        JOBS[job_id]["status"]   = status
        JOBS[job_id]["progress"] = progress
        JOBS[job_id]["message"]  = message
        log.info(f"[Job {job_id}] {progress}% — {message}")

    try:
        update("running", 2, "Starting pipeline…")

        # ── Credit check at job start ──────────────────────────────────────
        from credit_monitor import check_and_alert
        credit_status = check_and_alert(job_id=job_id, property_name=property_name)
        JOBS[job_id]["credits"] = credit_status
        if credit_status["any_low"]:
            log.warning(f"[Job {job_id}] Low credits detected at job start — alert sent.")

        enhanced_dir   = job_dir / "enhanced"
        audio_dir      = job_dir / "audio"
        video_clips_dir = job_dir / "clips"
        enhanced_dir.mkdir()
        audio_dir.mkdir()
        video_clips_dir.mkdir()

        n = len(image_paths)
        enhanced_paths  = []
        audio_paths     = []
        video_clip_paths = []

        # ── Stage 1: Image enhancement ────────────────────────────────────
        from image_enhance import enhance_image

        for i, img_path in enumerate(image_paths):
            update("running", int(5 + (i / n) * 20), f"Enhancing image {i+1} of {n}…")
            out = str(enhanced_dir / f"scene_{i:03d}_enhanced.jpg")
            result = await asyncio.to_thread(
                enhance_image, img_path, out, do_lighting, do_upscale
            )
            enhanced_paths.append(result)

        # ── Stage 2: TTS audio ────────────────────────────────────────────
        from voice_generation import generate_voice

        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            voiceover = scene.get("voiceover", "").strip()
            audio_out = str(audio_dir / f"scene_{i:03d}.mp3")
            update("running", int(25 + (i / n) * 20), f"Generating audio {i+1} of {n}…")

            if voiceover:
                ok = await asyncio.to_thread(
                    generate_voice, voiceover, audio_out, voice_id=voice_id or None
                )
                audio_paths.append(audio_out if ok else None)
            else:
                audio_paths.append(None)

        # ── Stage 3: AI video generation ─────────────────────────────────
        from video_generation import generate_video_single

        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            clip_out = str(video_clips_dir / f"scene_{i:03d}.mp4")
            duration = int(scene.get("duration", 8))
            hint     = scene.get("caption", "")
            update("running", int(45 + (i / n) * 35), f"Generating video clip {i+1} of {n}…")

            ok = await asyncio.to_thread(
                generate_video_single,
                img, clip_out, duration, hint
            )
            video_clip_paths.append(clip_out if ok else None)

        # ── Stage 4: Assembly ─────────────────────────────────────────────
        update("running", 82, "Assembling final video…")

        output_path = str(job_dir / f"{property_name.replace(' ', '_')}_final.mp4")

        from video_assembly import assemble_property_video
        ok = await asyncio.to_thread(
            assemble_property_video,
            scenes_config=scenes_config,
            video_clip_paths=video_clip_paths,
            audio_paths=audio_paths,
            image_paths=enhanced_paths,
            output_path=output_path,
            property_name=property_name,
        )

        if not ok:
            raise RuntimeError("Assembly step returned failure")

        JOBS[job_id]["output_path"] = output_path
        update("done", 100, "Video ready for download")

        # ── Credit check at job end ────────────────────────────────────────
        credit_status = check_and_alert(job_id=job_id, property_name=property_name)
        JOBS[job_id]["credits"] = credit_status

    except Exception as e:
        log.error(f"[Job {job_id}] Pipeline failed: {e}", exc_info=True)
        JOBS[job_id]["status"]  = "failed"
        JOBS[job_id]["message"] = f"Error: {str(e)}"
