"""
video_generation.py  (real-estate edition v6)
──────────────────────────────────────────────
Changes in v6:
  - Lyra 2.0 output resolution upgraded from 480p to 720p
  - NEW: post-generation video upscaling via fal-ai/topaz/upscale/video
    Upscales each clip from 720p to 1080p after generation
    Cost: ~€0.10 per 5s clip (€0.02/s at 720p→1080p tier)
    Controlled by do_video_upscale parameter (default True)
  - Image upscaling (aura-sr) retained but now optional — its main
    value is improving Lyra's 3D depth reconstruction, not output res
  - All v5 space detection, auto presets, and camera logic preserved
  - LTX-2.3 fallback preserved
"""

import os
import logging
import requests
import fal_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Model endpoints ────────────────────────────────────────────────────────────
LYRA_ENDPOINT   = "fal-ai/lyra-2/zoom"
LTX_ENDPOINT    = "fal-ai/ltx-2.3/image-to-video/fast"
TOPAZ_ENDPOINT  = "fal-ai/topaz/upscale/video"

# ── Frame mapping (Lyra uses frames not seconds) ───────────────────────────────
_DURATION_TO_FRAMES = {
    6: 81, 7: 81, 8: 81,
    9: 161, 10: 161, 11: 161, 12: 161,
    13: 161, 14: 161, 15: 161,
    16: 241, 17: 241, 18: 241, 19: 241, 20: 241,
}

# ── Space type detection ───────────────────────────────────────────────────────
_ELEVATED_KW  = [
    "balcony","terrace","loggia","rooftop","roof terrace","roof top",
    "balcone","terrazza","terrazzo","lastrico","loggia","tetto",
    "terrazzo sul tetto","roof garden",
]
_OUTDOOR_KW   = [
    "garden","pool","driveway","facade","courtyard",
    "exterior","outdoor","patio","backyard","front yard","street view",
    "giardino","piscina","vialetto","facciata","cortile",
    "esterno","esterni","patio","retro","fronte","vista strada",
    "giardino posteriore","giardino anteriore","entrata esterna",
]
_SMALLROOM_KW = [
    "bathroom","wc","toilet","ensuite","en-suite","cloakroom",
    "hallway","corridor","laundry","utility","closet","pantry","storage",
    "bagno","wc","toilette","bagno en suite","bagno privato",
    "antibagno","corridoio","lavanderia","ripostiglio","dispensa",
    "cabina armadio","sgabuzzino","disimpegno","ingresso",
]
_BEDROOM_KW   = [
    "bedroom","master bedroom","guest room","guest bedroom",
    "master suite","kids room","nursery",
    "camera","camera da letto","camera matrimoniale","camera singola",
    "camera doppia","camera degli ospiti","stanza da letto",
    "cameretta","camera bambini","suite","suite padronale",
]

def _detect_space(hint: str) -> str:
    h = hint.lower()
    if any(k in h for k in _ELEVATED_KW):  return "elevated"
    if any(k in h for k in _OUTDOOR_KW):   return "outdoor"
    if any(k in h for k in _SMALLROOM_KW): return "small"
    if any(k in h for k in _BEDROOM_KW):   return "bedroom"
    return "large"


# ── AUTO presets ───────────────────────────────────────────────────────────────
_AUTO_PRESETS = {
    "large": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom_bend",
        "zoom_in_strength":   0.28,
    },
    "bedroom": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.20,
    },
    "small": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.13,
    },
    "outdoor": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.25,
    },
    "elevated": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.10,
    },
}

# ── Manual camera presets ──────────────────────────────────────────────────────
CAMERA_PRESETS = {
    "auto":          None,
    "gentle_arc": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom_bend",
        "zoom_in_strength":   0.28,
    },
    "straight_push": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.30,
    },
    "soft_orbit": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.25,
    },
    "minimal": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.10,
    },
    "spiral": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "spiral",
        "zoom_in_strength":   0.30,
    },
    "dolly_zoom": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "dolly_zoom",
        "zoom_in_strength":   0.35,
    },
    "static": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.06,
    },
    "strong_orbit": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.50,
    },
    "pullback_arc": {
        "zoom_direction":     "both",
        "zoom_in_trajectory": "horizontal_zoom_bend",
        "zoom_in_strength":   0.40,
        "zoom_out_trajectory":"horizontal_zoom",
        "zoom_out_strength":  0.55,
    },
    "wide_reveal": {
        "zoom_direction":     "both",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.45,
        "zoom_out_trajectory":"back",
        "zoom_out_strength":  0.90,
    },
}

# ── Scene prompts ──────────────────────────────────────────────────────────────
_PROMPT_BASE = (
    "A high-end real estate {space_desc}. "
    "The scene is a completely frozen tableau — every surface, fixture, "
    "material, and architectural element is perfectly still and motionless. "
    "No people, no wind, no movement of any kind. "
    "The lighting is fixed and permanent. "
    "Rich spatial depth, premium materials, cinema-grade HDR colour grading, "
    "4K texture clarity throughout every frame."
)
_SPACE_DESCRIPTIONS = {
    "large":    "interior — a bright, spacious open-plan living area",
    "bedroom":  "interior — a carefully designed private bedroom",
    "small":    "interior — a precisely fitted compact space",
    "outdoor":  "exterior — a beautifully landscaped outdoor area",
    "elevated": "exterior — an elevated outdoor space with open views",
}


# ── Build Lyra arguments ───────────────────────────────────────────────────────

def _build_lyra_args(image_url, caption, camera_hint, duration):
    space      = _detect_space(caption)
    num_frames = _DURATION_TO_FRAMES.get(duration, 81)
    prompt     = _PROMPT_BASE.format(
        space_desc=_SPACE_DESCRIPTIONS.get(space, "interior")
    )

    if camera_hint == "auto":
        motion = _AUTO_PRESETS[space]
    else:
        motion = CAMERA_PRESETS.get(camera_hint) or _AUTO_PRESETS[space]

    log.info(
        f"[VideoGen] space={space} camera={camera_hint} "
        f"direction={motion.get('zoom_direction')} "
        f"trajectory={motion.get('zoom_in_trajectory','—')} "
        f"strength={motion.get('zoom_in_strength','—')} "
        f"frames={num_frames}"
    )

    args = {
        "image_url":         image_url,
        "prompt":            prompt,
        "zoom_direction":    motion.get("zoom_direction", "in"),
        "num_frames":        num_frames,
        "resolution":        "720p",     # ← upgraded from 480p in v6
        "use_dmd":           True,
        "frames_per_second": 16,
        "guidance_scale":    5,
    }

    if "zoom_in_trajectory"  in motion: args["zoom_in_trajectory"]  = motion["zoom_in_trajectory"]
    if "zoom_in_strength"    in motion: args["zoom_in_strength"]    = motion["zoom_in_strength"]
    if "zoom_out_trajectory" in motion: args["zoom_out_trajectory"] = motion["zoom_out_trajectory"]
    if "zoom_out_strength"   in motion: args["zoom_out_strength"]   = motion["zoom_out_strength"]

    return args


# ── LTX fallback ───────────────────────────────────────────────────────────────
_LTX_PROMPT = (
    "Professional real estate cinematography. Slow steady camera push. "
    "No people, no wind, no hallucinated rooms or fixtures. "
    "Level horizon, zero camera shake. HDR lighting, cinema colour correction."
)
_LTX_VALID = [6, 8, 10, 12, 14, 16, 18, 20]

def _snap_ltx(d):
    for v in _LTX_VALID:
        if v >= d: return v
    return _LTX_VALID[-1]


# ── Video upscaling via Topaz ──────────────────────────────────────────────────

def upscale_video(input_path: str, output_path: str, scale: float = 2.0) -> bool:
    """
    Upscales a video clip using Topaz Video AI via fal.ai.
    Default scale=2.0 takes Lyra's 720p output to 1440p (near-2K).
    Cost: ~€0.02/second at 720p→1080p tier.

    Args:
        input_path:  Local path to the input .mp4
        output_path: Local path for the upscaled .mp4
        scale:       Upscale factor (2.0 = double resolution)

    Returns:
        True on success, False on failure (original clip preserved)
    """
    if not os.environ.get("FAL_KEY"):
        log.warning("[VideoUpscale] FAL_KEY not set — skipping video upscale")
        return False

    if not os.path.exists(input_path):
        log.error(f"[VideoUpscale] Input not found: {input_path}")
        return False

    try:
        log.info(f"[VideoUpscale] Uploading clip for upscaling: {input_path}")
        video_url = fal_client.upload_file(input_path)

        log.info(f"[VideoUpscale] Running Topaz upscale at {scale}× ...")
        result = fal_client.subscribe(
            TOPAZ_ENDPOINT,
            arguments={
                "video_url":      video_url,
                "scale":          scale,
                "model":          "Standard V2",   # balanced quality/speed
                "output_format":  "mp4",
            }
        )

        upscaled_url = (result.get("video") or {}).get("url")
        if not upscaled_url:
            log.error(f"[VideoUpscale] No URL in result: {result}")
            return False

        log.info("[VideoUpscale] Downloading upscaled clip...")
        resp = requests.get(upscaled_url, stream=True, timeout=300)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)

        log.info(f"[VideoUpscale] ✓ Upscaled clip saved: {output_path}")
        return True

    except Exception as e:
        log.error(f"[VideoUpscale] Failed: {e}", exc_info=True)
        return False


# ── Main generation function ───────────────────────────────────────────────────

def generate_video_single(
    image_path:       str,
    duration:         int,
    output_path:      str,
    prompt:           str  = "",
    camera_hint:      str  = "auto",
    model_endpoint:   str  = LYRA_ENDPOINT,
    test_mode:        bool = False,
    do_video_upscale: bool = True,
) -> bool:
    """
    Generates a video clip from one image using Lyra 2.0 at 720p,
    then optionally upscales to ~1440p using Topaz via fal.ai.

    Args:
        image_path:       Local path to the source image.
        duration:         Desired duration in seconds.
        output_path:      Where to save the final .mp4.
        prompt:           Room description (used for space detection).
        camera_hint:      Camera movement preset key.
        model_endpoint:   fal.ai model string (default: Lyra 2.0).
        test_mode:        Downloads a sample video instead of calling API.
        do_video_upscale: Run Topaz upscale after generation (default True).

    Returns:
        True on success, False on failure.
    """
    if not os.path.exists(image_path):
        log.error(f"[VideoGen] Image not found: {image_path}")
        return False

    try:
        if test_mode:
            sample = "https://v3b.fal.media/files/b/0a8866f6/dmGBclH_CBmaku8J31ZE8_output.mp4"
            log.info("[VideoGen] test_mode=True — downloading sample.")
            return download_video(sample, output_path)

        log.info(f"[VideoGen] Uploading: {image_path}")
        image_url = fal_client.upload_file(image_path)

        # ── Try Lyra 2.0 at 720p ──────────────────────────────────────────
        lyra_path = output_path.replace(".mp4", "_720p.mp4")
        lyra_ok   = False

        try:
            lyra_args = _build_lyra_args(image_url, prompt, camera_hint, duration)
            result    = fal_client.subscribe(LYRA_ENDPOINT, arguments=lyra_args)
            video_url = (result.get("video") or {}).get("url")

            if not video_url:
                raise ValueError(f"No video URL returned: {result}")

            log.info("[VideoGen] ✓ Lyra succeeded at 720p — downloading...")
            if download_video(video_url, lyra_path):
                lyra_ok = True
                log.info(f"[VideoGen] model_used=lyra-2-720p")
            else:
                raise ValueError("Lyra download failed")

        except Exception as lyra_err:
            log.warning(f"[VideoGen] Lyra failed: {lyra_err} — falling back to LTX")

        # ── LTX-2.3 fallback ──────────────────────────────────────────────
        if not lyra_ok:
            ltx_result = fal_client.subscribe(
                LTX_ENDPOINT,
                arguments={
                    "image_url": image_url,
                    "prompt":    _LTX_PROMPT,
                    "duration":  _snap_ltx(duration),
                }
            )
            ltx_url = (ltx_result.get("video") or {}).get("url")
            if not ltx_url:
                log.error(f"[VideoGen] LTX fallback no URL: {ltx_result}")
                return False

            log.info("[VideoGen] ✓ LTX fallback succeeded — downloading...")
            if download_video(ltx_url, lyra_path):
                log.warning("[VideoGen] model_used=ltx-fallback — FLAGGED FOR QC")
            else:
                return False

        # ── Topaz video upscale ───────────────────────────────────────────
        if do_video_upscale:
            log.info(f"[VideoGen] Running Topaz upscale on clip...")
            upscale_ok = upscale_video(lyra_path, output_path, scale=2.0)
            if upscale_ok:
                # Remove the intermediate 720p file to save disk space
                try:
                    os.remove(lyra_path)
                except Exception:
                    pass
                log.info(f"[VideoGen] ✓ Final clip at 1080p: {output_path}")
                return True
            else:
                # Upscale failed — use 720p clip as fallback
                log.warning("[VideoGen] Topaz upscale failed — using 720p clip as fallback")
                import shutil
                shutil.move(lyra_path, output_path)
                return True
        else:
            # No upscale requested — move 720p clip to final output path
            import shutil
            shutil.move(lyra_path, output_path)
            log.info(f"[VideoGen] ✓ Final clip at 720p (upscale off): {output_path}")
            return True

    except Exception as e:
        log.error(f"[VideoGen] Complete failure: {e}", exc_info=True)
        return False


# ── Batch wrapper ──────────────────────────────────────────────────────────────

def mass_generation(
    image_dict:       dict,
    output_dir:       str,
    duration:         int  = 8,
    model_endpoint:   str  = LYRA_ENDPOINT,
    test_mode:        bool = False,
    do_video_upscale: bool = True,
) -> dict:
    if not os.environ.get("FAL_KEY"):
        log.critical("[VideoGen] FAL_KEY not set.")
        return {}
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    for image_path, meta in image_dict.items():
        hint   = meta.get("hint",   "") if isinstance(meta, dict) else str(meta)
        camera = meta.get("camera", "auto") if isinstance(meta, dict) else "auto"
        base   = os.path.splitext(os.path.basename(image_path))[0]
        out    = os.path.join(output_dir, f"{base}_video.mp4")
        ok     = generate_video_single(
            image_path, duration, out, hint, camera,
            do_video_upscale=do_video_upscale
        )
        results[image_path] = out if ok else None
    return results


# ── Download helper ────────────────────────────────────────────────────────────

def download_video(url, output_path):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        log.info(f"[VideoGen] Saved: {output_path}")
        return True
    except Exception as e:
        log.error(f"[VideoGen] Download failed: {e}")
        return False


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python video_generation.py <image.jpg> <output.mp4> [caption] [camera] [--no-upscale]")
        sys.exit(1)
    no_upscale = "--no-upscale" in sys.argv
    ok = generate_video_single(
        sys.argv[1], 8, sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else "",
        sys.argv[4] if len(sys.argv) > 4 else "auto",
        do_video_upscale=not no_upscale,
    )
    sys.exit(0 if ok else 1)
