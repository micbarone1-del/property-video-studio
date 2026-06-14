"""
api_server.py  v2
─────────────────
New in v2:
  - camera_hint per scene (passed through to video_generation)
  - transition_style global setting
  - Rework endpoint: POST /jobs/{id}/rework — regenerate selected scenes only
  - Scene-level status tracking so UI knows which clips succeeded
"""

import os
import uuid
import json
import shutil
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
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

app = FastAPI(title="Real Estate Video Generator", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if (BASE_DIR / "ui.html").exists():
    @app.get("/", response_class=FileResponse)
    def serve_ui():
        return FileResponse(BASE_DIR / "ui.html")


@app.get("/credits")
def get_credits():
    from credit_monitor import get_all_credits
    return get_all_credits()


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/jobs/")
async def create_job(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    config: str = Form(...),
    property_name: str = Form("Property"),
    voice_id: str = Form(""),
    enhance_images: bool = Form(True),
    upscale_images: bool = Form(True),
    transition_style: str = Form("fade"),
):
    """
    config is a JSON array, one object per scene:
    [
      {
        "caption":     "Living room",
        "voiceover":   "Welcome to this stunning...",
        "duration":    8,
        "camera_hint": "pan_right"   <- new in v2
      },
      ...
    ]
    transition_style: "fade" | "slide_left" | "slide_right" | "cut"
    """
    try:
        scenes_config = json.loads(config)
        if not isinstance(scenes_config, list):
            raise ValueError("config must be a JSON array")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config JSON: {e}")

    if len(images) != len(scenes_config):
        raise HTTPException(status_code=400,
            detail=f"Images ({len(images)}) must match scene configs ({len(scenes_config)})")

    job_id  = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    img_dir = job_dir / "images"
    img_dir.mkdir(parents=True)

    saved_images = []
    for i, upload in enumerate(images):
        ext = Path(upload.filename).suffix.lower() or ".jpg"
        if upload.content_type == "image/jpeg": ext = ".jpg"
        elif upload.content_type == "image/png":  ext = ".png"
        elif upload.content_type == "image/webp": ext = ".webp"
        dest = img_dir / f"scene_{i:03d}{ext}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        saved_images.append(str(dest))

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
    }

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
    )

    return {"job_id": job_id, "status": "queued"}


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
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail=f"Job not ready (status: {job['status']})")
    output_path = job.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    filename = f"{job.get('property_name','property').replace(' ','_')}_video.mp4"
    return FileResponse(output_path, media_type="video/mp4", filename=filename)


@app.post("/jobs/{job_id}/rework")
async def rework_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    rework_config: str = Form(...),
):
    """
    Regenerate only selected scenes from a completed job.
    rework_config is a JSON object:
    {
      "scenes": [0, 2],           <- scene indices to redo
      "redo_video": true,         <- regenerate video clips for these scenes
      "redo_audio": false,        <- regenerate audio for these scenes
      "updated_scenes": [         <- updated scene configs (same order as original)
        { "caption": "...", "voiceover": "...", "duration": 8, "camera_hint": "dolly_in" },
        ...
      ]
    }
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    original = JOBS[job_id]
    if original["status"] not in ["done", "failed"]:
        raise HTTPException(status_code=400, detail="Job must be completed before rework")

    try:
        cfg = json.loads(rework_config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid rework_config: {e}")

    rework_id  = f"{job_id}_rw{str(uuid.uuid4())[:4]}"
    JOBS[rework_id] = {
        "status":        "queued",
        "progress":      0,
        "message":       f"Rework of job {job_id} queued",
        "parent_job_id": job_id,
        "output_path":   None,
        "created_at":    datetime.utcnow().isoformat(),
        "property_name": original["property_name"],
        "total_scenes":  original["total_scenes"],
    }

    background_tasks.add_task(
        run_rework,
        rework_id=rework_id,
        parent_job_id=job_id,
        cfg=cfg,
    )

    return {"job_id": rework_id, "status": "queued", "parent_job_id": job_id}


# ── Pipeline runner ────────────────────────────────────────────────────────────

async def run_pipeline(
    job_id: str,
    job_dir: Path,
    image_paths: list,
    scenes_config: list,
    property_name: str,
    voice_id: str,
    do_lighting: bool,
    do_upscale: bool,
    transition_style: str = "fade",
):
    def update(status, progress, message):
        JOBS[job_id].update({"status": status, "progress": progress, "message": message})
        log.info(f"[Job {job_id}] {progress}% — {message}")

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

        n = len(image_paths)
        enhanced_paths   = []
        audio_paths      = []
        video_clip_paths = []
        scene_statuses   = []

        # Stage 1 — Image enhancement
        from image_enhance import enhance_image
        for i, img_path in enumerate(image_paths):
            update("running", int(5 + (i / n) * 20), f"Enhancing image {i+1} of {n}…")
            out    = str(enhanced_dir / f"scene_{i:03d}_enhanced.jpg")
            result = await asyncio.to_thread(enhance_image, img_path, out, do_lighting, do_upscale)
            enhanced_paths.append(result)

        # Stage 2 — TTS audio
        from voice_generation import generate_speech as generate_voice
        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            voiceover = scene.get("voiceover", "").strip()
            audio_out = str(audio_dir / f"scene_{i:03d}.mp3")
            update("running", int(25 + (i / n) * 20), f"Generating audio {i+1} of {n}…")
            if voiceover:
                ok = await asyncio.to_thread(generate_voice, voiceover, audio_out, voice_id=voice_id or None)
                audio_paths.append(audio_out if ok else None)
            else:
                audio_paths.append(None)

        # Stage 3 — AI video generation
        from video_generation import generate_video_single
        for i, (scene, img) in enumerate(zip(scenes_config, enhanced_paths)):
            clip_out    = str(video_clips_dir / f"scene_{i:03d}.mp4")
            duration    = int(scene.get("duration", 8))
            caption     = scene.get("caption", "")
            camera_hint = scene.get("camera_hint", "auto")
            update("running", int(45 + (i / n) * 35), f"Generating video clip {i+1} of {n}…")
            ok = await asyncio.to_thread(
                generate_video_single, img, duration, clip_out, caption, camera_hint
            )
            video_clip_paths.append(clip_out if ok else None)
            scene_statuses.append({
                "index":   i,
                "caption": caption,
                "video":   "ok" if ok else "failed",
                "audio":   "ok" if audio_paths[i] else "skipped",
            })

        JOBS[job_id]["scenes"] = scene_statuses

        # Stage 4 — Assembly
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
            raise RuntimeError("Assembly step returned failure")

        JOBS[job_id]["output_path"] = output_path
        update("done", 100, "Video ready for download")

        check_and_alert(job_id=job_id, property_name=property_name)

    except Exception as e:
        log.error(f"[Job {job_id}] Pipeline failed: {e}", exc_info=True)
        JOBS[job_id].update({"status": "failed", "message": f"Error: {str(e)}"})


# ── Rework runner ──────────────────────────────────────────────────────────────

async def run_rework(rework_id: str, parent_job_id: str, cfg: dict):
    def update(status, progress, message):
        JOBS[rework_id].update({"status": status, "progress": progress, "message": message})
        log.info(f"[Rework {rework_id}] {progress}% — {message}")

    try:
        parent      = JOBS[parent_job_id]
        parent_dir  = JOBS_DIR / parent_job_id
        rework_dir  = JOBS_DIR / rework_id
        rework_dir.mkdir(exist_ok=True)

        # Copy all existing assets from parent
        for sub in ["enhanced", "audio", "clips"]:
            src = parent_dir / sub
            dst = rework_dir / sub
            if src.exists():
                shutil.copytree(str(src), str(dst))
            else:
                (rework_dir / sub).mkdir(exist_ok=True)

        scenes_to_redo  = cfg.get("scenes", [])
        redo_video      = cfg.get("redo_video", True)
        redo_audio      = cfg.get("redo_audio", False)
        updated_scenes  = cfg.get("updated_scenes", [])
        n               = len(scenes_to_redo)

        update("running", 5, f"Reworking {n} scene(s)…")

        from voice_generation import generate_speech as generate_voice
        from video_generation import generate_video_single

        for idx, scene_index in enumerate(scenes_to_redo):
            scene = updated_scenes[scene_index] if scene_index < len(updated_scenes) else {}

            # Redo audio
            if redo_audio and scene.get("voiceover", "").strip():
                audio_out = str(rework_dir / "audio" / f"scene_{scene_index:03d}.mp3")
                update("running", int(10 + (idx/n)*30), f"Regenerating audio for scene {scene_index+1}…")
                await asyncio.to_thread(
                    generate_voice, scene["voiceover"], audio_out,
                    voice_id=os.getenv("DEFAULT_VOICE_ID") or None
                )

            # Redo video
            if redo_video:
                enhanced_img = str(rework_dir / "enhanced" / f"scene_{scene_index:03d}_enhanced.jpg")
                if not Path(enhanced_img).exists():
                    enhanced_img = str(parent_dir / "images" / f"scene_{scene_index:03d}.jpg")
                clip_out    = str(rework_dir / "clips" / f"scene_{scene_index:03d}.mp4")
                duration    = int(scene.get("duration", 8))
                caption     = scene.get("caption", "")
                camera_hint = scene.get("camera_hint", "auto")
                update("running", int(40 + (idx/n)*40), f"Regenerating video clip for scene {scene_index+1}…")
                await asyncio.to_thread(
                    generate_video_single, enhanced_img, duration, clip_out, caption, camera_hint
                )

        # Reassemble
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

    except Exception as e:
        log.error(f"[Rework {rework_id}] Failed: {e}", exc_info=True)
        JOBS[rework_id].update({"status": "failed", "message": f"Error: {str(e)}"})
