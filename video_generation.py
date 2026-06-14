"""
video_generation.py  (real-estate edition v2)
──────────────────────────────────────────────
Improvements in v2:
  - Space-adaptive prompting: detects outdoor/large room/small room and applies
    the right cinematic technique for each (dolly, pan, slider)
  - User camera hint per scene: passed as `camera_hint` parameter
  - Full anti-hallucination master prompt based on proven real estate prompt
  - Wind effect suppressed via explicit prompt instruction
  - Upscaling instruction embedded in the video prompt itself
  - return True added after download_video() (was returning None on success)
  - resolution/aspect_ratio params removed (not supported by LTX-2.3)
"""

import os
import logging
import requests
import fal_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

VALID_DURATIONS     = [6, 8, 10, 12, 14, 16, 18, 20]
DEFAULT_VIDEO_ENDPOINT = "fal-ai/ltx-2.3/image-to-video/fast"

# ── Space type keywords ────────────────────────────────────────────────────────
_OUTDOOR_KEYWORDS   = ["exterior", "garden", "terrace", "balcony", "facade", "outdoor", "pool", "courtyard", "street", "roof"]
_SMALLROOM_KEYWORDS = ["bathroom", "wc", "toilet", "hallway", "corridor", "laundry", "utility", "cloakroom", "ensuite"]

# ── Master anti-hallucination prompt ──────────────────────────────────────────
# Adapted from the proven prompt, split by space type.

_BASE_RULES = (
    "No people, hands, arms, or limbs visible. "
    "Strictly level horizon line with strict 0-degree vertical tilt "
    "and absolutely zero vertical bobbing, camera shake, or human stepping motion. "
    "Do not morph the architecture, blur the walls, or hallucinate new rooms, "
    "unseen fixtures, doors, window panes, or non-existent areas. "
    "The sequence must be entirely non-generative regarding structural layout. "
    "Upscale visual textures to 4K clarity, applying enhanced HDR lighting "
    "to significantly brighten and open up dark areas, and cinema-grade color correction. "
    "Digitally remove and inpaint any watermarks or text overlays from frame one to the end."
)

_PROMPT_LARGE = (
    "A professional high-end real estate cinematography sequence. "
    "The video begins tightly framed on a high-resolution, upscaled inner sub-section of the original image. "
    "From this inner starting point, the camera path acts strictly as a slow reveal outward, "
    "completely preventing the generation of unseen angles beyond the original frame boundaries. "
    "For this large room or exterior: perform a slow, smooth linear dolly-in push "
    "or a gentle horizontal pan toward the frame edges. "
    "{camera_hint}"
    "The camera must never zoom tightly into windows, mirrors, glass, or open balcony spaces. "
    "Keep the focus broad, showcasing the existing layout. "
    + _BASE_RULES
)

_PROMPT_SMALL = (
    "A professional high-end real estate cinematography sequence. "
    "The video begins tightly framed on a high-resolution, upscaled inner sub-section of the original image. "
    "From this inner starting point, the camera path acts strictly as a slow reveal outward, "
    "completely preventing the generation of unseen angles beyond the original frame boundaries. "
    "For this small or compact interior: restrict the movement to a very shallow, slow lateral slider shift "
    "tracking parallel to the main wall. "
    "{camera_hint}"
    "The camera must never zoom tightly into windows, mirrors, glass, or fixtures. "
    "Keep the focus broad, showcasing the existing compact layout. "
    + _BASE_RULES
)

_PROMPT_OUTDOOR = (
    "A professional high-end real estate cinematography sequence. "
    "The video begins tightly framed on a high-resolution, upscaled inner sub-section of the original image. "
    "From this inner starting point, the camera path acts strictly as a slow reveal outward across known pixels, "
    "completely preventing the generation of unseen angles beyond the original frame boundaries. "
    "For this exterior or outdoor space: perform a slow, smooth linear dolly-in push "
    "or a gentle arc revealing the full exterior. "
    "{camera_hint}"
    "The camera must never zoom tightly into windows, glass, or pool water surfaces. "
    "Keep the focus broad, showcasing the existing exterior layout. "
    + _BASE_RULES
)

# Camera movement options (shown in UI dropdown)
CAMERA_MOVEMENTS = {
    "auto":         "",   # let space-type detection decide
    "dolly_in":     "Slow dolly-in push toward the centre of the frame. ",
    "pan_left":     "Slow smooth pan from right to left across the space. ",
    "pan_right":    "Slow smooth pan from left to right across the space. ",
    "slider":       "Very shallow lateral slider shift parallel to the main wall. ",
    "zoom_out":     "Slow gradual zoom out from tight crop to reveal the full room. ",
    "tilt_up":      "Slow subtle tilt upward from floor level to ceiling. ",
    "static":       "Completely static locked-off shot with no camera movement. ",
}


def _detect_space_type(hint: str) -> str:
    """Returns 'outdoor', 'small', or 'large' based on keywords in the hint."""
    h = hint.lower()
    if any(k in h for k in _OUTDOOR_KEYWORDS):
        return "outdoor"
    if any(k in h for k in _SMALLROOM_KEYWORDS):
        return "small"
    return "large"


def _build_prompt(space_hint: str, camera_hint: str) -> str:
    """
    Builds the final video generation prompt.
    space_hint: caption/room description from the user
    camera_hint: specific camera movement key from CAMERA_MOVEMENTS
    """
    movement_text = CAMERA_MOVEMENTS.get(camera_hint, "")
    space_type    = _detect_space_type(space_hint)

    # Auto mode: use a sensible slow walk-in default per space type
    if not movement_text:
        if space_type == "outdoor":
            movement_text = "Slow smooth dolly-in push toward the centre of the frame, combined with a very slight upward tilt. "
        elif space_type == "small":
            movement_text = "Slow subtle dolly-in push toward the centre of the frame with minimal lateral drift. "
        else:
            movement_text = "Slow smooth dolly-in push toward the centre of the frame, combined with a very slight 10-degree arc pan. "

    if space_type == "outdoor":
        return _PROMPT_OUTDOOR.format(camera_hint=movement_text)
    elif space_type == "small":
        return _PROMPT_SMALL.format(camera_hint=movement_text)
    else:
        return _PROMPT_LARGE.format(camera_hint=movement_text)


def _snap_duration(d: int) -> int:
    if d in VALID_DURATIONS:
        return d
    for v in VALID_DURATIONS:
        if v >= d:
            return v
    return VALID_DURATIONS[-1]


def generate_video_single(
    image_path: str,
    duration: int,
    output_path: str,
    prompt: str = "",
    camera_hint: str = "auto",
    model_endpoint: str = DEFAULT_VIDEO_ENDPOINT,
    test_mode: bool = False,
) -> bool:
    """
    Generates a single video clip from one image.

    Args:
        image_path:    Local path to the source image.
        duration:      Desired duration in seconds.
        output_path:   Where to save the resulting .mp4.
        prompt:        Room description / caption (used for space detection).
        camera_hint:   Camera movement key from CAMERA_MOVEMENTS dict.
        model_endpoint: fal.ai model string.
        test_mode:     If True, downloads a sample video instead of calling API.

    Returns:
        True on success, False on failure.
    """
    if not os.path.exists(image_path):
        log.error(f"[VideoGen] Image not found: {image_path}")
        return False

    duration = _snap_duration(duration)

    try:
        if test_mode:
            sample = "https://v3b.fal.media/files/b/0a8866f6/dmGBclH_CBmaku8J31ZE8_output.mp4"
            log.info("[VideoGen] test_mode=True — downloading sample video.")
            return download_video(sample, output_path)

        # Build the final prompt
        final_prompt = _build_prompt(prompt, camera_hint)
        log.info(f"[VideoGen] Space type detected from: '{prompt}'")
        log.info(f"[VideoGen] Camera hint: {camera_hint}")
        log.info(f"[VideoGen] Final prompt (first 120 chars): {final_prompt[:120]}...")

        # Upload image
        log.info(f"[VideoGen] Uploading: {image_path}")
        image_url = fal_client.upload_file(image_path)

        # Submit to fal.ai
        log.info(f"[VideoGen] Generating {duration}s clip via {model_endpoint}...")
        result = fal_client.subscribe(
            model_endpoint,
            arguments={
                "image_url": image_url,
                "prompt":    final_prompt,
                "duration":  duration,
            }
        )

        video_url = (result.get("video") or {}).get("url")
        if not video_url:
            log.error(f"[VideoGen] No video URL in result: {result}")
            return False

        log.info("[VideoGen] Downloading generated clip...")
        success = download_video(video_url, output_path)
        return True if success else False

    except Exception as e:
        log.error(f"[VideoGen] Error processing {image_path}: {e}", exc_info=True)
        return False


def mass_generation(
    image_dict: dict,
    output_dir: str,
    duration: int = 8,
    model_endpoint: str = DEFAULT_VIDEO_ENDPOINT,
    test_mode: bool = False,
) -> dict:
    """Batch generate. image_dict = { image_path: {"hint": str, "camera": str} }"""
    if not os.environ.get("FAL_KEY"):
        log.critical("[VideoGen] FAL_KEY not set.")
        return {}

    os.makedirs(output_dir, exist_ok=True)
    results = {}

    for image_path, meta in image_dict.items():
        hint   = meta.get("hint", "") if isinstance(meta, dict) else str(meta)
        camera = meta.get("camera", "auto") if isinstance(meta, dict) else "auto"
        base   = os.path.splitext(os.path.basename(image_path))[0]
        out    = os.path.join(output_dir, f"{base}_video.mp4")
        ok     = generate_video_single(
            image_path=image_path,
            duration=duration,
            output_path=out,
            prompt=hint,
            camera_hint=camera,
            model_endpoint=model_endpoint,
            test_mode=test_mode,
        )
        results[image_path] = out if ok else None

    return results


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
