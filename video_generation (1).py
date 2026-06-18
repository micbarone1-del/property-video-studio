"""
video_generation.py  (real-estate edition v7 — POV immersive engine)
──────────────────────────────────────────────────────────────────────
Architecture:
  Eco tier:       Lyra 2.0 zoom  — 720p + Topaz upscale to 1080p
  Standard tier:  Kling 2.5 Turbo Pro — native 1080p, no upscale needed
  Premium tier:   Veo 3.1 Fast — native 1080p, best prompt adherence

Prompt system:
  Zero free text — all prompts assembled from structured token dictionaries
  POV immersive language — visitor walking through the property
  Space type + movement auto-suggested by Florence-2, user-overridable
  Crop-and-reveal pre-processing for walk-in movements (85% centre crop)
  Property-level: lighting + motion intensity
  Per-scene: space type + POV movement

Future hook:
  include_person=False parameter ready — when True routes to Kling 2.6 Pro
  with character consistency token (reviewed separately)
"""

import os
import io
import logging
import requests
import fal_client
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Model endpoints ────────────────────────────────────────────────────────────
LYRA_ENDPOINT   = "fal-ai/lyra-2/zoom"
KLING_ENDPOINT  = "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"
VEO_ENDPOINT    = "fal-ai/veo3.1/image-to-video"       # fast mode via param
TOPAZ_ENDPOINT  = "fal-ai/topaz/upscale/video"
LTX_ENDPOINT    = "fal-ai/ltx-2.3/image-to-video/fast" # emergency fallback only

# ── Model tier mapping ─────────────────────────────────────────────────────────
MODEL_TIERS = {
    "eco":      LYRA_ENDPOINT,
    "standard": KLING_ENDPOINT,
    "premium":  VEO_ENDPOINT,
}

# ── Lyra frame mapping ─────────────────────────────────────────────────────────
_LYRA_FRAMES = {
    6: 81, 7: 81, 8: 81,
    9: 161, 10: 161, 11: 161, 12: 161,
    13: 161, 14: 161, 15: 161,
    16: 241, 17: 241, 18: 241, 19: 241, 20: 241,
}

# ── Space type detection (Italian + English) ───────────────────────────────────
_ELEVATED_KW  = [
    "balcony","terrace","loggia","rooftop","roof terrace",
    "balcone","terrazza","terrazzo","lastrico","tetto","roof garden",
]
_OUTDOOR_KW   = [
    "garden","pool","driveway","facade","courtyard","exterior","outdoor",
    "patio","backyard","front yard",
    "giardino","piscina","vialetto","facciata","cortile","esterno",
    "esterni","retro","fronte","entrata esterna",
]
_SMALLROOM_KW = [
    "bathroom","wc","toilet","ensuite","cloakroom","hallway","corridor",
    "laundry","utility","closet","pantry","storage",
    "bagno","toilette","antibagno","corridoio","lavanderia","ripostiglio",
    "dispensa","cabina armadio","sgabuzzino","disimpegno","ingresso",
]
_BEDROOM_KW   = [
    "bedroom","master bedroom","guest room","master suite","kids room","nursery",
    "camera","camera da letto","camera matrimoniale","camera singola",
    "camera doppia","camera degli ospiti","cameretta","suite padronale",
]
_CORRIDOR_KW  = [
    "corridor","hallway","entrance hall","foyer",
    "corridoio","disimpegno","ingresso","atrio",
]

def _detect_space(hint: str) -> str:
    h = hint.lower()
    if any(k in h for k in _ELEVATED_KW):  return "elevated"
    if any(k in h for k in _OUTDOOR_KW):   return "outdoor"
    if any(k in h for k in _CORRIDOR_KW):  return "corridor"
    if any(k in h for k in _SMALLROOM_KW): return "small"
    if any(k in h for k in _BEDROOM_KW):   return "bedroom"
    return "large"


# ── POV movement suggestions per space type ────────────────────────────────────
# Used by Florence-2 auto-suggest AND as fallback when camera_hint="auto"
SPACE_DEFAULT_MOVEMENT = {
    "large":    "walk_in_explore",
    "medium":   "walk_in_explore",
    "bedroom":  "walk_in_gentle",
    "small":    "approach_reveal",   # lateral tracking in Kling, approach in Veo
    "corridor": "walk_through",
    "outdoor":  "walk_toward",
    "elevated": "step_out_onto",
}

# ── Movements that use crop-and-reveal pre-processing ─────────────────────────
CROP_REVEAL_MOVEMENTS = {
    "walk_in_explore", "walk_in_gentle", "walk_in_turn_left",
    "walk_in_turn_right", "approach_reveal", "walk_toward",
    "stand_look_around", "subtle_rotate",
}


# ── Structured POV token dictionaries ─────────────────────────────────────────
# CRITICAL: Kling and Veo need completely different prompt languages.
# Kling image-to-video: MOTION ONLY — short, specific, no scene description.
#   Format: {camera_type} {direction} {endpoint}. {constraint}.
#   Max 3-4 elements. Never redescribe what's in the image.
# Veo image-to-video: Full narrative POV description works well.
# Lyra: Frozen-scene description — it's a zoom model not a motion model.


# ── KLING-specific motion tokens ───────────────────────────────────────────────
# These replace the verbose POV narrative for Kling.
# Each token is: camera type + direction + endpoint + stability note.

_KLING_MOTION = {
    # Large interior movements
    "walk_in_explore":    "Slow tracking push-in from the doorway toward the far wall, then settles. Camera level, no shake.",
    "walk_in_gentle":     "Gentle slow push-in, camera drifts slightly right to reveal the room, settles at centre. Level horizon.",
    "walk_in_turn_left":  "Push-in from entrance, camera pivots slowly left to reveal the room width, settles. Level.",
    "walk_in_turn_right": "Push-in from entrance, camera pivots slowly right to reveal the room width, settles. Level.",
    "walk_through":       "Slow tracking shot moving steadily forward through the space, camera level, settles at far end.",
    "stand_look_around":  "Slow pan left to right across the full room, camera stationary, settles back to centre.",
    # Small room / constrained space movements
    "approach_reveal":    "Slow lateral tracking shot moving left to right parallel to the main wall, reveals the full space. Camera level, no zoom.",
    # Exterior movements
    "walk_toward":        "Slow push-in toward the building facade, camera rises slightly, settles. Level horizon throughout.",
    "step_out_onto":      "Slow pan across the outdoor space left to right, camera stationary, settles. No zoom.",
}

# Kling intensity modifier (appended to motion token)
_KLING_INTENSITY = {
    "very_slow":    "Very slow speed.",
    "natural_pace": "Moderate slow speed.",
    "energetic":    "Confident smooth speed.",
}

# Kling anti-hallucination (minimal — Kling reads short prompts better)
_KLING_RULES = "No people. Camera stays within the visible scene. No new elements added."


# ── VEO-specific POV narrative tokens ─────────────────────────────────────────
# Veo follows longer narrative prompts accurately.

_VEO_SPACE_TOKENS = {
    "large":    "Stepping into a bright spacious living area",
    "medium":   "Entering a well-proportioned room",
    "bedroom":  "Walking gently into a private bedroom",
    "small":    "Moving carefully through a compact space",
    "corridor": "Walking along the entrance corridor",
    "outdoor":  "Walking toward the property from outside",
    "elevated": "Stepping out onto an elevated outdoor space",
}

# ── VEO-specific POV movement tokens — pace integrated ────────────────────────
# CRITICAL LESSONS FROM TESTING:
# - Push-forward on shallow rooms = 2D zoom. Use lateral or diagonal instead.
# - Separate intensity token is unreliable — Veo interprets pace relative to movement type.
# - Solution: embed pace directly in the movement token as a speed qualifier.
# - All movements include explicit frame boundary constraint.

# Movement tokens are now 3D dictionaries: [movement][intensity]
# This gives Veo a single coherent instruction rather than two separate signals.

_VEO_MOVEMENT_TOKENS = {

    # Large rooms — diagonal push creates parallax even without strong depth
    "walk_in_explore": {
        "very_slow":    "extremely slow diagonal push-in from the doorway drifting slightly right, revealing the room width gradually, camera stays within visible frame",
        "natural_pace": "slow diagonal push-in from the doorway drifting slightly right, revealing the full room as the camera advances, stays within visible frame",
        "energetic":    "confident diagonal push-in from the doorway angling slightly right, brisk reveal of the full room width, stays within visible frame",
    },

    # Bedrooms — lateral tracking always works regardless of depth
    "walk_in_gentle": {
        "very_slow":    "very slow lateral tracking shot moving left to right across the room, camera at eye level, strictly within the visible frame width, no push-forward",
        "natural_pace": "slow lateral tracking shot moving left to right across the room, steady eye-level movement, strictly within visible frame width",
        "energetic":    "smooth lateral tracking shot moving left to right across the room at a confident pace, eye level, within visible frame",
    },

    # Pivot reveals — for rooms with strong features on one side
    "walk_in_turn_left": {
        "very_slow":    "very slow pan strictly from right to left — maximum 30 degrees total rotation, camera must not move beyond the leftmost edge of the original image, no new content generated",
        "natural_pace": "slow pan from right to left — maximum 30 degrees total, strictly within original image left boundary, no content beyond original frame",
        "energetic":    "smooth pan from right to left — maximum 30 degrees, contained strictly within original image boundaries",
    },
    "walk_in_turn_right": {
        "very_slow":    "very slow pan strictly from left to right — maximum 30 degrees total rotation, camera must not move beyond the rightmost edge of the original image, no new content generated",
        "natural_pace": "slow pan from left to right — maximum 30 degrees total, strictly within original image right boundary, no content beyond original frame",
        "energetic":    "smooth pan from left to right — maximum 30 degrees, contained strictly within original image boundaries",
    },

    # Corridors — forward movement is the only natural option
    "walk_through": {
        "very_slow":    "very slow steady push forward along the corridor, camera level, stops before reaching far wall, no lateral movement",
        "natural_pace": "slow steady forward tracking along the corridor, eye level, stops before far wall",
        "energetic":    "confident forward tracking along the corridor, purposeful pace, eye level",
    },

    # Small rooms — lateral works; avoid forward push
    "approach_reveal": {
        "very_slow":    "very slow lateral tracking shot parallel to the main wall, left to right, camera within the visible frame, no zoom, no forward push",
        "natural_pace": "slow lateral tracking shot parallel to the main wall, steady left to right, within visible frame boundaries, no zoom",
        "energetic":    "smooth lateral tracking shot parallel to the main wall, left to right at a gentle pace, within frame",
    },

    # Stand and look — hard cap at 30 degrees to prevent hallucination
    "stand_look_around": {
        "very_slow":    "extremely slow partial pan — maximum 30 degrees total, camera starts and ends within the original image frame, strictly no rotation beyond original image edges, no new rooms or areas generated",
        "natural_pace": "slow partial pan — maximum 30 degrees total, strictly within original image boundaries, camera never reveals content outside the source photo",
        "energetic":    "smooth partial pan — maximum 30 degrees, strictly within original image boundaries, no new content beyond frame edges",
    },

    # Exterior — approaching the building
    "walk_toward": {
        "very_slow":    "very slow push-in toward the building facade, camera level, stays within visible facade frame, no lateral drift",
        "natural_pace": "slow push-in toward the building, steady approach, camera level, within visible frame",
        "energetic":    "confident push-in toward the building, purposeful approach pace, camera level",
    },

    # Balcony/terrace — slow pan, never push outward
    "step_out_onto": {
        "very_slow":    "very slow partial pan across the outdoor space — maximum 60 degrees, strictly within the width visible in original image, no rotation beyond edges, no push outward",
        "natural_pace": "slow partial pan across the outdoor space — maximum 60 degrees, within original image width, no outward push",
        "energetic":    "smooth partial pan across the outdoor space — maximum 60 degrees, within original frame",
    },

    # Subtle rotate — maximum 15 degrees, works in any space including small rooms
    # Use when walk_in_turn fails in shallow spaces
    "subtle_rotate": {
        "very_slow":    "extremely subtle rotation of maximum 15 degrees from centre, camera otherwise completely stationary, no zoom, no forward movement",
        "natural_pace": "very subtle rotation of maximum 15 degrees from centre, camera stationary, no zoom, no push",
        "energetic":    "subtle 15-degree rotation from centre, camera fixed position, no zoom",
    },
}

_VEO_LIGHTING_TOKENS = {
    "bright_natural":   "bright natural daylight, consistent and even, no flickering",
    "golden_hour":      "warm late-afternoon golden light, soft shadows, consistent",
    "overcast_soft":    "soft diffused overcast light, even and flattering",
    "evening_interior": "warm interior lighting, lamps and overhead lights on, evening atmosphere",
    "mixed_day":        "natural window light contrasting with warm interior ambient light",
}

_VEO_INTENSITY_TOKENS = {
    "very_slow":    "extremely slow and deliberate, appreciating every detail",
    "natural_pace": "natural comfortable walking pace",
    "energetic":    "confident and purposeful, excited about the space",
}

_VEO_RULES = (
    "No people, no human hands, arms, legs, fingers, or body parts visible in any frame. "
    "No wind effects on any surface. "
    "All architectural elements remain exactly as in the source image. "
    "Camera movement is strictly constrained within the boundaries of the original image — "
    "do not generate or reveal any content that was not visible in the source photo. "
    "Maximum rotation angle is 30 degrees in any direction. "
    "No rotation beyond the edges of the original frame under any circumstances. "
    "No new rooms, doors, windows, or spaces may be revealed that were not in the source photo. "
    "No flickering, no morphing of walls or floors."
)

# Lyra frozen-scene prompt (lighting only — Lyra controls camera via parameters)
_LYRA_SCENE = (
    "A high-end real estate interior. "
    "The scene is a completely frozen tableau — every surface, fixture, and element "
    "is perfectly still and motionless. {lighting}. "
    "No people, no wind, no movement of any kind. "
    "Cinema-grade HDR colour grading, 4K texture clarity."
)

_LYRA_LIGHTING = {
    "bright_natural":   "Bright natural daylight, fixed and consistent",
    "golden_hour":      "Warm golden-hour light, fixed, soft shadows",
    "overcast_soft":    "Soft diffused overcast light, even illumination",
    "evening_interior": "Warm interior lighting, stable and realistic",
    "mixed_day":        "Natural window light with warm interior ambient",
}


def assemble_pov_prompt(
    space_type:   str,
    pov_movement: str,
    lighting:     str,
    intensity:    str,
    model_tier:   str,
) -> str:
    """
    Assembles a model-specific prompt from structured token dictionaries.
    Kling: short precise motion-only instructions (3-4 elements max)
    Veo:   full POV narrative (follows longer prompts accurately)
    Lyra:  frozen-scene description (camera controlled via API parameters)
    """
    if model_tier == "eco":
        # Lyra — frozen scene, camera via parameters
        light = _LYRA_LIGHTING.get(lighting, _LYRA_LIGHTING["bright_natural"])
        return _LYRA_SCENE.format(lighting=light)

    elif model_tier == "premium":
        # Veo — pace integrated into movement token for consistency

        # Small room remapping: pivot movements don't work in shallow spaces
        # Remap to lateral tracking which works regardless of depth
        _SMALL_ROOM_REMAPS = {
            "walk_in_turn_left":  "approach_reveal",
            "walk_in_turn_right": "approach_reveal",
            "walk_in_explore":    "approach_reveal",
            "walk_in_gentle":     "approach_reveal",
        }
        if space_type in ("small", "corridor") and pov_movement in _SMALL_ROOM_REMAPS:
            original_movement = pov_movement
            pov_movement = _SMALL_ROOM_REMAPS[pov_movement]
            log.info(f"[VideoGen] Small room remap: {original_movement} → {pov_movement}")
        space    = _VEO_SPACE_TOKENS.get(space_type, _VEO_SPACE_TOKENS["large"])
        # Get movement with intensity baked in
        movement_dict = _VEO_MOVEMENT_TOKENS.get(pov_movement, _VEO_MOVEMENT_TOKENS["walk_in_explore"])
        if isinstance(movement_dict, dict):
            movement = movement_dict.get(intensity, movement_dict.get("natural_pace", ""))
        else:
            movement = movement_dict  # backward compat
        light    = _VEO_LIGHTING_TOKENS.get(lighting, _VEO_LIGHTING_TOKENS["bright_natural"])
        prompt   = (
            f"First-person POV shot: {space}. "
            f"Camera: {movement}. "
            f"Lighting: {light}. "
            f"{_VEO_RULES}"
        )
        log.info(f"[VideoGen] Veo FULL prompt: {prompt}")
        return prompt

    else:
        # Kling — short precise motion instructions ONLY
        # Do NOT describe the scene — Kling sees the image directly
        motion    = _KLING_MOTION.get(pov_movement, _KLING_MOTION["walk_in_explore"])
        pace      = _KLING_INTENSITY.get(intensity, _KLING_INTENSITY["natural_pace"])
        prompt    = f"{motion} {pace} {_KLING_RULES}"
        log.info(f"[VideoGen] Kling prompt: {prompt}")
        return prompt


# ── Crop-and-reveal pre-processing ────────────────────────────────────────────

def _crop_for_reveal(image_path: str, crop_pct: float = 0.85) -> bytes:
    """
    Crops the image to a central subset before sending to the model.
    The model starts from the tighter crop and reveals outward —
    since it only knows the cropped region, it cannot hallucinate
    content beyond the original image boundaries.

    Returns the cropped image as JPEG bytes.
    Falls back to original image bytes on any error.
    """
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        left   = int(w * (1 - crop_pct) / 2)
        top    = int(h * (1 - crop_pct) / 2)
        right  = w - left
        bottom = h - top
        cropped = img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=92)
        log.info(f"[VideoGen] Crop-and-reveal: {w}×{h} → {right-left}×{bottom-top}")
        return buf.getvalue()
    except Exception as e:
        log.warning(f"[VideoGen] Crop failed ({e}) — using full image")
        with open(image_path, "rb") as f:
            return f.read()


def _upload_bytes(data: bytes, filename: str = "image.jpg") -> str:
    """Uploads raw bytes to fal.ai and returns the URL."""
    import tempfile
    tmp = tempfile.mktemp(suffix=".jpg")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        return fal_client.upload_file(tmp)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


# ── Kling 2.5 Turbo Pro generation ────────────────────────────────────────────

def _generate_kling(image_url: str, prompt: str, duration: int) -> str | None:
    """Submits to Kling 2.5 Turbo Pro. Returns video URL or None.
    Kling only accepts duration '5' or '10' — snap to nearest valid value.
    """
    kling_dur = "5" if duration <= 7 else "10"
    try:
        log.info(f"[VideoGen] Kling 2.5 Turbo Pro — {kling_dur}s (requested {duration}s)")
        result = fal_client.subscribe(
            KLING_ENDPOINT,
            arguments={
                "image_url":    image_url,
                "prompt":       prompt,
                "duration":     kling_dur,
                "aspect_ratio": "16:9",
                "mode":         "pro",
            }
        )
        return (result.get("video") or {}).get("url")
    except Exception as e:
        log.error(f"[VideoGen] Kling failed: {e}")
        return None


# ── Veo 3.1 Fast generation ───────────────────────────────────────────────────

def _generate_veo(image_url: str, prompt: str, duration: int) -> str | None:
    """Submits to Veo 3.1 Fast. Returns video URL or None."""
    try:
        log.info(f"[VideoGen] Veo 3.1 Fast — {duration}s")
        result = fal_client.subscribe(
            VEO_ENDPOINT,
            arguments={
                "image_url":     image_url,
                "prompt":        prompt,
                "duration_secs": duration,
                "enhance_prompt": False,   # we control the prompt, no AI rewriting
                "generate_audio": False,   # ElevenLabs handles audio separately
                "fast_mode":     True,
            }
        )
        return (result.get("video") or {}).get("url")
    except Exception as e:
        log.error(f"[VideoGen] Veo failed: {e}")
        return None


# ── Lyra 2.0 generation (Eco tier) ────────────────────────────────────────────

def _generate_lyra(image_url: str, prompt: str, duration: int,
                   space_type: str, pov_movement: str) -> str | None:
    """Submits to Lyra 2.0 zoom. Returns video URL or None."""
    # Lyra uses its own camera parameters alongside the prompt
    _LYRA_FRAMES_MAP = {
        6: 81, 7: 81, 8: 81,
        9: 161, 10: 161, 11: 161, 12: 161,
        13: 161, 14: 161, 15: 161,
        16: 241, 17: 241, 18: 241, 19: 241, 20: 241,
    }
    _LYRA_MOTION = {
        "large":    {"zoom_direction":"in","zoom_in_trajectory":"horizontal_zoom_bend","zoom_in_strength":0.28},
        "bedroom":  {"zoom_direction":"in","zoom_in_trajectory":"horizontal_zoom","zoom_in_strength":0.20},
        "small":    {"zoom_direction":"in","zoom_in_trajectory":"horizontal_zoom","zoom_in_strength":0.13},
        "corridor": {"zoom_direction":"in","zoom_in_trajectory":"horizontal_zoom","zoom_in_strength":0.15},
        "outdoor":  {"zoom_direction":"in","zoom_in_trajectory":"orbit_horizontal","zoom_in_strength":0.25},
        "elevated": {"zoom_direction":"in","zoom_in_trajectory":"horizontal_zoom","zoom_in_strength":0.10},
    }
    motion = _LYRA_MOTION.get(space_type, _LYRA_MOTION["large"])
    try:
        log.info(f"[VideoGen] Lyra 2.0 Eco — {duration}s space={space_type}")
        result = fal_client.subscribe(
            LYRA_ENDPOINT,
            arguments={
                "image_url":          image_url,
                "prompt":             prompt,
                "zoom_direction":     motion["zoom_direction"],
                "zoom_in_trajectory": motion["zoom_in_trajectory"],
                "zoom_in_strength":   motion["zoom_in_strength"],
                "num_frames":         _LYRA_FRAMES_MAP.get(duration, 81),
                "resolution":         "720p",
                "use_dmd":            True,
                "frames_per_second":  16,
                "guidance_scale":     5,
            }
        )
        return (result.get("video") or {}).get("url")
    except Exception as e:
        log.error(f"[VideoGen] Lyra failed: {e}")
        return None


# ── Topaz video upscale (Eco tier only) ───────────────────────────────────────

def _upscale_video(video_path: str, output_path: str) -> bool:
    """Upscales a 720p clip to 1080p via Topaz. Returns True on success."""
    try:
        log.info(f"[VideoGen] Topaz upscale: {video_path}")
        video_url = fal_client.upload_file(video_path)
        result = fal_client.subscribe(
            TOPAZ_ENDPOINT,
            arguments={
                "video_url":     video_url,
                "scale":         2.0,
                "model":         "Standard V2",
                "output_format": "mp4",
            }
        )
        url = (result.get("video") or {}).get("url")
        if not url:
            log.error(f"[VideoGen] Topaz returned no URL: {result}")
            return False
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        log.info(f"[VideoGen] Topaz upscale saved: {output_path}")
        return True
    except Exception as e:
        log.error(f"[VideoGen] Topaz failed: {e}")
        return False


# ── LTX emergency fallback ─────────────────────────────────────────────────────

_LTX_FALLBACK_PROMPT = (
    "Professional real estate interior. Slow steady camera push. "
    "No people, no wind, no hallucinated rooms. "
    "Level horizon, zero camera shake. HDR lighting."
)
_LTX_VALID = [6, 8, 10, 12, 14, 16, 18, 20]

def _snap_ltx(d):
    for v in _LTX_VALID:
        if v >= d: return v
    return _LTX_VALID[-1]


# ── Download helper ────────────────────────────────────────────────────────────

def download_video(url: str, output_path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        r = requests.get(url, stream=True, timeout=180)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        log.info(f"[VideoGen] Saved: {output_path}")
        return True
    except Exception as e:
        log.error(f"[VideoGen] Download failed: {e}")
        return False


# ── Main generation function ───────────────────────────────────────────────────

def generate_video_single(
    image_path:     str,
    duration:       int,
    output_path:    str,
    # Structured prompt parameters (no free text)
    space_type:     str  = "large",        # from Florence-2 or user dropdown
    pov_movement:   str  = "walk_in_explore", # from Florence-2 or user dropdown
    lighting:       str  = "bright_natural",  # property-level
    intensity:      str  = "natural_pace",    # property-level
    model_tier:     str  = "standard",        # eco / standard / premium
    # Legacy parameter kept for backward compatibility
    prompt:         str  = "",
    camera_hint:    str  = "auto",
    # Options
    do_video_upscale: bool = True,         # Eco: Topaz; Standard/Premium: ignored
    include_person: bool = False,          # future hook
    test_mode:      bool = False,
) -> bool:
    """
    Generates a single POV immersive video clip from a property photo.

    All video content is controlled by structured parameters — no free text.
    Model routing:
      eco      → Lyra 2.0 (720p) + Topaz upscale (1080p)
      standard → Kling 2.5 Turbo Pro (native 1080p)
      premium  → Veo 3.1 Fast (native 1080p, best realism)
    Falls back to LTX-2.3 if primary and secondary models fail.
    """
    if not os.path.exists(image_path):
        log.error(f"[VideoGen] Image not found: {image_path}")
        return False

    # Override space_type from legacy caption if structured params not provided
    if space_type == "large" and prompt:
        space_type = _detect_space(prompt)

    # Override pov_movement from camera_hint if structured params not provided
    if pov_movement == "walk_in_explore" and camera_hint != "auto":
        # Map old camera hints to new POV movements for backward compat
        _hint_map = {
            "gentle_arc":   "walk_in_explore",
            "straight_push":"walk_in_explore",
            "soft_orbit":   "stand_look_around",
            "minimal":      "step_out_onto",
            "spiral":       "walk_in_explore",
            "dolly_zoom":   "approach_reveal",
            "static":       "stand_look_around",
        }
        pov_movement = _hint_map.get(camera_hint, SPACE_DEFAULT_MOVEMENT.get(space_type, "walk_in_explore"))

    log.info(
        f"[VideoGen] tier={model_tier} space={space_type} "
        f"movement={pov_movement} lighting={lighting} intensity={intensity}"
    )

    try:
        if test_mode:
            sample = "https://v3b.fal.media/files/b/0a8866f6/dmGBclH_CBmaku8J31ZE8_output.mp4"
            return download_video(sample, output_path)

        # ── Assemble structured prompt ─────────────────────────────────────
        final_prompt = assemble_pov_prompt(
            space_type, pov_movement, lighting, intensity, model_tier
        )
        log.info(f"[VideoGen] Prompt: {final_prompt[:120]}...")

        # ── Crop-and-reveal pre-processing ────────────────────────────────
        # Tighter crop for rotation movements — gives model less room to hallucinate
        _ROTATION_MOVEMENTS = {"walk_in_turn_left","walk_in_turn_right","stand_look_around"}
        if pov_movement in _ROTATION_MOVEMENTS:
            image_data = _crop_for_reveal(image_path, crop_pct=0.75)  # tighter for rotation
        elif pov_movement in CROP_REVEAL_MOVEMENTS:
            image_data = _crop_for_reveal(image_path, crop_pct=0.85)  # standard for walk-in
        else:
            with open(image_path, "rb") as f:
                image_data = f.read()

        # Upload (cropped or full) image
        image_url = _upload_bytes(image_data)

        # ── Route to correct model ─────────────────────────────────────────
        video_url = None
        used_model = None

        if model_tier == "premium":
            video_url  = _generate_veo(image_url, final_prompt, duration)
            used_model = "veo-3.1-fast"
            if not video_url:
                log.warning("[VideoGen] Veo failed — falling back to Kling")
                video_url  = _generate_kling(image_url, final_prompt, duration)
                used_model = "kling-2.5-turbo-fallback"

        elif model_tier == "eco":
            raw_path = output_path.replace(".mp4", "_720p.mp4")
            video_url = _generate_lyra(image_url, final_prompt, duration, space_type, pov_movement)
            used_model = "lyra-2-eco"

        else:  # standard (Kling)
            video_url  = _generate_kling(image_url, final_prompt, duration)
            used_model = "kling-2.5-turbo"
            if not video_url:
                log.warning("[VideoGen] Kling failed — falling back to Veo")
                video_url  = _generate_veo(image_url, final_prompt, duration)
                used_model = "veo-3.1-fallback"

        # ── LTX emergency fallback ─────────────────────────────────────────
        if not video_url:
            log.warning("[VideoGen] Primary and secondary failed — LTX emergency fallback")
            result = fal_client.subscribe(
                LTX_ENDPOINT,
                arguments={
                    "image_url": image_url,
                    "prompt":    _LTX_FALLBACK_PROMPT,
                    "duration":  _snap_ltx(duration),
                }
            )
            video_url  = (result.get("video") or {}).get("url")
            used_model = "ltx-emergency"

        if not video_url:
            log.error("[VideoGen] All models failed")
            return False

        # ── Download generated clip ────────────────────────────────────────
        if model_tier == "eco" and do_video_upscale:
            # Download to temp path then Topaz upscale
            raw_path = output_path.replace(".mp4", "_720p.mp4")
            if not download_video(video_url, raw_path):
                return False
            ok = _upscale_video(raw_path, output_path)
            if not ok:
                log.warning("[VideoGen] Topaz failed — using 720p clip")
                import shutil
                shutil.move(raw_path, output_path)
            else:
                try: os.remove(raw_path)
                except: pass
        else:
            if not download_video(video_url, output_path):
                return False

        log.info(f"[VideoGen] ✓ model_used={used_model} output={output_path}")
        return True

    except Exception as e:
        log.error(f"[VideoGen] Complete failure: {e}", exc_info=True)
        return False


# ── Batch wrapper ──────────────────────────────────────────────────────────────

def mass_generation(
    image_dict:   dict,
    output_dir:   str,
    duration:     int  = 8,
    model_tier:   str  = "standard",
    lighting:     str  = "bright_natural",
    intensity:    str  = "natural_pace",
    test_mode:    bool = False,
) -> dict:
    """
    Batch generate. image_dict = {
      image_path: {
        "space_type": str,
        "pov_movement": str,
      }
    }
    """
    if not os.environ.get("FAL_KEY"):
        log.critical("[VideoGen] FAL_KEY not set.")
        return {}
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    for image_path, meta in image_dict.items():
        space    = meta.get("space_type",   "large") if isinstance(meta, dict) else "large"
        movement = meta.get("pov_movement", SPACE_DEFAULT_MOVEMENT.get(space, "walk_in_explore"))
        base     = os.path.splitext(os.path.basename(image_path))[0]
        out      = os.path.join(output_dir, f"{base}_video.mp4")
        ok       = generate_video_single(
            image_path, duration, out,
            space_type=space, pov_movement=movement,
            lighting=lighting, intensity=intensity,
            model_tier=model_tier, test_mode=test_mode,
        )
        results[image_path] = out if ok else None
    return results


if __name__ == "__main__":
    import sys, json
    logging.basicConfig(level=logging.INFO)

    # Print available options
    if "--list" in sys.argv:
        print("Space types:", list(SPACE_DEFAULT_MOVEMENT.keys()))
        print("POV movements:", list(_MOVEMENT_TOKENS.keys()))
        print("Lighting:", list(_LIGHTING_TOKENS.keys()))
        print("Intensity:", list(_INTENSITY_TOKENS.keys()))
        print("Model tiers: eco, standard, premium")
        sys.exit(0)

    if len(sys.argv) < 3:
        print("Usage: python video_generation.py <image.jpg> <output.mp4>")
        print("       [--space large|bedroom|small|corridor|outdoor|elevated]")
        print("       [--move walk_in_explore|walk_through|stand_look_around|...]")
        print("       [--light bright_natural|golden_hour|overcast_soft|evening_interior|mixed_day]")
        print("       [--pace very_slow|natural_pace|energetic]")
        print("       [--tier eco|standard|premium]")
        print("       [--list]")
        sys.exit(1)

    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("output")
    p.add_argument("--space",  default="large")
    p.add_argument("--move",   default=None)
    p.add_argument("--light",  default="bright_natural")
    p.add_argument("--pace",   default="natural_pace")
    p.add_argument("--tier",   default="standard")
    args = p.parse_args()

    movement = args.move or SPACE_DEFAULT_MOVEMENT.get(args.space, "walk_in_explore")
    ok = generate_video_single(
        args.image, 8, args.output,
        space_type=args.space, pov_movement=movement,
        lighting=args.light, intensity=args.pace,
        model_tier=args.tier,
    )
    sys.exit(0 if ok else 1)
