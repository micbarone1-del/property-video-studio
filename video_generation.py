"""
video_generation.py  (real-estate edition v4 — Lyra 2.0 optimised)
────────────────────────────────────────────────────────────────────
Changes in v4:
  - Combined camera movements using zoom_direction="both" (out then in)
  - Space-adaptive strength and trajectory:
      Large rooms: pull-back + orbital arc (depth-revealing)
      Small rooms: gentle arc push with low strength (avoids flat zoom)
      Exteriors:   wide back reveal + slow orbit
  - 9 predefined camera movement combinations in UI dropdown
  - zoom_out_trajectory and zoom_out_strength now used properly
  - Prompt rewritten per Lyra's own example: rich frozen-scene description
    drives better 3D reconstruction and reduces flat-zoom artefact
  - 720p resolution for quality mode when use_dmd=False (future option)
  - LTX-2.3 fallback unchanged
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
LTX_ENDPOINT  = "fal-ai/ltx-2.3/image-to-video/fast"

# ── Frame mapping (Lyra uses frames not seconds) ───────────────────────────────
# At 16fps: 81=~5s  161=~10s  241=~15s  321=~20s
_DURATION_TO_FRAMES = {
    6: 81, 7: 81, 8: 81,
    9: 161, 10: 161, 11: 161, 12: 161,
    13: 161, 14: 161, 15: 161, 16: 241,
    17: 241, 18: 241, 19: 241, 20: 241,
}

# ── Space type detection ───────────────────────────────────────────────────────
_OUTDOOR_KW   = ["exterior","garden","terrace","balcony","facade","outdoor","pool",
                  "courtyard","street","roof","driveway","entrance","patio","backyard"]
_SMALLROOM_KW = ["bathroom","wc","toilet","hallway","corridor","laundry","utility",
                  "cloakroom","ensuite","closet","pantry","storage","loo"]

def _detect_space(hint: str) -> str:
    h = hint.lower()
    if any(k in h for k in _OUTDOOR_KW):   return "outdoor"
    if any(k in h for k in _SMALLROOM_KW): return "small"
    return "large"


# ── Camera movement presets ────────────────────────────────────────────────────
# Each preset is a full Lyra parameter bundle.
# zoom_direction "both" = camera pulls out first, then pushes in.
# This is how Lyra achieves combined movements natively.

CAMERA_PRESETS = {

    # ── Auto presets (space-adaptive — set at runtime) ─────────────────────
    "auto": None,   # resolved at runtime based on space type

    # ── Single direction moves ─────────────────────────────────────────────
    "dolly_in": {
        "zoom_direction":      "in",
        "zoom_in_trajectory":  "horizontal_zoom",
        "zoom_in_strength":    0.55,
        "label": "Dolly in — straight push toward centre",
    },
    "orbit": {
        "zoom_direction":      "in",
        "zoom_in_trajectory":  "orbit_horizontal",
        "zoom_in_strength":    0.6,
        "label": "Orbit — arc around the space",
    },
    "spiral": {
        "zoom_direction":      "in",
        "zoom_in_trajectory":  "spiral",
        "zoom_in_strength":    0.5,
        "label": "Spiral approach — spiraling push in",
    },
    "dolly_zoom": {
        "zoom_direction":      "in",
        "zoom_in_trajectory":  "dolly_zoom",
        "zoom_in_strength":    0.5,
        "label": "Dolly zoom — Hitchcock / vertigo effect",
    },
    "pull_back": {
        "zoom_direction":      "out",
        "zoom_out_trajectory": "back",
        "zoom_out_strength":   1.0,
        "label": "Pull back — camera retreats to reveal space",
    },

    # ── Combined moves (zoom_direction="both") ─────────────────────────────
    "pullback_orbit": {
        "zoom_direction":      "both",
        "zoom_in_trajectory":  "orbit_horizontal",
        "zoom_in_strength":    0.55,
        "zoom_out_trajectory": "horizontal_zoom",
        "zoom_out_strength":   0.7,
        "label": "Pull back + orbit — retreat then arc in (cinematic)",
    },
    "pullback_dolly": {
        "zoom_direction":      "both",
        "zoom_in_trajectory":  "horizontal_zoom",
        "zoom_in_strength":    0.6,
        "zoom_out_trajectory": "horizontal_zoom",
        "zoom_out_strength":   0.6,
        "label": "Pull back + dolly — retreat then push in (classic)",
    },
    "wide_reveal_orbit": {
        "zoom_direction":      "both",
        "zoom_in_trajectory":  "orbit_horizontal",
        "zoom_in_strength":    0.5,
        "zoom_out_trajectory": "back",
        "zoom_out_strength":   1.2,
        "label": "Wide reveal + orbit — strong pull back then slow orbit",
    },
    "arc_push": {
        "zoom_direction":      "in",
        "zoom_in_trajectory":  "horizontal_zoom_bend",
        "zoom_in_strength":    0.35,
        "label": "Arc push — gentle push with slight arc (best for small rooms)",
    },
    "static": {
        "zoom_direction":      "in",
        "zoom_in_trajectory":  "horizontal_zoom",
        "zoom_in_strength":    0.08,
        "label": "Static — near-motionless, very subtle depth",
    },
}

# ── Auto presets resolved by space type ───────────────────────────────────────
_AUTO_LARGE = {
    "zoom_direction":      "both",
    "zoom_in_trajectory":  "orbit_horizontal",
    "zoom_in_strength":    0.55,
    "zoom_out_trajectory": "horizontal_zoom",
    "zoom_out_strength":   0.65,
}

_AUTO_SMALL = {
    "zoom_direction":      "in",
    "zoom_in_trajectory":  "horizontal_zoom_bend",
    "zoom_in_strength":    0.25,
}

_AUTO_OUTDOOR = {
    "zoom_direction":      "both",
    "zoom_in_trajectory":  "orbit_horizontal",
    "zoom_in_strength":    0.5,
    "zoom_out_trajectory": "back",
    "zoom_out_strength":   1.1,
}


# ── Lyra scene prompts ─────────────────────────────────────────────────────────
# Lyra's own docs show that rich frozen-scene descriptions produce better
# 3D reconstruction. The more the model "understands" the scene geometry,
# the more natural the camera movement. Keep everything FROZEN/MOTIONLESS.

_PROMPT_LARGE = (
    "A luxurious real estate interior bathed in natural light. "
    "The scene is a frozen tableau — every surface, piece of furniture, "
    "wall, ceiling, floor, and decorative element is perfectly still and motionless. "
    "The lighting is fixed and permanent. Shadows are static. "
    "No people, no wind effect, no door or window movement, no flickering. "
    "Rich architectural details, high-end finishes, and deep spatial depth "
    "are all clearly defined and motionless throughout every frame. "
    "Cinema-grade HDR colour grading, 4K texture clarity."
)

_PROMPT_SMALL = (
    "A high-end real estate interior — a carefully designed compact space. "
    "The scene is a frozen tableau — every fixture, surface, tile, fitting, "
    "and architectural element is perfectly still and motionless. "
    "The lighting is fixed. No movement of any kind in any element. "
    "No people, no steam, no reflections shifting, no door movement. "
    "Clean lines, precise geometry, and premium materials are all "
    "sharply defined and completely static throughout every frame. "
    "Cinema-grade HDR colour grading, 4K texture clarity."
)

_PROMPT_OUTDOOR = (
    "A stunning real estate exterior in perfect, still conditions. "
    "The scene is a frozen tableau — the architecture, landscaping, sky, "
    "paving, water features, and all natural elements are perfectly still. "
    "No wind effect on trees, plants, or grass. No moving clouds. "
    "No people, no vehicles, no flickering light. "
    "The building's geometry and materials are sharply defined and motionless "
    "with clear spatial depth between foreground and background. "
    "Cinema-grade HDR colour grading, 4K texture clarity, golden-hour lighting."
)

def _get_scene_prompt(space_type: str) -> str:
    if space_type == "outdoor": return _PROMPT_OUTDOOR
    if space_type == "small":   return _PROMPT_SMALL
    return _PROMPT_LARGE


# ── Build Lyra API arguments ───────────────────────────────────────────────────

def _build_lyra_args(
    image_url:   str,
    prompt:      str,
    camera_hint: str,
    duration:    int,
) -> dict:
    space_type   = _detect_space(prompt)
    scene_prompt = _get_scene_prompt(space_type)
    num_frames   = _DURATION_TO_FRAMES.get(duration, 81)

    # Resolve auto preset
    if camera_hint == "auto":
        if space_type == "outdoor":   motion = _AUTO_OUTDOOR
        elif space_type == "small":   motion = _AUTO_SMALL
        else:                         motion = _AUTO_LARGE
    else:
        motion = CAMERA_PRESETS.get(camera_hint, _AUTO_LARGE)

    log.info(
        f"[VideoGen] space={space_type} camera={camera_hint} "
        f"direction={motion.get('zoom_direction')} "
        f"in_traj={motion.get('zoom_in_trajectory','—')} "
        f"out_traj={motion.get('zoom_out_trajectory','—')} "
        f"frames={num_frames}"
    )

    args = {
        "image_url":         image_url,
        "prompt":            scene_prompt,
        "zoom_direction":    motion.get("zoom_direction", "in"),
        "num_frames":        num_frames,
        "resolution":        "480p",
        "use_dmd":           True,
        "frames_per_second": 16,
        "guidance_scale":    5,
    }

    # In-direction params
    if "zoom_in_trajectory" in motion:
        args["zoom_in_trajectory"] = motion["zoom_in_trajectory"]
    if "zoom_in_strength" in motion:
        args["zoom_in_strength"] = motion["zoom_in_strength"]

    # Out-direction params (only relevant when zoom_direction=both or out)
    if "zoom_out_trajectory" in motion:
        args["zoom_out_trajectory"] = motion["zoom_out_trajectory"]
    if "zoom_out_strength" in motion:
        args["zoom_out_strength"] = motion["zoom_out_strength"]

    return args


# ── LTX fallback prompt ────────────────────────────────────────────────────────
_LTX_FALLBACK_PROMPT = (
    "Professional real estate cinematography. "
    "Slow steady camera push revealing the space. "
    "No people, no wind, no door movement, no hallucinated rooms or fixtures. "
    "Level horizon, zero camera shake. "
    "HDR lighting, cinema-grade colour correction."
)

_LTX_VALID = [6, 8, 10, 12, 14, 16, 18, 20]

def _snap_ltx(d: int) -> int:
    for v in _LTX_VALID:
        if v >= d: return v
    return _LTX_VALID[-1]


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
    Generates a single video clip using Lyra 2.0 with combined camera movements.
    Falls back to LTX-2.3 automatically if Lyra fails.
    Returns True on success, False on failure.
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

        # ── Lyra 2.0 ──────────────────────────────────────────────────────
        try:
            lyra_args = _build_lyra_args(image_url, prompt, camera_hint, duration)
            result    = fal_client.subscribe(LYRA_ENDPOINT, arguments=lyra_args)
            video_url = (result.get("video") or {}).get("url")

            if not video_url:
                raise ValueError(f"No video URL returned: {result}")

            log.info("[VideoGen] ✓ Lyra succeeded — downloading...")
            if download_video(video_url, output_path):
                log.info(f"[VideoGen] model_used=lyra-2 output={output_path}")
                return True
            raise ValueError("Download failed after Lyra success")

        except Exception as lyra_err:
            log.warning(f"[VideoGen] Lyra failed: {lyra_err} — falling back to LTX-2.3")

        # ── LTX-2.3 fallback ──────────────────────────────────────────────
        ltx_result = fal_client.subscribe(
            LTX_ENDPOINT,
            arguments={
                "image_url": image_url,
                "prompt":    _LTX_FALLBACK_PROMPT,
                "duration":  _snap_ltx(duration),
            }
        )
        video_url = (ltx_result.get("video") or {}).get("url")
        if not video_url:
            log.error(f"[VideoGen] LTX fallback returned no URL: {ltx_result}")
            return False

        log.info("[VideoGen] ✓ LTX fallback succeeded — downloading...")
        if download_video(video_url, output_path):
            log.warning(f"[VideoGen] model_used=ltx-fallback — FLAGGED FOR QC REVIEW")
            return True
        return False

    except Exception as e:
        log.error(f"[VideoGen] Complete failure for {image_path}: {e}", exc_info=True)
        return False


def mass_generation(
    image_dict:     dict,
    output_dir:     str,
    duration:       int  = 8,
    model_endpoint: str  = LYRA_ENDPOINT,
    test_mode:      bool = False,
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
        ok     = generate_video_single(image_path, duration, out, hint, camera)
        results[image_path] = out if ok else None
    return results


def download_video(url: str, output_path: str) -> bool:
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
        print("Usage: python video_generation.py <image.jpg> <output.mp4> [caption] [camera_hint]")
        sys.exit(1)
    ok = generate_video_single(sys.argv[1], 8, sys.argv[2],
                                sys.argv[3] if len(sys.argv)>3 else "",
                                sys.argv[4] if len(sys.argv)>4 else "auto")
    sys.exit(0 if ok else 1)
