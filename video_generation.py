"""
video_generation.py  (real-estate edition v3 — Lyra 2.0)
──────────────────────────────────────────────────────────
Changes in v3:
  - PRIMARY model switched to fal-ai/lyra-2/zoom (true 3D camera movement)
  - Camera movement now passed as a PARAMETER (zoom_in_trajectory) not a prompt
  - Lyra uses num_frames not duration — mapping table included
  - Prompt rewritten for Lyra: camera-path language, not restriction language
  - LTX-2.3 kept as automatic fallback if Lyra fails
  - model_used logged in result so QC can flag LTX fallback clips
  - Portrait output (720x1280) from Lyra — assembly will handle aspect ratio
"""

import os
import logging
import requests
import fal_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Model endpoints ────────────────────────────────────────────────────────────
LYRA_ENDPOINT = "fal-ai/lyra-2/zoom"
LTX_ENDPOINT  = "fal-ai/ltx-2.3/image-to-video/fast"   # fallback only

# ── Lyra frame mapping ─────────────────────────────────────────────────────────
# Lyra uses num_frames not seconds. At 16fps:
#   81 frames  = ~5s
#   161 frames = ~10s
#   241 frames = ~15s
# We map requested duration to nearest valid frame count.
_DURATION_TO_FRAMES = {
    6:  81,
    8:  81,
    10: 161,
    12: 161,
    14: 161,
    16: 241,
    18: 241,
    20: 241,
}

# ── Lyra trajectory mapping ────────────────────────────────────────────────────
# camera_hint from UI dropdown → Lyra zoom_in_trajectory parameter
# These are GUARANTEED by the model architecture, not just prompt suggestions.
_CAMERA_TO_TRAJECTORY = {
    "auto":      "orbit_horizontal",   # best general-purpose for rooms
    "dolly_in":  "horizontal_zoom",    # straight push toward centre
    "pan_left":  "orbit_horizontal",   # Lyra orbits; closest to pan
    "pan_right": "orbit_horizontal",
    "slider":    "horizontal_zoom_bend", # slight arc — good for small rooms
    "zoom_out":  "horizontal_zoom",    # we set zoom_direction=out below
    "tilt_up":   "spiral",             # spiraling approach gives vertical reveal
    "static":    "horizontal_zoom",    # minimal strength = near-static
    "orbit":     "orbit_horizontal",   # explicit orbit for exteriors
}

# ── Space type detection ───────────────────────────────────────────────────────
_OUTDOOR_KEYWORDS   = ["exterior","garden","terrace","balcony","facade","outdoor","pool","courtyard","street","roof","driveway","entrance"]
_SMALLROOM_KEYWORDS = ["bathroom","wc","toilet","hallway","corridor","laundry","utility","cloakroom","ensuite","closet","pantry"]

def _detect_space_type(hint: str) -> str:
    h = hint.lower()
    if any(k in h for k in _OUTDOOR_KEYWORDS):   return "outdoor"
    if any(k in h for k in _SMALLROOM_KEYWORDS): return "small"
    return "large"

# ── Lyra prompts ───────────────────────────────────────────────────────────────
# Lyra is a camera-control model. The prompt describes the SCENE STATE,
# not the camera. Camera movement is controlled by the trajectory parameter.
# Key rule: describe everything as FROZEN/STILL — this prevents hallucinations.

_LYRA_PROMPT_LARGE = (
    "Professional real estate interior. "
    "Camera at human eye level, approximately 1.6m height, moving forward slowly "
    "as if a person is walking into and exploring the space. "
    "All objects, furniture, doors, windows, curtains, and fixtures are completely "
    "motionless — only the camera moves along a ground-level path. "
    "No floating, no aerial angle, no objects moving. "
    "Smooth dolly-forward motion. HDR lighting, cinema colour, 4K detail."
)

_LYRA_PROMPT_SMALL = (
    "Professional real estate interior — a compact space. "
    "Camera at human eye level, approximately 1.6m height, making a short step "
    "forward then a slow gentle pan, as a person naturally surveys a small room. "
    "All surfaces, fixtures and fittings are completely motionless — only the camera "
    "moves along a short, ground-level path. "
    "No floating, no aerial angle, no objects moving. "
    "Smooth movement, no shake. HDR lighting, cinema colour, 4K detail."
)

_LYRA_PROMPT_OUTDOOR = (
    "Professional real estate exterior. "
    "Camera at human eye level, approximately 1.6m height, moving slowly forward "
    "or along the facade at a natural walking pace, as if approaching the property. "
    "All architectural surfaces, landscaping, and sky are completely motionless — "
    "only the camera moves along a ground-level path. "
    "No floating, no aerial angle, no wind, no plants or trees moving. "
    "Smooth arc or dolly movement. HDR lighting, cinema colour, 4K detail."
)

def _build_lyra_args(
    image_url: str,
    prompt: str,
    camera_hint: str,
    duration: int,
) -> dict:
    """
    Builds the complete argument dict for the Lyra 2.0 API call.
    Camera movement is controlled via trajectory parameters, not the prompt.
    """
    space_type = _detect_space_type(prompt)

    if space_type == "outdoor":
        scene_prompt = _LYRA_PROMPT_OUTDOOR
    elif space_type == "small":
        scene_prompt = _LYRA_PROMPT_SMALL
    else:
        scene_prompt = _LYRA_PROMPT_LARGE

    trajectory = _CAMERA_TO_TRAJECTORY.get(camera_hint, "orbit_horizontal")
    num_frames  = _DURATION_TO_FRAMES.get(duration, 81)

    # zoom_out hint: reverse the direction
    zoom_direction = "out" if camera_hint == "zoom_out" else "in"

    # For "auto" camera: pick trajectory based on space type for natural movement
    # Large/small interiors → forward dolly (horizontal_zoom) = person walking in
    # Outdoor → orbit (arc around facade) = person approaching
    if camera_hint == "auto":
        if space_type == "outdoor":
            trajectory = "orbit_horizontal"
        else:
            trajectory = "horizontal_zoom"

    # Strength: 0.55 normal, 0.15 static — enough for visible 3D movement
    strength = 0.15 if camera_hint == "static" else 0.55

    return {
        "image_url":          image_url,
        "prompt":             scene_prompt,
        "zoom_direction":     zoom_direction,
        "zoom_in_trajectory": trajectory,
        "zoom_in_strength":   strength,
        "num_frames":         num_frames,
        "resolution":         "480p",    # 480x832 portrait — fast and cost-efficient
        "use_dmd":            True,      # fast mode — 4-step scheduler
        "frames_per_second":  16,
        "guidance_scale":     5,
    }

# ── LTX fallback prompt ────────────────────────────────────────────────────────
_LTX_FALLBACK_PROMPT = (
    "Professional real estate cinematography. "
    "Slow steady camera push revealing the space. "
    "No people, no wind, no door movement, no hallucinated rooms or fixtures. "
    "Level horizon, zero camera shake. "
    "HDR lighting, cinema-grade colour correction."
)

# ── Duration snapping for LTX fallback ────────────────────────────────────────
_LTX_VALID_DURATIONS = [6, 8, 10, 12, 14, 16, 18, 20]

def _snap_duration(d: int) -> int:
    if d in _LTX_VALID_DURATIONS:
        return d
    for v in _LTX_VALID_DURATIONS:
        if v >= d:
            return v
    return _LTX_VALID_DURATIONS[-1]


# ── Main generation function ───────────────────────────────────────────────────

def generate_video_single(
    image_path:     str,
    duration:       int,
    output_path:    str,
    prompt:         str  = "",
    camera_hint:    str  = "auto",
    model_endpoint: str  = LYRA_ENDPOINT,
    test_mode:      bool = False,
) -> bool:
    """
    Generates a single video clip from one image using Lyra 2.0.
    Falls back to LTX-2.3 automatically if Lyra fails.

    Returns True on success, False on failure.
    Logs which model was actually used so QC can flag LTX fallbacks.
    """
    if not os.path.exists(image_path):
        log.error(f"[VideoGen] Image not found: {image_path}")
        return False

    try:
        if test_mode:
            sample = "https://v3b.fal.media/files/b/0a8866f6/dmGBclH_CBmaku8J31ZE8_output.mp4"
            log.info("[VideoGen] test_mode=True — downloading sample video.")
            return download_video(sample, output_path)

        # Upload image once — used by both Lyra and LTX if needed
        log.info(f"[VideoGen] Uploading image: {image_path}")
        image_url = fal_client.upload_file(image_path)

        # ── Try Lyra 2.0 first ─────────────────────────────────────────────
        log.info(f"[VideoGen] Trying Lyra 2.0 | camera={camera_hint} | space={_detect_space_type(prompt)}")
        try:
            lyra_args = _build_lyra_args(image_url, prompt, camera_hint, duration)
            log.info(f"[VideoGen] Lyra args: trajectory={lyra_args['zoom_in_trajectory']} frames={lyra_args['num_frames']} direction={lyra_args['zoom_direction']}")

            result = fal_client.subscribe(
                LYRA_ENDPOINT,
                arguments=lyra_args
            )

            video_url = (result.get("video") or {}).get("url")
            if not video_url:
                raise ValueError(f"Lyra returned no video URL. Result: {result}")

            log.info(f"[VideoGen] ✓ Lyra succeeded — downloading...")
            success = download_video(video_url, output_path)
            if success:
                log.info(f"[VideoGen] model_used=lyra-2 output={output_path}")
                return True
            raise ValueError("Lyra video download failed")

        except Exception as lyra_err:
            log.warning(f"[VideoGen] Lyra failed: {lyra_err} — falling back to LTX-2.3")

        # ── LTX-2.3 fallback ──────────────────────────────────────────────
        log.info(f"[VideoGen] Using LTX-2.3 fallback | duration={_snap_duration(duration)}s")
        ltx_result = fal_client.subscribe(
            LTX_ENDPOINT,
            arguments={
                "image_url": image_url,
                "prompt":    _LTX_FALLBACK_PROMPT,
                "duration":  _snap_duration(duration),
            }
        )

        video_url = (ltx_result.get("video") or {}).get("url")
        if not video_url:
            log.error(f"[VideoGen] LTX fallback also returned no URL: {ltx_result}")
            return False

        log.info(f"[VideoGen] ✓ LTX fallback succeeded — downloading...")
        success = download_video(video_url, output_path)
        if success:
            log.warning(f"[VideoGen] model_used=ltx-fallback output={output_path} — FLAGGED FOR QC REVIEW")
        return success

    except Exception as e:
        log.error(f"[VideoGen] Complete failure for {image_path}: {e}", exc_info=True)
        return False


# ── Batch wrapper ──────────────────────────────────────────────────────────────

def mass_generation(
    image_dict:     dict,
    output_dir:     str,
    duration:       int  = 8,
    model_endpoint: str  = LYRA_ENDPOINT,
    test_mode:      bool = False,
) -> dict:
    """Batch generate. image_dict = { image_path: {"hint": str, "camera": str} }"""
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
            image_path=image_path,
            duration=duration,
            output_path=out,
            prompt=hint,
            camera_hint=camera,
            test_mode=test_mode,
        )
        results[image_path] = out if ok else None

    return results


# ── Download helper ────────────────────────────────────────────────────────────

def download_video(url: str, output_path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info(f"[VideoGen] Saved: {output_path}")
        return True
    except Exception as e:
        log.error(f"[VideoGen] Download failed: {e}")
        return False


# ── CLI quick test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python video_generation.py <image.jpg> <output.mp4> [caption] [camera_hint]")
        sys.exit(1)
    hint   = sys.argv[3] if len(sys.argv) > 3 else ""
    camera = sys.argv[4] if len(sys.argv) > 4 else "auto"
    ok = generate_video_single(sys.argv[1], 8, sys.argv[2], hint, camera)
    sys.exit(0 if ok else 1)
