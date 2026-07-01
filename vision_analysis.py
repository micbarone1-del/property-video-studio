"""
vision_analysis.py
──────────────────
Dual-purpose vision AI module using Florence-2 Large via fal.ai:

  1. INPUT ANALYSIS  — analyses a property photo on upload
     Returns: space_type, depth, recommended_camera, confidence, description
     Used by: UI to auto-fill space type and camera movement dropdowns

  2. OUTPUT QC       — compares generated video frame against original photo
     Returns: verdict (pass/flag/reject), issues list, quality_score
     Used by: pipeline to hold assembly until human approves flagged clips

  3. TTS QC          — checks generated audio file quality
     Returns: verdict, issues list
     Used by: pipeline after each ElevenLabs call

All vision calls use fal-ai/florence-2-large/more-detailed-caption.
Uses existing FAL_KEY — no additional API key required.
Cost: ~€0.0001-0.0003 per image analysis.
"""

import os
import re
import logging
import tempfile
from pathlib import Path

import fal_client
import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Model endpoint ─────────────────────────────────────────────────────────────
FLORENCE_ENDPOINT = "fal-ai/florence-2-large/more-detailed-caption"

# ── Space classification keywords (parsed from Florence description) ───────────
# IMPORTANT: Only use keywords that unambiguously mean the CAMERA IS ON
# the elevated space — not just that a terrace/balcony is visible through a window.
_ELEVATED_KW  = ["balcony floor","terrace floor","standing on balcony",
                  "standing on terrace","balcony railing in foreground",
                  "elevated outdoor","outdoor balcony","rooftop terrace",
                  "stepping onto terrace","stepping onto balcony",
                  "terrace with outdoor furniture","balcony with outdoor furniture"]

# If ANY of these appear in the description alongside elevated keywords,
# it's an interior with a view — not an elevated space.
_INTERIOR_OVERRIDE_KW = ["sofa","armchair","dining table","coffee table","bookshelf",
                          "wardrobe","bed","kitchen","living room","indoor","interior",
                          "carpet","wooden floor inside","ceiling","chandelier","curtains"]

_OUTDOOR_KW   = ["garden","yard","swimming pool","driveway","building facade",
                  "courtyard","patio","lawn","grass","outdoor pathway",
                  "entrance gate","street view","outdoor space","outside the building",
                  "parking","front garden","back garden"]
_SMALLROOM_KW = ["bathroom","shower","bathtub","toilet","wc","sink","basin",
                  "hallway","corridor","laundry","utility room","closet","pantry",
                  "narrow room","compact room","ensuite","cloakroom","powder room"]
_BEDROOM_KW   = ["bedroom","bed frame","mattress","pillows","headboard","wardrobe",
                  "nightstand","bedside table","duvet","bedroom furniture","sleeping area"]

# Body part detection — used in QC separate from general description
_BODY_PART_KW = ["human hand","person's hand","hand reaching","fingers visible",
                  "arm visible","arm extended","human arm","body part","limb visible",
                  "hand in frame","hands in frame","arm in frame","person visible",
                  "human figure","silhouette of person"]

# ── Camera recommendations by space type ──────────────────────────────────────
_SPACE_CAMERA = {
    "large_interior":  "gentle_arc",
    "medium_interior": "gentle_arc",
    "bedroom":         "straight_push",
    "small_interior":  "straight_push",
    "ground_exterior": "soft_orbit",
    "elevated":        "minimal",
}

# ── People/anomaly detection keywords for QC ──────────────────────────────────
_PEOPLE_KW    = ["person","people","man","woman","child","human","figure",
                  "face","hand","arm","leg","body","silhouette","shadow of a person"]
_STRUCTURAL_KW = ["door opening","window appeared","new room","additional room",
                   "different room","corridor appeared","staircase appeared",
                   "wall disappeared","ceiling collapsed","furniture moved",
                   "door swinging","door ajar","door opened","opening door",
                   "new doorway","new window","previously unseen",
                   "open door","doorway visible","door frame","through the door",
                   "another room","room behind","hallway beyond","space beyond",
                   "room beyond","area beyond","space through","leading to another"]


# ── Florence-2 helper ──────────────────────────────────────────────────────────

def _describe_image(image_url: str) -> str:
    """
    Calls Florence-2 Large to get a detailed caption of an image.
    Returns the description string, or empty string on failure.
    """
    try:
        result = fal_client.subscribe(
            FLORENCE_ENDPOINT,
            arguments={"image_url": image_url}
        )
        description = result.get("results", "").strip()
        log.info(f"[Vision] Florence description: {description[:120]}...")
        return description
    except Exception as e:
        log.warning(f"[Vision] Florence-2 call failed: {e}")
        return ""


def _upload_local_image(image_path: str) -> str:
    """Uploads a local image to fal.ai and returns its URL."""
    try:
        url = fal_client.upload_file(image_path)
        return url
    except Exception as e:
        log.warning(f"[Vision] Image upload failed: {e}")
        return ""


# ── Space type classification ──────────────────────────────────────────────────

def _classify_space(description: str) -> tuple[str, float]:
    """
    Parses a Florence-2 description and returns (space_type, confidence).
    """
    d = description.lower()

    # Check elevated ONLY if no interior furniture/elements are present
    # This prevents windows with terrace views from triggering elevated
    has_interior = any(k in d for k in _INTERIOR_OVERRIDE_KW)
    if any(k in d for k in _ELEVATED_KW) and not has_interior:
        return "elevated", 0.85

    # Check outdoor
    if any(k in d for k in _OUTDOOR_KW) and not has_interior:
        return "ground_exterior", 0.85

    # Check small rooms
    if any(k in d for k in _SMALLROOM_KW):
        return "small_interior", 0.90

    # Check bedroom
    if any(k in d for k in _BEDROOM_KW):
        return "bedroom", 0.90

    # Estimate interior size from description cues
    size_cues_large  = ["spacious","open plan","large room","expansive","wide","high ceiling",
                         "open-plan","generous","airy","grand","living room","salon","lounge"]
    size_cues_medium = ["medium","modest","cosy","cozy","comfortable","dining room",
                         "kitchen","study","office","studio","well-proportioned"]

    large_score  = sum(1 for k in size_cues_large  if k in d)
    medium_score = sum(1 for k in size_cues_medium if k in d)

    if large_score > medium_score:
        return "large_interior", 0.75
    elif medium_score > 0:
        return "medium_interior", 0.70
    else:
        return "large_interior", 0.55   # default — interior with unknown size


def _estimate_depth(description: str) -> str:
    """Estimates spatial depth from the Florence description."""
    d = description.lower()
    deep_cues   = ["background","far wall","depth","perspective","leading lines",
                   "distance","vista","view through","open plan","see through"]
    shallow_cues = ["small","narrow","compact","tight","close","limited","confined"]

    if any(k in d for k in deep_cues):   return "deep"
    if any(k in d for k in shallow_cues): return "shallow"
    return "medium"


# ── 1. INPUT ANALYSIS ──────────────────────────────────────────────────────────

def analyse_input(image_path: str) -> dict:
    """
    Analyses a property photo to determine space type and recommend camera movement.

    Args:
        image_path: Local path to the uploaded photo.

    Returns:
        {
          "space_type":          "large_interior|medium_interior|bedroom|small_interior|ground_exterior|elevated",
          "depth":               "shallow|medium|deep",
          "recommended_camera":  "gentle_arc|straight_push|soft_orbit|minimal|static",
          "confidence":          0.0-1.0,
          "description":         "Florence-2 description of the image",
          "error":               None or error message
        }
    """
    default = {
        "space_type":         "large_interior",
        "v7_space_type":      "large",
        "suggested_movement": "walk_in_explore",
        "depth":              "medium",
        "recommended_camera": "gentle_arc",
        "confidence":         0.0,
        "description":        "",
        "error":              None,
    }

    if not os.environ.get("FAL_KEY"):
        log.warning("[Vision] FAL_KEY not set — skipping input analysis")
        default["error"] = "FAL_KEY not set"
        return default

    if not os.path.exists(image_path):
        default["error"] = f"Image not found: {image_path}"
        return default

    try:
        # Upload image
        image_url   = _upload_local_image(image_path)
        if not image_url:
            default["error"] = "Image upload failed"
            return default

        # Get Florence description
        description = _describe_image(image_url)
        if not description:
            default["error"] = "Vision model returned no description"
            return default

        # Classify
        space_type, confidence = _classify_space(description)
        depth                  = _estimate_depth(description)
        recommended_camera     = _SPACE_CAMERA.get(space_type, "gentle_arc")

        # Map Florence space type to v7 space type and suggested POV movement
        _SPACE_MAP = {
            "large_interior":  "large",
            "medium_interior": "medium",
            "bedroom":         "bedroom",
            "small_interior":  "small",
            "ground_exterior": "outdoor",
            "elevated":        "elevated",
        }
        _MOVEMENT_MAP = {
            "large":    "walk_in_explore",
            "medium":   "walk_in_explore",
            "bedroom":  "walk_in_gentle",
            "small":    "subtle_rotate",    # approach_reveal produces 2D zoom in shallow spaces
            "corridor": "walk_through",
            "outdoor":  "walk_toward",
            "elevated": "step_out_onto",
        }
        # Also detect corridor from description
        corridor_cues = ["corridor","hallway","entrance hall","foyer","narrow passage"]
        if any(c in description.lower() for c in corridor_cues):
            space_type = "small_interior"

        v7_space    = _SPACE_MAP.get(space_type, "large")
        v7_movement = _MOVEMENT_MAP.get(v7_space, "walk_in_explore")
        # Refine movement based on depth
        if v7_space == "large" and depth == "shallow":
            v7_movement = "stand_look_around"

        log.info(
            f"[Vision] Input analysis: space={space_type}→{v7_space} "
            f"movement={v7_movement} depth={depth} "
            f"camera={recommended_camera} confidence={confidence:.0%}"
        )

        return {
            "space_type":          space_type,
            "v7_space_type":       v7_space,
            "suggested_movement":  v7_movement,
            "depth":               depth,
            "recommended_camera":  recommended_camera,
            "confidence":          confidence,
            "description":         description,
            "error":               None,
        }

    except Exception as e:
        log.error(f"[Vision] Input analysis failed: {e}", exc_info=True)
        default["error"] = str(e)
        return default


# ── 2. OUTPUT VIDEO QC ────────────────────────────────────────────────────────

def _extract_video_frame(video_path: str, position: str = "first") -> str | None:
    """
    Extracts a single frame from a video clip and saves it as a temp JPEG.
    position: "first" or "last"
    Returns local path to the extracted frame, or None on failure.
    """
    try:
        from moviepy import VideoFileClip
        clip  = VideoFileClip(video_path)
        t     = 0.1 if position == "first" else max(0, clip.duration - 0.5)
        frame = clip.get_frame(t)
        clip.close()

        # Save frame as JPEG
        from PIL import Image
        import numpy as np
        img      = Image.fromarray(frame.astype("uint8"))
        tmp_path = tempfile.mktemp(suffix=f"_{position}.jpg")
        img.save(tmp_path, quality=85)
        return tmp_path

    except Exception as e:
        log.warning(f"[Vision] Frame extraction failed ({position}): {e}")
        return None


def analyse_output(
    video_path:         str,
    original_image_path: str,
) -> dict:
    """
    Compares generated video frames against the original photo for QC.

    Args:
        video_path:          Local path to the generated .mp4 clip.
        original_image_path: Local path to the original input photo.

    Returns:
        {
          "verdict":                  "pass|flag|reject",
          "people_detected":          True|False,
          "space_matches":            True|False,
          "structural_hallucinations": True|False,
          "quality_score":            0.0-1.0,
          "issues":                   ["list of issues"],
          "original_description":     "...",
          "output_description":       "...",
          "error":                    None or error message
        }
    """
    default = {
        "verdict":                   "pass",
        "people_detected":           False,
        "space_matches":             True,
        "structural_hallucinations": False,
        "quality_score":             1.0,
        "issues":                    [],
        "original_description":      "",
        "output_description":        "",
        "error":                     None,
    }

    if not os.environ.get("FAL_KEY"):
        log.warning("[Vision] FAL_KEY not set — skipping output QC")
        default["error"] = "FAL_KEY not set"
        return default

    issues = []

    try:
        # ── Describe original photo ────────────────────────────────────────
        orig_url  = _upload_local_image(original_image_path)
        orig_desc = _describe_image(orig_url) if orig_url else ""
        orig_space, _ = _classify_space(orig_desc) if orig_desc else ("unknown", 0)

        # ── Extract and describe first frame of video ──────────────────────
        first_frame = _extract_video_frame(video_path, "first")
        if not first_frame:
            default["error"] = "Could not extract video frame"
            default["verdict"] = "flag"
            return default

        # ── Describe first AND last frame ─────────────────────────────────
        frame_url  = _upload_local_image(first_frame)
        frame_desc = _describe_image(frame_url) if frame_url else ""

        # Also check last frame for hallucinations that appear mid-clip
        last_frame  = _extract_video_frame(video_path, "last")
        last_desc   = ""
        if last_frame:
            last_url  = _upload_local_image(last_frame)
            last_desc = _describe_image(last_url) if last_url else ""
            try: os.remove(last_frame)
            except: pass

        # Combine descriptions for structural checks
        combined_desc = (frame_desc + " " + last_desc).lower()

        # Clean up temp frame
        try: os.remove(first_frame)
        except: pass

        if not frame_desc:
            default["error"] = "Vision model returned no description for video frame"
            default["verdict"] = "flag"
            default["issues"]  = ["Could not analyse video output"]
            return default

        frame_space, _ = _classify_space(frame_desc)

        # ── Check 1: People and body part detection ───────────────────────
        people_detected     = any(k in combined_desc for k in _PEOPLE_KW)
        body_parts_detected = any(k in combined_desc for k in _BODY_PART_KW)
        if body_parts_detected:
            issues.append("Human body part detected in generated video (hands/arms/fingers)")
            log.warning("[Vision QC] BODY PARTS detected")
        if people_detected:
            issues.append("Person or human element detected in generated video")
            log.warning("[Vision QC] PEOPLE DETECTED")

        # ── Check 2: Space type matches ────────────────────────────────────
        # Allow some flexibility — interior types can vary
        interior_types = {"large_interior","medium_interior","bedroom","small_interior"}
        exterior_types = {"ground_exterior","elevated"}

        space_matches = True
        if orig_space in interior_types and frame_space in exterior_types:
            space_matches = False
            issues.append(f"Space type mismatch: input is {orig_space}, output appears to be {frame_space}")
            log.warning(f"[Vision QC] SPACE MISMATCH: {orig_space} → {frame_space}")
        elif orig_space in exterior_types and frame_space in interior_types:
            space_matches = False
            issues.append(f"Space type mismatch: input is exterior, output appears to be interior")
            log.warning(f"[Vision QC] SPACE MISMATCH: {orig_space} → {frame_space}")

        # ── Check 3: Structural hallucinations (first AND last frame) ────
        structural = any(k in combined_desc for k in _STRUCTURAL_KW)
        if structural:
            issues.append("Possible structural hallucination detected (door opening or new element)")
            log.warning("[Vision QC] STRUCTURAL hallucination suspected")

        # ── Check 4: Basic quality score ──────────────────────────────────
        # Simple heuristic: longer, richer descriptions = better quality
        quality_score = min(1.0, len(frame_desc) / 200)
        if quality_score < 0.3:
            issues.append("Video frame appears low quality or heavily degraded")

        # ── Determine verdict ──────────────────────────────────────────────
        if people_detected or body_parts_detected or not space_matches:
            verdict = "reject"
        elif structural or quality_score < 0.3:
            verdict = "flag"
        elif issues:
            verdict = "flag"
        else:
            verdict = "pass"

        log.info(
            f"[Vision QC] verdict={verdict} people={people_detected} "
            f"space_match={space_matches} quality={quality_score:.2f} "
            f"issues={len(issues)}"
        )

        return {
            "verdict":                   verdict,
            "people_detected":           people_detected,
            "space_matches":             space_matches,
            "structural_hallucinations": structural,
            "quality_score":             round(quality_score, 2),
            "issues":                    issues,
            "original_description":      orig_desc,
            "output_description":        frame_desc,
            "error":                     None,
        }

    except Exception as e:
        log.error(f"[Vision] Output QC failed: {e}", exc_info=True)
        default["error"]   = str(e)
        default["verdict"] = "flag"
        default["issues"]  = [f"QC check failed: {e}"]
        return default


# ── 3. TTS QUALITY CONTROL ────────────────────────────────────────────────────

def analyse_tts(
    audio_path:    str,
    voiceover_text: str,
    tolerance:     float = 0.40,
) -> dict:
    """
    Checks a generated TTS audio file for quality issues.
    All checks are local — no API call needed.

    Checks:
      A. File exists and has content
      B. Not silent (peak volume above threshold)
      C. Duration matches expected reading time (within tolerance)
      D. File is a valid readable audio file

    Args:
        audio_path:     Local path to the generated .mp3 file.
        voiceover_text: The original text that was synthesised.
        tolerance:      Acceptable duration variance (0.40 = ±40%).

    Returns:
        {
          "verdict":           "pass|flag|reject",
          "issues":            ["list of issues"],
          "duration_seconds":  float,
          "expected_seconds":  float,
          "peak_db":           float,
          "error":             None or error message
        }
    """
    default = {
        "verdict":          "pass",
        "issues":           [],
        "duration_seconds": 0.0,
        "expected_seconds": 0.0,
        "peak_db":          0.0,
        "error":            None,
    }

    issues = []

    # ── Check A: File exists ──────────────────────────────────────────────
    if not os.path.exists(audio_path):
        return {**default,
                "verdict": "reject",
                "issues":  ["Audio file does not exist"],
                "error":   "File not found"}

    file_size = os.path.getsize(audio_path)
    if file_size < 1000:   # less than 1KB — almost certainly empty
        return {**default,
                "verdict": "reject",
                "issues":  [f"Audio file too small ({file_size} bytes) — likely empty"],
                "error":   "File too small"}

    try:
        from pydub import AudioSegment

        # ── Check D: Valid audio file ─────────────────────────────────────
        try:
            audio = AudioSegment.from_file(audio_path)
        except Exception as e:
            return {**default,
                    "verdict": "reject",
                    "issues":  [f"Audio file is corrupted or unreadable: {e}"],
                    "error":   str(e)}

        duration_seconds = len(audio) / 1000.0
        peak_db          = audio.max_dBFS

        # ── Check B: Not silent ───────────────────────────────────────────
        SILENCE_THRESHOLD_DB = -50.0
        if peak_db < SILENCE_THRESHOLD_DB:
            issues.append(f"Audio appears silent (peak: {peak_db:.1f}dBFS)")

        # ── Check C: Duration vs expected ─────────────────────────────────
        # ElevenLabs averages ~14 characters per second at normal pace
        CHARS_PER_SECOND = 14.0
        char_count       = len(voiceover_text.strip())
        expected_seconds = char_count / CHARS_PER_SECOND if char_count > 0 else 0

        if expected_seconds > 0:
            ratio = duration_seconds / expected_seconds
            if ratio < (1 - tolerance):
                issues.append(
                    f"Audio too short: {duration_seconds:.1f}s vs expected ~{expected_seconds:.1f}s "
                    f"({char_count} characters). May be truncated."
                )
            elif ratio > (1 + tolerance):
                issues.append(
                    f"Audio longer than expected: {duration_seconds:.1f}s vs ~{expected_seconds:.1f}s. "
                    f"Check for repeated or extra content."
                )

        # ── Determine verdict ─────────────────────────────────────────────
        silence_issue = any("silent" in i for i in issues)
        duration_issue = any("too short" in i or "truncated" in i for i in issues)

        if silence_issue:
            verdict = "reject"
        elif duration_issue:
            verdict = "flag"
        elif issues:
            verdict = "flag"
        else:
            verdict = "pass"

        log.info(
            f"[TTS QC] verdict={verdict} duration={duration_seconds:.1f}s "
            f"expected={expected_seconds:.1f}s peak={peak_db:.1f}dB issues={len(issues)}"
        )

        return {
            "verdict":          verdict,
            "issues":           issues,
            "duration_seconds": round(duration_seconds, 2),
            "expected_seconds": round(expected_seconds, 2),
            "peak_db":          round(peak_db, 1),
            "error":            None,
        }

    except ImportError:
        log.warning("[TTS QC] pydub not available — skipping audio checks")
        return {**default, "error": "pydub not installed"}
    except Exception as e:
        log.error(f"[TTS QC] Unexpected error: {e}", exc_info=True)
        return {**default,
                "verdict": "flag",
                "issues":  [f"QC check failed: {e}"],
                "error":   str(e)}


# ── CLI test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 3:
        print("Usage:")
        print("  Input analysis:  python vision_analysis.py input <image.jpg>")
        print("  Output QC:       python vision_analysis.py output <video.mp4> <original.jpg>")
        print("  TTS QC:          python vision_analysis.py tts <audio.mp3> 'voiceover text'")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "input":
        result = analyse_input(sys.argv[2])
    elif mode == "output":
        result = analyse_output(sys.argv[2], sys.argv[3])
    elif mode == "tts":
        result = analyse_tts(sys.argv[2], sys.argv[3])
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

    print(json.dumps(result, indent=2))
