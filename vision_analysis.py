"""
vision_analysis.py
──────────────────
Dual-purpose vision AI module (input analysis: Claude vision with Florence-2
fallback; output/TTS QC: Florence-2 Large via fal.ai):

  1. INPUT ANALYSIS  — analyses a property photo on upload
     (2026-10-10: room recognition by Claude vision; Florence-2 only as fallback)
     Returns: space_type, depth, recommended_camera, confidence, description
     Used by: UI to auto-fill space type and camera movement dropdowns

  2. OUTPUT QC       — compares first/last frame of a generated clip against the original photo
                       (2026-10-25: Claude vision; Florence-2 + keywords removed, backlog 83)
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
import camera_plan
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

# Interior override — only used to prevent ELEVATED false positives
_ELEVATED_INTERIOR_OVERRIDE = ["sofa","armchair","dining table","coffee table",
                                "bookshelf","wardrobe","bed frame","kitchen counter",
                                "living room furniture","indoor flooring","carpet",
                                "chandelier","indoor ceiling light","parquet floor"]

# Strong outdoor indicators — specific enough to not match interior descriptions
_OUTDOOR_KW   = ["garden","swimming pool","driveway","building facade",
                  "courtyard","patio","lawn","grass","outdoor pathway",
                  "entrance gate","street view","outdoor space","outside the building",
                  "parking area","front garden","back garden","exterior wall",
                  "outdoor area","gravel path","exterior of","building exterior",
                  "house exterior","property exterior","outdoor terrace",
                  "exterior view","outdoor ground","sunlight on ground",
                  "sky above","open sky","outdoor furniture on ground",
                  "stone path","brick path","exterior facade"]

_SMALLROOM_KW = ["bathroom","shower","bathtub","toilet","wc","sink","basin",
                  "hallway","corridor","laundry","utility room","closet","pantry",
                  "narrow room","compact room","ensuite","cloakroom","powder room"]
_BEDROOM_KW   = ["bedroom","bed frame","mattress","pillows","headboard","wardrobe",
                  "nightstand","bedside table","duvet","bedroom furniture","sleeping area"]

# Body part detection

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
# People detection — must be SPECIFIC phrases, not single generic words.
# Previous version used bare words like "figure", "face", "body", "arm", "leg" —
# these match constantly inside ordinary vocabulary: "furniture", "surface",
# "armchair", "table leg", "configuration" — causing false positives on every
# scene with furniture, which is every scene. Only unambiguous multi-word
# phrases that specifically indicate an actual human presence are used here.


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

    # Check elevated — only blocked if strong interior furniture present
    # (prevents window-view-of-terrace from being classified as elevated)
    has_interior_furniture = any(k in d for k in _ELEVATED_INTERIOR_OVERRIDE)
    if any(k in d for k in _ELEVATED_KW) and not has_interior_furniture:
        return "elevated", 0.85

    # Check outdoor — NOT blocked by interior override
    # A garden photo may have windows with interior visible; it's still outdoor
    outdoor_score = sum(1 for k in _OUTDOOR_KW if k in d)
    if outdoor_score >= 1:
        return "ground_exterior", min(0.70 + outdoor_score * 0.05, 0.95)

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
        return "large_interior", 0.55


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

# ── 1a. ROOM RECOGNITION (Claude vision) ───────────────────────────────────────
# 2026-10-10: Florence-2 + keyword rules mislabelled rooms (exterior -> "large
# interior", living room -> "bedroom", balcony -> "large interior"). Room
# recognition now asks Claude vision; Florence stays only as a fallback when the
# Claude call fails. ONE implementation: analyse_input() is used by the manual
# "analyse photo" endpoint, the URL scraper and the Relinx adapter alike.

_ROOMS = ("living", "dining", "kitchen", "bedroom", "bathroom", "hallway", "balcony",
          "terrace", "garden", "building_exterior", "pool", "other_interior", "other_exterior")
_SIZES = ("small", "medium", "large")
_DEPTHS = ("shallow", "medium", "deep")

ROOM_PROMPT = """You classify ONE real-estate photo so a camera-motion planner can choose a move.
Look only at what the camera sees. Reply with ONLY a JSON object, no other text:
{"room": "<one of: living, dining, kitchen, bedroom, bathroom, hallway, balcony, terrace, garden, building_exterior, pool, other_interior, other_exterior>",
 "size": "<small|medium|large>",
 "depth": "<shallow|medium|deep>",
 "confidence": <0.0-1.0>,
 "description": "<max 15 words>"}
Rules:
- "balcony" or "terrace" ONLY if the camera is standing ON that outdoor space. An interior photo that shows a balcony or terrace through a window or door is the interior room (living, bedroom...).
- "garden", "building_exterior", "pool", "other_exterior" = camera is outside at ground level (facade, yard, courtyard, driveway, land).
- "hallway" = entrance hall, corridor, stairs landing.
- "size": how much floor area is visible. small = bathroom/closet/tiny room, medium = typical bedroom/kitchen/dining, large = open-plan or big living space (or any outdoor area).
- "depth": shallow = wall or objects close to camera, deep = long view through the space."""


# 2026-10-27: camera direction. Asked in the SAME call (no second analysis), only when PVS_ANCHOR=1 so the prompt is otherwise unchanged.
ROOM_PROMPT_ANCHOR = """
Also add three more keys to the JSON object. They choose the TARGET of a slow straight camera push-in (the camera moves toward it and stops well before reaching it):
 "anchor": an English noun phrase of at most 8 words, or "none".
 "anchor_side": where it sits horizontally in the frame: left, center or right.
 "anchor_height": where it sits vertically in the frame: upper, middle or lower.
Rules for the anchor:
 - It must sit in the CENTRE of the frame (middle vertically, not near the left or right edge) and be FAR from the camera: the far wall, the far end of the room, a window or opening with a view. For outdoor photos, balconies and terraces choose the DISTANT VIEW (the landscape, skyline, garden or horizon beyond), never what is near you.
 - It must be worth looking at for a buyer: the view, a window with a view, the far end of the living space, a bed, a sofa area, a fireplace, a dining set. NOT a utilitarian fixture (sink, toilet, bathtub, shower, radiator, stove, oven, fridge, kitchen counter, appliance).
 - It must be fixed and still: NEVER a door of any kind (doors get animated), curtain, blind, plant, water, flame, screen, mirror or any reflective surface, person, animal or small decorative object.
 - NEVER a near foreground object (railing, balustrade, fence, a table or chair close to the camera): it pulls the camera down toward the floor.
 - If nothing satisfies all of this, answer "none"."""


def _claude_vision_call(image_paths: list, prompt: str, max_tokens: int = 250, model: str = None, usage_out: dict = None) -> str | None:
    """Sends one or more (downscaled) photos + prompt to Claude vision; returns the text, or None on any failure.
    Default: reuses listing_scraper's model and its per-job usage counter (draft stage).
    usage_out (Patch X, 2026-10-25): a dict that receives THIS call's tokens and cost (and the call is then NOT added to the process-wide
    counter) - the clip QC runs long after the draft, so its usage is attached to the job explicitly (see api_server).
    2026-10-25: the single-image helper became this (one implementation) so the clip QC can send photo + 2 frames."""
    try:
        import base64, io
        import anthropic
        from PIL import Image
        import listing_scraper as ls
        if not os.getenv("ANTHROPIC_API_KEY"):
            return None
        content = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            img = Image.open(image_path).convert("RGB")
            img.thumbnail((1024, 1024))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        use_model = model or ls.MODEL
        resp = client.messages.create(model=use_model, max_tokens=max_tokens, messages=[{"role": "user", "content": content}])
        if usage_out is None:
            ls._track_claude(resp)
        else:
            u = getattr(resp, "usage", None)
            i_t, o_t = int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
            usage_out.update(ls.merge_claude_usage(usage_out, {"input_tokens": i_t, "output_tokens": o_t, "calls": 1,
                                                                "cost_eur": ls.claude_cost_eur(i_t, o_t, use_model)}))
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:
        log.warning(f"[Vision] Claude vision call failed: {e}")
        return None


def _claude_vision_text(image_path: str, prompt: str, max_tokens: int = 250) -> str | None:
    """One photo + prompt -> text (room recognition). Thin wrapper of _claude_vision_call."""
    return _claude_vision_call([image_path], prompt, max_tokens)


def _classify_room_claude(image_path: str) -> dict | None:
    """Returns {"room","size","depth","confidence","description"} or None if the call failed or the answer is invalid."""
    import json
    raw = _claude_vision_text(image_path, ROOM_PROMPT + (ROOM_PROMPT_ANCHOR if camera_plan.anchor_enabled() else ""), 420 if camera_plan.anchor_enabled() else 250)
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        log.warning(f"[Vision] Claude room answer is not JSON: {raw[:120]}")
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        log.warning(f"[Vision] Claude room answer is invalid JSON: {raw[:120]}")
        return None
    room = str(d.get("room", "")).strip().lower()
    size = str(d.get("size", "medium")).strip().lower()
    depth = str(d.get("depth", "medium")).strip().lower()
    if room not in _ROOMS:
        log.warning(f"[Vision] Claude returned unknown room {room!r}")
        return None
    if size not in _SIZES:
        size = "medium"
    if depth not in _DEPTHS:
        depth = "medium"
    try:
        conf = max(0.0, min(1.0, float(d.get("confidence", 0.8))))
    except Exception:
        conf = 0.8
    out = {"room": room, "size": size, "depth": depth, "confidence": conf,
           "description": str(d.get("description", ""))[:200]}
    if camera_plan.anchor_enabled():       # unusable / unsafe / "none" -> "": the scene then keeps today's movement text
        out["anchor"] = camera_plan.anchor_usable(d.get("anchor"), d.get("anchor_side"), d.get("anchor_height"))
        out["anchor_side"] = camera_plan.clean_side(d.get("anchor_side")) if out["anchor"] else ""
    return out


def _space_from_room(room: str, size: str) -> str:
    """Room + size -> the internal space_type vocabulary used by the rest of this module."""
    if room in ("garden", "building_exterior", "pool", "other_exterior"):
        return "ground_exterior"
    if room in ("balcony", "terrace"):
        return "elevated"
    if room == "bedroom":
        return "bedroom"
    if room == "bathroom":
        return "small_interior"
    if room == "hallway":
        return "corridor"
    return {"small": "small_interior", "medium": "medium_interior", "large": "large_interior"}.get(size, "medium_interior")


# internal space_type -> v7 UI vocabulary (ui.html SPACE_OPTS) and default POV movement (MOVEMENT_OPTS)
_SPACE_MAP = {
    "large_interior": "large", "medium_interior": "medium", "bedroom": "bedroom",
    "small_interior": "small", "corridor": "corridor", "ground_exterior": "outdoor", "elevated": "elevated",
}
# 2026-10-26: the movement table is camera_plan.SPACE_DEFAULT_MOVEMENT (it used to be a drifted copy here); same object, no second table.
_MOVEMENT_MAP = camera_plan.SPACE_DEFAULT_MOVEMENT


def _build_input_result(space_type, depth, confidence, description, source, room=None, anchor="", anchor_side="") -> dict:
    v7_space = _SPACE_MAP.get(space_type, "large")
    v7_movement = camera_plan.movement_for(v7_space, depth, room)
    camera = _SPACE_CAMERA.get(space_type, "gentle_arc")
    log.info(f"[Vision] Input analysis ({source}): room={room} space={space_type}->{v7_space} "
             f"movement={v7_movement} depth={depth} confidence={confidence:.0%}")
    return {
        "space_type":          space_type,
        "v7_space_type":       v7_space,
        "suggested_movement":  v7_movement,
        "depth":               depth,
        "recommended_camera":  camera,
        "confidence":          confidence,
        "description":         description,
        "room":                room,
        "source":              source,
        "error":               None,
        "anchor":              anchor,
        "anchor_side":         anchor_side,
    }


def _analyse_input_florence(image_path: str, default: dict) -> dict:
    """Legacy Florence-2 + keyword classification (fallback only)."""
    if not os.environ.get("FAL_KEY"):
        log.warning("[Vision] FAL_KEY not set — skipping Florence input analysis")
        default["error"] = "FAL_KEY not set"
        return default
    try:
        image_url = _upload_local_image(image_path)
        if not image_url:
            default["error"] = "Image upload failed"
            return default
        description = _describe_image(image_url)
        if not description:
            default["error"] = "Vision model returned no description"
            return default
        space_type, confidence = _classify_space(description)
        depth = _estimate_depth(description)
        corridor_cues = ["corridor", "hallway", "entrance hall", "foyer", "narrow passage"]
        if any(c in description.lower() for c in corridor_cues):
            space_type = "small_interior"
        return _build_input_result(space_type, depth, confidence, description, "florence")
    except Exception as e:
        log.error(f"[Vision] Florence input analysis failed: {e}", exc_info=True)
        default["error"] = str(e)
        return default


# ── 1. INPUT ANALYSIS ──────────────────────────────────────────────────────────

def analyse_input(image_path: str) -> dict:
    """
    Analyses a property photo to determine space type and recommend camera movement.

    2026-10-10: room recognition by Claude vision (Florence-2 only as fallback).

    Returns:
        {
          "space_type":          "large_interior|medium_interior|bedroom|small_interior|corridor|ground_exterior|elevated",
          "v7_space_type":       "large|medium|bedroom|small|corridor|outdoor|elevated"  (ui.html SPACE_OPTS keys),
          "suggested_movement":  a ui.html MOVEMENT_OPTS key,
          "depth":               "shallow|medium|deep",
          "recommended_camera":  "gentle_arc|straight_push|soft_orbit|minimal|static",
          "confidence":          0.0-1.0,
          "description":         short description of the image,
          "room":                "living|kitchen|bedroom|..." (None when Florence was used),
          "source":              "claude" | "florence",
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
        "room":               None,
        "source":             None,
        "error":              None,
    }
    if not os.path.exists(image_path):
        default["error"] = f"Image not found: {image_path}"
        return default

    r = _classify_room_claude(image_path)
    if r:
        return _build_input_result(_space_from_room(r["room"], r["size"]), r["depth"],
                                   r["confidence"], r["description"], "claude", room=r["room"],
                                   anchor=r.get("anchor", ""), anchor_side=r.get("anchor_side", ""))
    log.warning("[Vision] Claude room recognition unavailable — falling back to Florence-2")
    return _analyse_input_florence(image_path, default)


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


CLIP_QC_MAX_TOKENS = 1200   # 2026-10-25: Haiku 5.5 writes ~700 tokens, so 700 cut its JSON (6 of 12 answers invalid in the model comparison)
CLIP_QC_DEFAULT_MODEL = "claude-sonnet-5-5"   # 2026-10-25 (Michele "ok Sonnet 5.5"): same verdicts on 2 full runs, 0 false rejects, best descriptions; ~EUR 0.0093 per clip
CLIP_QC_MODEL = os.getenv("CLIP_QC_MODEL") or CLIP_QC_DEFAULT_MODEL   # CLIP_QC_MODEL in .env overrides it (e.g. back to claude-haiku-4-5-20251001)

CLIP_QC_PROMPT = """You are the quality check of an AI-generated real-estate video clip.
You get THREE images, in this order: (1) the ORIGINAL PHOTO the clip was made from, (2) the FIRST frame of the clip, (3) the LAST frame of the clip.
The system already knows what kind of space this is ({known}). NEVER judge or comment on interior-versus-exterior or on the type of room: only compare what is in the frames with what is in the photo.
The camera moves, so a frame may show a slightly different part of the SAME space: that is normal and is NOT a problem. Compare only things that clearly contradict the photo.

Work in two steps. STEP A - look ONLY at the photo (image 1) and write down its FIXED ELEMENTS that can be counted or named exactly: how many beds and of what kind (one double bed? two single beds?), sofas, chairs, tables, how many doors and windows and of what kind (sliding glass door, hinged door, arched window, french window...), stairs, built-in furniture, large fixtures. STEP B - check each of those elements in image 2 and in image 3 (when it is in view): same number, same kind, same place? A different number or a different kind (for example a sofa that became two armchairs, a sliding glass door that became a hinged door) is a MAJOR change even if the room looks similar. A REFLECTION in a mirror, a window or glass is NOT a separate object: never count it as an extra bed, door or window, in the photo or in the frames (a bed seen again inside a mirrored wardrobe is still ONE bed). Also list anything in image 2 or 3 that does not exist in the photo.

Answer with ONE JSON object and nothing else:
{{"photo_elements": ["..."],                // step A: the counted/named fixed elements of the photo (max 10 short items)
 "people": true|false,                     // a person, a face, a hand/arm/finger, or the shadow or reflection of a person or photographer, CLEARLY recognisable in frame 2 or 3 and NOT in the photo
 "possible_person": true|false,             // something that MIGHT be a person but is faint, blurry or ambiguous, or could just be a pattern (tiles, wallpaper, plants, curtains, furniture, textures): use this INSTEAD of "people" when you are not sure
 "same_space": true|false,                  // frames 2 and 3 show the same place as the photo (false only if it is clearly another place)
 "new_structure": ["..."],                  // step B: elements of the photo that are missing, changed in number or kind, or things that do NOT exist in the photo (a new door/window/opening/stair/wall, furniture added or removed). Empty list if none. Elements that ARE in the photo, in the same number and kind, do not count.
 "severity": "none"|"minor"|"major",        // major = a clear invented or changed structure/furniture number or kind, or another place; minor = small doubtful differences
 "artifacts": true|false,                   // heavy warping, melting or smeared surfaces in frame 2 or 3
 "first_frame": "one sentence describing frame 2",
 "last_frame": "one sentence describing frame 3"}}"""


def _parse_clip_qc(raw: str):
    """Claude's reply -> a validated dict, or None when it is not the expected JSON."""
    import json
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(re.sub(r"//[^\n]*", "", m.group(0)))
    except Exception:
        return None
    if not isinstance(d, dict) or "severity" not in d or "people" not in d:
        return None
    sev = str(d.get("severity", "none")).strip().lower()
    if sev not in ("none", "minor", "major"):
        return None
    ns = d.get("new_structure") or []
    if not isinstance(ns, list):
        ns = [str(ns)]
    return {"people": bool(d.get("people")), "possible_person": bool(d.get("possible_person")), "same_space": d.get("same_space", True) is not False,
            "new_structure": [str(x)[:160] for x in ns][:6], "severity": sev, "artifacts": bool(d.get("artifacts")),
            "first_frame": str(d.get("first_frame", ""))[:300], "last_frame": str(d.get("last_frame", ""))[:300],
            "photo_elements": [str(x)[:80] for x in (d.get("photo_elements") or [])][:10] if isinstance(d.get("photo_elements"), list) else []}


def clip_qc_verdict(qc: dict) -> tuple:
    """(verdict, issues) from the parsed answer. The rules are HERE, not in the model: reject = a CLEAR person/body part, another place, or a
    major invented/changed structure; flag = something the operator can read and check (a described difference, a doubtful person, artifacts);
    otherwise pass. 2026-10-26 (Michele, real job 6dddfd66): a faint 'human-like silhouette' in a tile pattern rejected a good clip, and a
    'minor' severity with nothing described flagged a good clip with no text - so a doubtful person is a flag, not a reject, and a flag
    always carries a text (nothing to read = nothing to check = pass)."""
    issues = []
    if qc["people"]:
        issues.append("Persona, parte del corpo, ombra o riflesso di una persona nel video")
    elif qc.get("possible_person"):
        issues.append("Possibile figura umana poco chiara (può essere una texture o un disegno): verificare")
    if not qc["same_space"]:
        issues.append("Il video mostra un posto diverso dalla foto")
    if qc["new_structure"] and qc["severity"] != "none":
        issues.append("Struttura/arredo diverso dalla foto: " + "; ".join(qc["new_structure"]))
    elif qc["severity"] == "major":
        issues.append("Struttura/arredo molto diverso dalla foto (il controllo non ha indicato quale)")
    if qc["artifacts"]:
        issues.append("Deformazioni evidenti nel video")
    if qc["people"] or not qc["same_space"] or qc["severity"] == "major":
        return "reject", issues
    return ("flag" if issues else "pass"), issues


def analyse_output(
    video_path:          str,
    original_image_path: str,
    known_space_type:    str = None,  # the scene space_type from the job: NEVER contested by the QC
) -> dict:
    """
    Clip QC (2026-10-25: Claude vision instead of Florence-2 captions + keywords, backlog 83). Claude receives the original photo, the
    first and the last frame and answers a strict JSON (see CLIP_QC_PROMPT); the verdict rules are in clip_qc_verdict().
    The known space type is only context for the model: interior-versus-exterior is no longer judged here.

    Returns the same keys as before (verdict pass|flag|reject, people_detected, space_matches, structural_hallucinations, quality_score,
    issues, original_description, output_description, error) plus last_description, new_structure, severity, qc_engine.
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cost_eur": 0.0}     # THIS clip's Claude usage (the pipeline adds it to the job)
    default = {
        "verdict": "pass", "people_detected": False, "space_matches": True, "structural_hallucinations": False,
        "quality_score": 1.0, "issues": [], "original_description": "", "output_description": "", "last_description": "",
        "new_structure": [], "severity": "none", "qc_engine": "claude", "error": None, "claude_usage": usage,
    }

    def _fail(msg):
        out = dict(default)
        out.update({"verdict": "flag", "error": msg, "issues": [msg]})
        return out

    first_frame = last_frame = None
    try:
        first_frame = _extract_video_frame(video_path, "first")
        last_frame = _extract_video_frame(video_path, "last")
        if not first_frame or not last_frame:
            return _fail("QC: impossibile estrarre i frame dal video")
        known = (known_space_type or "").strip() or "not given"
        raw = _claude_vision_call([original_image_path, first_frame, last_frame], CLIP_QC_PROMPT.format(known=known), max_tokens=CLIP_QC_MAX_TOKENS,
                                  model=CLIP_QC_MODEL, usage_out=usage)
        qc = _parse_clip_qc(raw)
        if qc is None:
            log.warning(f"[Vision QC] Claude answer unusable: {str(raw)[:160]!r}")
            return _fail("QC: risposta di Claude non valida o non disponibile")
        verdict, issues = clip_qc_verdict(qc)
        log.info(f"[Vision QC] verdict={verdict} people={qc['people']} same_space={qc['same_space']} severity={qc['severity']} "
                 f"new_structure={qc['new_structure']} artifacts={qc['artifacts']}")
        out = dict(default)
        out.update({
            "verdict": verdict, "people_detected": qc["people"], "space_matches": qc["same_space"],
            "structural_hallucinations": bool(qc["new_structure"]) and qc["severity"] != "none",
            "quality_score": 0.2 if qc["artifacts"] else 1.0, "issues": issues,
            "output_description": qc["first_frame"], "last_description": qc["last_frame"],
            "new_structure": qc["new_structure"], "severity": qc["severity"], "photo_elements": qc["photo_elements"],
        })
        return out
    except Exception as e:
        log.error(f"[Vision] Output QC failed: {e}", exc_info=True)
        return _fail(f"QC check failed: {e}")
    finally:
        for f in (first_frame, last_frame):
            try:
                if f:
                    os.remove(f)
            except Exception:
                pass


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
