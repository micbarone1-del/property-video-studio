"""
clip_provenance.py
------------------
Which model really produced each clip, and the one shared way to find a
scene's clip file (2026-10-15, Patch A).

Why this exists: generate_video_single() knew which model made a clip
(`used_model`) but only wrote it to the log, so a silent switch from the
direct Luma API to fal.ai (Luma Ray 2 at about 2.00 USD per 5 s clip, or
Veo) was invisible and cost more than expected. Now every clip gets a small
sidecar file `<clip>.mp4.model.json`, and the API reads them back to show a
red warning in the UI.

Deliberately independent from fal_client / job state: no job state is
changed anywhere, the sidecars are only read to build a summary.
"""
import json
import time
from pathlib import Path

SIDECAR_SUFFIX = ".model.json"


def is_fal_substitute(used_model, model_tier):
    """True when a clip came from fal.ai instead of the provider the tier is
    meant to use: any '-fallback' model, the LTX emergency model, or (for the
    luma tier, which is meant to run on the direct Luma API) any model that
    is not the direct one."""
    m = used_model or ""
    if m.endswith("-fallback") or m == "ltx-emergency":
        return True
    if model_tier == "luma" and not m.endswith("-direct"):
        return True
    return False


def sidecar_path(clip_path):
    return Path(str(clip_path) + SIDECAR_SUFFIX)


def write(clip_path, used_model, model_tier, reason=None):
    """Best effort: never raises (a failed note must not fail a paid clip)."""
    try:
        data = {
            "model": used_model,
            "tier": model_tier,
            "fal_substitute": bool(is_fal_substitute(used_model, model_tier)),
            "reason": reason,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        sidecar_path(clip_path).write_text(json.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return False


def read(clip_path):
    try:
        return json.loads(sidecar_path(clip_path).read_text(encoding="utf-8"))
    except Exception:
        return None


LOST_SUFFIX = ".lost.json"


def lost_path(clip_path):
    return Path(str(clip_path) + LOST_SUFFIX)


def write_lost(clip_path, info, duration):
    """2026-10-28 (P2): a generation that was started (and is probably billed) but gave no usable clip. Best effort."""
    try:
        data = dict(info or {})
        data.update({"duration": int(duration), "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        lost_path(clip_path).write_text(json.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return False


def read_lost(clip_path):
    try:
        return json.loads(lost_path(clip_path).read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_lost(clip_path):
    try:
        lost_path(clip_path).unlink()
    except Exception:
        pass


def used_model_of(clip_path):
    """The model that really made this clip (from its sidecar), or None if unknown (clips made before the sidecars)."""
    meta = read(clip_path) if clip_path else None
    return (meta or {}).get("model")


def clip_file_for_scene(job_dir, scene_index, scene_id=None):
    """The ONE resolver for 'which file is this scene's clip'. Same order the
    reassemble step uses: the scene's stable scene_id file first (a rework
    writes a new scene_id), then the legacy scene_NNN.mp4. Returns None if
    neither exists."""
    clips = Path(job_dir) / "clips"
    if scene_id:
        p = clips / f"{scene_id}.mp4"
        if p.exists():
            return p
    p = clips / f"scene_{int(scene_index):03d}.mp4"
    return p if p.exists() else None


def summarize(job_dir, scenes_config):
    """Read-only summary for the API / UI. Clips without a sidecar (made
    before this patch) are simply not counted."""
    out = {"clips": [], "fal_clips": 0, "level": "none",
           "est_usd_on_fal": 0.0, "est_usd_if_direct": 0.0}
    try:
        from cost_tracker import clip_price_usd, LUMA_DIRECT_USD_PER_CLIP
    except Exception:
        clip_price_usd, LUMA_DIRECT_USD_PER_CLIP = (lambda m, d=5: None), None
    for i, sc in enumerate(scenes_config or []):
        sid = (sc or {}).get("scene_id")
        f = clip_file_for_scene(job_dir, i, sid)
        if not f:
            continue
        meta = read(f)
        if not meta or not meta.get("fal_substitute"):
            continue
        model = meta.get("model")
        dur = (sc or {}).get("duration") or 5
        price = clip_price_usd(model, dur)
        out["clips"].append({
            "index": i, "scene_id": sid, "model": model,
            "reason": meta.get("reason"), "price_usd": price,
        })
        out["fal_clips"] += 1
        if price:
            out["est_usd_on_fal"] += price
        if LUMA_DIRECT_USD_PER_CLIP:
            out["est_usd_if_direct"] += LUMA_DIRECT_USD_PER_CLIP
        if str(model).startswith("veo") or model == "ltx-emergency":
            out["level"] = "high"
        elif out["level"] != "high":
            out["level"] = "fal"
    out["est_usd_on_fal"] = round(out["est_usd_on_fal"], 2)
    out["est_usd_if_direct"] = round(out["est_usd_if_direct"], 2)
    return out
