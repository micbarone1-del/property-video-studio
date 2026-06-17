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
_ELEVATED_KW = ["balcony","terrace","loggia","rooftop","roof terrace","roof top","balustrade","parapet","roof deck","roof garden"]
_OUTDOOR_KW   = ["garden","yard","pool","swimming","driveway","facade","courtyard",
                  "exterior","patio","lawn","grass","outdoor",
                  "street","pathway","entrance gate","letterbox"]
_SMALLROOM_KW = ["bathroom","shower","bathtub","toilet","wc","sink","basin",
                  "hallway","corridor","laundry","utility room","closet","pantry",
                  "narrow","compact","small room","ensuite","cloakroom"]
_BEDROOM_KW   = ["bedroom","bed","mattress","pillows","headboard","wardrobe",
                  "nightstand","bedside","duvet","bedroom furniture","sleeping"]

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
_PEOPLE_KW    = ["person","people","man","woman","child","human",
              "face","silhouette","shadow of a person"]
_STRUCTURAL_KW = ["door opening","window appeared","new room","additional room",
                   "different room","corridor appeared","staircase appeared",
                   "wall disappeared","ceiling collapsed","furniture moved"]


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
    space_type is one of: large_interior, medium_interior, bedroom,
                          small_interior, ground_exterior, elevated
    confidence is 0.0-1.0
    """
    import re as _re
    d = description.lower()

    # Phrases indicating the elevated/outdoor element is visible in the background
    # but is NOT the primary subject of the image
    _BACKGROUND_CTX = [
        "leads to a balcony", "leads to the balcony", "leads to a terrace",
        "lead to a balcony", "lead to a terrace",
        "door that leads to", "doors that lead", "doors lead to",
        "opening to a balcony", "opening onto",
        "through the window", "through the door", "outside the window",
        "glass door", "sliding door", "sliding glass",
        "terrace door", "terrace doors", "balcony door", "balcony doors",
        "in the background", "outside the room", "can be seen", "seen through",
        "from the window", "view of", "visible through",
    ]

    # Interior room subject words — if present alongside elevated keyword,
    # the elevated keyword is likely background context
    _INTERIOR_SUBJ = [
        "living room", "bedroom", "kitchen", "dining room", "bathroom",
        "hallway", "corridor", "salon", "lounge", "apartment", "flat",
        "study", "office", "room with", "sofa", "bed ", "wardrobe",
        "ceiling", "floor is", "floor of", "walls are", "painted",
        "furniture", "the image shows a",
    ]

    # Check elevated — but verify it is the PRIMARY subject, not background
    elevated_found = any(k in d for k in _ELEVATED_KW)
    if elevated_found:
        background_override = any(ctx in d for ctx in _BACKGROUND_CTX)
        interior_subject    = any(kw  in d for kw  in _INTERIOR_SUBJ)

        if background_override and interior_subject:
            pass  # interior room with outdoor visible through door/window
        elif ("rooftops" in d and interior_subject
              and not any(k in d for k in ["on the rooftop", "rooftop terrace",
                                            "roof terrace", "roof garden"])):
            pass  # interior room with rooftops visible through window
        elif _re.search(r"\b(window|room)\b.{0,50}\boverloo", d) and interior_subject:
            pass  # "window overlooks" pattern in interior room
        else:
            return "elevated", 0.85

    # Check outdoor / ground exterior
    if any(k in d for k in _OUTDOOR_KW):
        return "ground_exterior", 0.85

    # Check small rooms (bathroom, corridor, etc.)
    if any(k in d for k in _SMALLROOM_KW):
        return "small_interior", 0.90

    # Check bedroom — only truly bedroom-specific terms (wardrobe removed as too generic)
    _STRICT_BEDROOM_KW = [
        "bedroom", "mattress", "pillows", "headboard",
        "nightstand", "bedside", "duvet", "bedroom furniture", "sleeping",
        "bed frame", "double bed", "single bed", "king size", "queen size",
    ]
    if any(k in d for k in _STRICT_BEDROOM_KW):
        return "bedroom", 0.90
    # standalone "bed" (not bedside / bedroom / bedspread)
    if _re.search(r"\bbed\b", d) and not _re.search(r"bed(side|room|spread|ding)", d):
        return "bedroom", 0.85

    # Estimate interior size from description cues
    size_cues_large  = ["spacious", "open", "large", "expansive", "wide",
                        "high ceiling", "open plan", "generous", "airy",
                        "grand", "living room", "salon"]
    size_cues_medium = ["medium", "modest", "cosy", "cozy", "comfortable",
                        "dining", "kitchen", "study", "office", "studio"]
    large_score  = sum(1 for k in size_cues_large  if k in d)
    medium_score = sum(1 for k in size_cues_medium if k in d)

    if large_score > medium_score:
        return "large_interior", 0.75
    elif medium_score > 0:
        return "medium_interior", 0.70
    else:
        return "large_interior", 0.55  # default with low confidence


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

        log.info(
            f"[Vision] Input analysis: space={space_type} depth={depth} "
            f"camera={recommended_camera} confidence={confidence:.0%}"
        )

        return {
            "space_type":         space_type,
            "depth":              depth,
            "recommended_camera": recommended_camera,
            "confidence":         confidence,
            "description":        description,
            "error":              None,
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

        frame_url  = _upload_local_image(first_frame)
        frame_desc = _describe_image(frame_url) if frame_url else ""

        # Clean up temp frame
        try: os.remove(first_frame)
        except: pass

        if not frame_desc:
            default["error"] = "Vision model returned no description for video frame"
            default["verdict"] = "flag"
            default["issues"]  = ["Could not analyse video output"]
            return default

        frame_space, _ = _classify_space(frame_desc)

        # ── Check 1: People detection ──────────────────────────────────────
        people_detected = any(k in frame_desc.lower() for k in _PEOPLE_KW)
        if people_detected:
            issues.append("Person or human element detected in generated video")
            log.warning("[Vision QC] PEOPLE DETECTED in output frame")

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

        # ── Check 3: Structural hallucinations ────────────────────────────
        structural = any(k in frame_desc.lower() for k in _STRUCTURAL_KW)
        if structural:
            issues.append("Possible structural hallucination detected")
            log.warning("[Vision QC] STRUCTURAL hallucination suspected")

        # ── Check 4: Basic quality score ──────────────────────────────────
        # Simple heuristic: longer, richer descriptions = better quality
        quality_score = min(1.0, len(frame_desc) / 200)
        if quality_score < 0.3:
            issues.append("Video frame appears low quality or heavily degraded")

        # ── Determine verdict ──────────────────────────────────────────────
        if people_detected and not space_matches:
            verdict = "reject"    # must redo
        elif people_detected:
            verdict = "flag"  # people detected but space ok
        elif structural or quality_score < 0.3:
            verdict = "flag"      # human review required
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
