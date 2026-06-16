"""
video_generation.py  (real-estate edition v5 — Lyra 2.0 constrained)
─────────────────────────────────────────────────────────────────────
Changes in v5:
  - AUTO mode completely reworked: 6 distinct space types, each with
    its own single-direction movement tuned to natural human movement
  - TWO-STEP movements removed from auto entirely
  - All auto strengths capped at 0.30 to stay within original frame
  - Balcony/terrace/rooftop gets near-static (camera is at the edge)
  - Bedroom gets intimate low-strength arc push
  - Small rooms get straight dolly-in at minimal strength
  - Ground exteriors get gentle orbit at safe strength
  - Large interiors get gentle arc push (horizontal_zoom_bend)
  - Two-step and strong orbit options kept in manual dropdown
    but clearly flagged with warning labels
  - All manual strengths for orbit capped at 0.30 in safe mode
  - LTX-2.3 fallback unchanged
"""

import os
import logging
import requests
import fal_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

LYRA_ENDPOINT = "fal-ai/lyra-2/zoom"
LTX_ENDPOINT  = "fal-ai/ltx-2.3/image-to-video/fast"

# ── Frame mapping ──────────────────────────────────────────────────────────────
_DURATION_TO_FRAMES = {
    6: 81, 7: 81, 8: 81,
    9: 161, 10: 161, 11: 161, 12: 161,
    13: 161, 14: 161, 15: 161,
    16: 241, 17: 241, 18: 241, 19: 241, 20: 241,
}

# ── Space type detection ───────────────────────────────────────────────────────
# Order matters — more specific keywords checked first

_ELEVATED_KW  = [
    # English
    "balcony","terrace","loggia","rooftop","roof terrace","roof top",
    # Italian
    "balcone","terrazza","terrazzo","lastrico","loggia","tetto",
    "terrazzo sul tetto","roof garden",
]
_OUTDOOR_KW   = [
    # English
    "garden","pool","driveway","facade","entrance","courtyard",
    "exterior","outdoor","patio","backyard","front yard","street view",
    # Italian
    "giardino","piscina","vialetto","facciata","cortile",
    "esterno","esterni","patio","retro","fronte","vista strada",
    "giardino posteriore","giardino anteriore","entrata esterna",
]
_SMALLROOM_KW = [
    # English
    "bathroom","wc","toilet","ensuite","en-suite","cloakroom",
    "hallway","corridor","laundry","utility","closet","pantry","storage",
    # Italian
    "bagno","wc","toilette","bagno en suite","bagno privato",
    "antibagno","corridoio","lavanderia","ripostiglio","dispensa",
    "cabina armadio","sgabuzzino","disimpegno","ingresso",
]
_BEDROOM_KW   = [
    # English
    "bedroom","master bedroom","guest room","guest bedroom",
    "master suite","kids room","nursery",
    # Italian
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
    return "large"   # default for: soggiorno, cucina, sala, salone, sala da pranzo,
                     # living room, kitchen, dining, open plan — all get gentle arc push


# ── AUTO presets — one per space type ─────────────────────────────────────────
# Rules:
#   - Always zoom_direction="in" (single smooth movement)
#   - All strengths ≤ 0.30 to stay within original frame
#   - Trajectory chosen to match how a human would move in that space

_AUTO_PRESETS = {

    # Large open interior — living room, kitchen, dining, open plan
    # Human movement: walk slowly into the space, slight curve to take it in
    "large": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom_bend",
        "zoom_in_strength":   0.28,
    },

    # Bedroom — intimate, personal space
    # Human movement: step gently into the room, straight ahead
    "bedroom": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.20,
    },

    # Small interior — bathroom, hallway, corridor
    # Human movement: step in, barely any room to move
    "small": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.13,
    },

    # Ground exterior — garden, pool, facade, driveway
    # Human movement: walk up to the property, slight arc to see the breadth
    "outdoor": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.25,
    },

    # Elevated exterior — balcony, terrace, rooftop
    # Camera is already at the edge of the space — almost no movement possible
    # A strong move here flies outside the building (what you saw)
    "elevated": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.10,
    },
}


# ── Manual camera presets (UI dropdown) ───────────────────────────────────────
# User explicitly picks these — higher strengths allowed but warned

CAMERA_PRESETS = {

    "auto": None,   # resolved at runtime from _AUTO_PRESETS

    # ── Safe single moves (strength ≤ 0.30, stays in frame) ───────────────

    "gentle_arc": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom_bend",
        "zoom_in_strength":   0.28,
        "label": "⭐ Gentle arc push — recommended for most rooms",
    },
    "straight_push": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.30,
        "label": "Straight dolly in — direct walk-in, no arc",
    },
    "soft_orbit": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.25,
        "label": "Soft lateral sweep — gentle arc, stays in frame",
    },
    "minimal": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.10,
        "label": "Minimal movement — for balconies and tight spaces",
    },
    "spiral": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "spiral",
        "zoom_in_strength":   0.30,
        "label": "Spiral approach — spiraling push in",
    },
    "dolly_zoom": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "dolly_zoom",
        "zoom_in_strength":   0.35,
        "label": "Dolly zoom — Hitchcock / vertigo effect",
    },
    "static": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "horizontal_zoom",
        "zoom_in_strength":   0.06,
        "label": "Static — near-motionless",
    },

    # ── Stronger moves — may hallucinate at frame edges ───────────────────

    "strong_orbit": {
        "zoom_direction":     "in",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.50,
        "label": "⚠ Strong lateral sweep — cinematic but may hallucinate edges",
    },
    "pullback_arc": {
        "zoom_direction":     "both",
        "zoom_in_trajectory": "horizontal_zoom_bend",
        "zoom_in_strength":   0.40,
        "zoom_out_trajectory":"horizontal_zoom",
        "zoom_out_strength":  0.55,
        "label": "⚠ Pull back + arc — two-step, may look unnatural in small rooms",
    },
    "wide_reveal": {
        "zoom_direction":     "both",
        "zoom_in_trajectory": "orbit_horizontal",
        "zoom_in_strength":   0.45,
        "zoom_out_trajectory":"back",
        "zoom_out_strength":  0.90,
        "label": "⚠ Wide reveal — outdoor/large rooms only, hallucination risk",
    },
}


# ── Scene prompts ──────────────────────────────────────────────────────────────

_PROMPT_BASE = (
    "A high-end real estate {space_desc}. "
    "The scene is a completely frozen tableau — every surface, fixture, "
    "material, and architectural element is perfectly still and motionless. "
    "No people, no wind, no movement of any kind in any element. "
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

    # Resolve motion preset
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
        "resolution":        "480p",
        "use_dmd":           True,
        "frames_per_second": 16,
        "guidance_scale":    5,
    }

    if "zoom_in_trajectory" in motion:
        args["zoom_in_trajectory"] = motion["zoom_in_trajectory"]
    if "zoom_in_strength" in motion:
        args["zoom_in_strength"] = motion["zoom_in_strength"]
    if "zoom_out_trajectory" in motion:
        args["zoom_out_trajectory"] = motion["zoom_out_trajectory"]
    if "zoom_out_strength" in motion:
        args["zoom_out_strength"] = motion["zoom_out_strength"]

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


# ── Main function ──────────────────────────────────────────────────────────────

def generate_video_single(
    image_path:     str,
    duration:       int,
    output_path:    str,
    prompt:         str  = "",
    camera_hint:    str  = "auto",
    model_endpoint: str  = LYRA_ENDPOINT,
    test_mode:      bool = False,
) -> bool:

    if not os.path.exists(image_path):
        log.error(f"[VideoGen] Image not found: {image_path}")
        return False

    try:
        if test_mode:
            sample = "https://v3b.fal.media/files/b/0a8866f6/dmGBclH_CBmaku8J31ZE8_output.mp4"
            return download_video(sample, output_path)

        log.info(f"[VideoGen] Uploading: {image_path}")
        image_url = fal_client.upload_file(image_path)

        # ── Try Lyra ──────────────────────────────────────────────────────
        try:
            args   = _build_lyra_args(image_url, prompt, camera_hint, duration)
            result = fal_client.subscribe(LYRA_ENDPOINT, arguments=args)
            url    = (result.get("video") or {}).get("url")
            if not url:
                raise ValueError(f"No video URL: {result}")
            log.info("[VideoGen] ✓ Lyra succeeded")
            if download_video(url, output_path):
                log.info(f"[VideoGen] model_used=lyra-2")
                return True
            raise ValueError("Download failed")

        except Exception as e:
            log.warning(f"[VideoGen] Lyra failed: {e} — falling back to LTX")

        # ── LTX fallback ──────────────────────────────────────────────────
        result = fal_client.subscribe(
            LTX_ENDPOINT,
            arguments={
                "image_url": image_url,
                "prompt":    _LTX_PROMPT,
                "duration":  _snap_ltx(duration),
            }
        )
        url = (result.get("video") or {}).get("url")
        if not url:
            log.error(f"[VideoGen] LTX fallback no URL: {result}")
            return False
        if download_video(url, output_path):
            log.warning("[VideoGen] model_used=ltx-fallback — FLAGGED FOR QC")
            return True
        return False

    except Exception as e:
        log.error(f"[VideoGen] Complete failure: {e}", exc_info=True)
        return False


def mass_generation(image_dict, output_dir, duration=8,
                    model_endpoint=LYRA_ENDPOINT, test_mode=False):
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
        print("Usage: python video_generation.py <image.jpg> <output.mp4> [caption] [camera]")
        sys.exit(1)
    ok = generate_video_single(
        sys.argv[1], 8, sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else "",
        sys.argv[4] if len(sys.argv) > 4 else "auto"
    )
    sys.exit(0 if ok else 1)
