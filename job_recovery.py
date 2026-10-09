"""Startup recovery for jobs orphaned by a server restart.

2026-10-08 (task 4): a job left "running" or "queued" by a restart has no
thread that will ever finish it, and _save_job() used to write
job_meta.json non-atomically. This module holds the pure, testable logic;
api_server.py only wires it in at startup.
"""
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import rework_policy

ORPHAN_STATES = ("running", "queued")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def atomic_write_json(path, obj):
    """Write JSON to a temp file in the same folder, then os.replace().
    A crash mid-write leaves the old file intact instead of a truncated one."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".job_meta_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def probe_duration(path):
    """Duration in seconds via ffprobe, or None if unreadable/truncated."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def classify_orphan(job, job_dir):
    """Returns (new_status, message) for a job found running/queued at startup."""
    out = job.get("output_path")
    if out and Path(out).is_file() and (probe_duration(out) or 0) > 0:
        return "done", ("Il server e' stato riavviato durante un'operazione: "
                        "il video precedente e' ancora valido. Controlla le ultime modifiche.")
    imgs = Path(job_dir) / "images"
    has_images = imgs.is_dir() and any(p.suffix.lower() in IMAGE_EXTS for p in imgs.iterdir())
    if job.get("scenes_config") and has_images:
        return "interrupted", "Interrotto da un riavvio del server. Le scene gia' pronte non vanno perse."
    return "failed", ("Interrotto da un riavvio del server prima che il job avesse scene e foto. "
                      "Va ricreato.")


def recover_orphans(jobs, jobs_dir, save_fn):
    """Fixes the status of every orphaned job in `jobs`, persists each via
    save_fn(job_id), and returns a list describing what changed."""
    recovered = []
    for job_id, job in list(jobs.items()):
        old = job.get("status")
        if old not in ORPHAN_STATES:
            continue
        new, msg = classify_orphan(job, Path(jobs_dir) / job_id)
        job["status"] = new
        job["message"] = msg
        # 2026-10-09: a rework cut short by the restart must not look like a
        # clean "done" -- rework_policy turns it into rework_incomplete +
        # needs_operator and gives the interrupted round back.
        rw_ids = rework_policy.recovery_mark(job)
        if rw_ids is not None and new == "done":
            job["message"] = ("Rework interrotto dal riavvio (scene: "
                              + ", ".join(rw_ids) + "). Il video mostrato e' la versione precedente.")
        job["recovered_from"] = old
        job["recovered_at"] = datetime.utcnow().isoformat()
        save_fn(job_id)
        recovered.append({
            "job_id": job_id, "old": old, "new": new,
            "property_name": job.get("property_name"),
            "has_callback": bool(job.get("callback_url")),
            "rework_incomplete": rw_ids,
        })
    return recovered


# ── Stage 2 (2026-10-08): reuse of work already on disk when a job is resumed ──

def clip_is_valid(path):
    """A clip is reusable only if ffprobe can read it and it has real length."""
    return (probe_duration(path) or 0) > 1.0


def audio_is_valid(path):
    return (probe_duration(path) or 0) > 0.3


def image_is_valid(path):
    """Fully decodes the image, so a file truncated by a crash is not trusted."""
    p = Path(path)
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return False
    except OSError:
        return False
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        with Image.open(p) as im:
            im.load()
        return True
    except Exception:
        return False
