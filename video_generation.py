"""
video_generation.py  (real-estate edition v3)
──────────────────────────────────────────────
v3 changes:
- 3D walk-in + rotation prompts
- No objects moving rules
- Space-adaptive rotation caps
"""

import os
import logging
import requests
import fal_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

VALID_DURATIONS        = [6, 8, 10, 12, 14, 16, 18, 20]
DEFAULT_VIDEO_ENDPOINT = "fal-ai/ltx-2.3/image-to-video/fast"

_OUTDOOR_KEYWORDS  = ["exterior", "garden", "terrace", "balcony", "facade",
                       "outdoor", "pool", "courtyard", "street", "roof"]
_SMALLROOM_KEYWORDS = ["bathroom", "wc", "toilet", "hallway", "corridor",
                        "laundry", "utility", "cloakroom", "ensuite"]

_BASE_RULES = (
    "STRICT RULES: "
    "No people, no human figures, no hands, no arms, no limbs, no animals at any point. "
    "STATIC OBJECTS: Every object in the scene must remain completely stationary throughout. "
    "No doors opening or closing. No windows opening. No fans, curtains, or fabrics moving. "
    "No water rippling. No plants swaying. No lights flickering. Zero wind effects. "
    "The camera is the ONLY thing that moves — everything else is frozen still. "
    "GEOMETRY LOCK: Do not generate, invent, or reveal any room, corridor, door, window, fixture, "
    "or architectural element that is not clearly visible in the original still image. "
    "Do not morph, distort, blur, or warp existing walls, floors, or ceilings. "
    "The structural geometry must remain 100 percent faithful to the source image. "
    "HORIZON LOCK: Camera horizon must remain perfectly level with exactly 0 degrees of vertical tilt. "
    "Zero vertical bobbing. Zero camera shake. Zero stepping motion. "
    "POST-PROCESSING: Apply 4K upscaling, enhanced HDR lighting to brighten dark areas, "
    "and cinema-grade color grading. Remove and inpaint any visible watermarks or text overlays."
)

_PROMPT_LARGE = (
    "Professional high-end real estate cinematography sequence. "
    "Large interior space. "
    "CAMERA MOVEMENT - 3D WALK-IN WITH HORIZONTAL ARC: "
    "The camera begins at the near edge of the room and performs a slow, smooth forward dolly-in, "
    "physically moving deeper into the space as if a person is walking slowly into the room. "
    "Simultaneously the camera rotates horizontally no more than 30 degrees in a single direction "
    "(left or right arc), sweeping to reveal the width of the space. "
    "This combined forward push plus horizontal arc creates genuine three-dimensional parallax: "
    "nearby furniture grows larger and shifts sideways while the far wall slowly approaches. "
    "{camera_hint}"
    "The movement is slow, smooth, and cinematic — the entire arc takes the full clip duration. "
    "FORBIDDEN camera targets: do not point the lens toward windows, mirrors, glass surfaces, "
    "or open balcony openings at any point in the arc. "
    "Keep the lens aimed at solid walls, ceilings, and furnishings. "
    "Stay strictly within the boundaries of the original visible frame. "
    + _BASE_RULES
)

_PROMPT_SMALL = (
    "Professional high-end real estate cinematography sequence. "
    "Small or compact interior space (bathroom, hallway, utility room). "
    "CAMERA MOVEMENT - SLOW FORWARD CREEP WITH MICRO LATERAL DRIFT: "
    "The camera performs a very slow, shallow forward push deeper into the space, "
    "combined with an extremely subtle lateral drift of no more than 10 degrees. "
    "This gentle combined motion creates a quiet three-dimensional parallax in a confined space "
    "without revealing any unseen geometry beyond the original frame. "
    "{camera_hint}"
    "Movement is extremely restrained and slow to avoid generating hallucinations in tight spaces. "
    "FORBIDDEN camera targets: do not move toward or zoom into mirrors, glass, taps, "
    "or shiny fixtures. Keep the lens aimed at tiled walls and main solid surfaces. "
    "Stay within the visible frame. "
    + _BASE_RULES
)

_PROMPT_OUTDOOR = (
    "Professional high-end real estate cinematography sequence. "
    "Exterior or outdoor space (facade, garden, terrace, pool area). "
    "CAMERA MOVEMENT - SLOW ARC FLYBY WITH 3D DEPTH: "
    "The camera performs a slow smooth horizontal arc up to 40 degrees, "
    "combined with a gentle forward push toward the building or main subject. "
    "This arc-dolly combination creates strong three-dimensional depth separation: "
    "foreground landscaping slides past in one direction while the building facade fills the frame. "
    "{camera_hint}"
    "The movement is elegant and unhurried, covering the full arc over the entire clip duration. "
    "FORBIDDEN camera targets: do not point the lens toward windows, glazed doors, pool water surfaces, "
    "or glass balustrades. Keep the lens focused on solid architectural elements. "
    "Stay strictly within the visible original frame boundaries. "
    + _BASE_RULES
)

CAMERA_MOVEMENTS = {
    "auto":       "",
    "dolly_in":   "Camera move: slow forward dolly-in push toward the centre of the room. ",
    "pan_left":   "Camera move: slow smooth pan from right to left across the space. ",
    "pan_right":  "Camera move: slow smooth pan from left to right across the space. ",
    "slider":     "Camera move: very shallow lateral slider shift parallel to the main wall. ",
    "zoom_out":   "Camera move: slow gradual zoom out from tight crop to reveal the full room. ",
    "tilt_up":    "Camera move: slow subtle tilt upward from floor level to ceiling. ",
    "static":     "Camera move: completely static locked-off shot with zero camera movement. ",
}


def _detect_space_type(hint: str) -> str:
    """Returns outdoor, small, or large based on keywords in the hint."""
    h = hint.lower()
    if any(k in h for k in _OUTDOOR_KEYWORDS):
        return "outdoor"
    if any(k in h for k in _SMALLROOM_KEYWORDS):
        return "small"
    return "large"


def _build_prompt(space_hint: str, camera_hint: str) -> str:
    """Builds the final video generation prompt."""
    movement_text = CAMERA_MOVEMENTS.get(camera_hint, "")
    space_type = _detect_space_type(space_hint)
    if space_type == "outdoor":
        template = _PROMPT_OUTDOOR
    elif space_type == "small":
        template = _PROMPT_SMALL
    else:
        template = _PROMPT_LARGE
    return template.format(camera_hint=movement_text)


# ── fal.ai helpers ─────────────────────────────────────────────────────────────

def _fal_image_url(image_path: str) -> str:
    """Upload a local image to fal.ai storage and return its CDN URL."""
    with open(image_path, "rb") as f:
        url = fal_client.upload(f, content_type="image/jpeg")
    return url


def generate_video(
    image_path: str,
    output_path: str,
    space_hint: str  = "living room",
    camera_hint: str = "auto",
    duration: int    = 8,
    endpoint: str    = DEFAULT_VIDEO_ENDPOINT,
) -> bool:
    """Generate a short video clip from a still image using fal.ai LTX-2.3."""
    if duration not in VALID_DURATIONS:
        log.warning("Duration %s not in VALID_DURATIONS; clamping to 8.", duration)
        duration = 8

    prompt = _build_prompt(space_hint, camera_hint)
    log.info("[VideoGen] space=%s camera=%s duration=%s", space_hint, camera_hint, duration)
    log.info("[VideoGen] prompt=%.200s", prompt)

    try:
        image_url = _fal_image_url(image_path)
        log.info("[VideoGen] image uploaded -> %s", image_url)
    except Exception as exc:
        log.error("[VideoGen] image upload failed: %s", exc)
        return False

    payload = {
        "prompt":              prompt,
        "image_url":           image_url,
        "num_frames":          duration * 8,
        "guidance_scale":      3.5,
        "num_inference_steps": 30,
    }

    try:
        log.info("[VideoGen] submitting to %s ...", endpoint)
        result = fal_client.run(endpoint, arguments=payload)
        log.info("[VideoGen] fal.ai result keys: %s", list(result.keys()) if isinstance(result, dict) else type(result))
    except Exception as exc:
        log.error("[VideoGen] fal.ai call failed: %s", exc)
        return False

    video_url = None
    if isinstance(result, dict):
        if "video" in result:
            v = result["video"]
            video_url = v.get("url") if isinstance(v, dict) else v
        elif "videos" in result and result["videos"]:
            v = result["videos"][0]
            video_url = v.get("url") if isinstance(v, dict) else v
        elif "url" in result:
            video_url = result["url"]

    if not video_url:
        log.error("[VideoGen] no video URL in result: %s", result)
        return False

    return download_video(video_url, output_path)


def download_video(url: str, output_path: str) -> bool:
    """Download a video from a URL to a local file path."""
    try:
        log.info("[VideoGen] downloading from %s ...", url)
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info("[VideoGen] saved to %s", output_path)
        return True
    except Exception as exc:
        log.error("[VideoGen] download failed: %s", exc)
        return False
