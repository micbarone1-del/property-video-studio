"""The ONE place that says which camera movement a photo gets (2026-10-26, Michele chose to consolidate).

Before this module the same table existed in four copies that had already drifted apart: video_generation.SPACE_DEFAULT_MOVEMENT,
vision_analysis._MOVEMENT_MAP (this one decides the movement of every URL draft, it overrides the scraper's), the scraper's
_CATEGORY_TO_POV_MOVEMENT and the mirror in ui.html. Now they all read from here; a test (test_camera_plan.py) fails if ui.html's
copy differs, or if a movement named here is unknown to the Luma prompt tokens or to the UI list.

Michele's camera brief (2026-10-26): facade = slow straight approach that never shows MORE than the photo; garden, pool, balcony and
terrace = just look outward without inventing anything; the old "reveal_pullback" (a reverse dolly) invented a street and a pavement.
"""

DEFAULT_MOVEMENT = "walk_in_explore"

# space type (the UI / v7 vocabulary of SPACE_OPTS) -> default movement. "outdoor" is the UI's "garden, pool, facade": without knowing
# which one, the facade approach is the default (the usual manual upload); the photo analysis knows the room and uses ROOM_MOVEMENT.
SPACE_DEFAULT_MOVEMENT = {
    "large":    "walk_in_explore",
    "medium":   "walk_in_explore",
    "bedroom":  "walk_in_gentle",
    "small":    "subtle_rotate",
    "corridor": "walk_through",
    "outdoor":  "approach_facade",
    "elevated": "outward_view",
}

# room recognised in the photo (vision_analysis._ROOMS) -> movement, for the rooms where the space type is not enough
ROOM_MOVEMENT = {
    "building_exterior": "approach_facade",
    "garden":            "outward_view",
    "pool":              "outward_view",
    "other_exterior":    "outward_view",
    "balcony":           "outward_view",
    "terrace":           "outward_view",
}

# kept as it was (a shallow large room): the generator remaps stand_look_around to walk_in_explore
SHALLOW_LARGE_MOVEMENT = "stand_look_around"


def movement_for(space: str, depth: str = None, room: str = None) -> str:
    """Movement for a photo analysed as (space type, depth, room). Room first, then the shallow-large rule, then the space default."""
    if room in ROOM_MOVEMENT:
        return ROOM_MOVEMENT[room]
    if space == "large" and depth == "shallow":
        return SHALLOW_LARGE_MOVEMENT
    return SPACE_DEFAULT_MOVEMENT.get(space, DEFAULT_MOVEMENT)


# the URL scraper's photo categories -> the movement a scene starts with, before (and if) the photo analysis overrides it. The two
# outside categories are DERIVED from ROOM_MOVEMENT, the others keep the values they always had.
CATEGORY_MOVEMENT = {
    "exterior": ROOM_MOVEMENT["building_exterior"],   # the facade
    "outdoor":  ROOM_MOVEMENT["garden"],              # garden / terrace / pool
    "living":   "walk_in_explore",
    "kitchen":  "walk_in_gentle",
    "bedrooms": "stand_look_around",
    "bathrooms": "subtle_rotate",
}


# ── Start + end frame pair (2026-10-27) ──────────────────────────────────────────────────────────────────────────────────
# Luma can be given the first AND the last frame. Test of 2026-10-26: first frame = whole photo, last frame = a smaller crop -> Luma (rightly)
# made a ZOOM. Michele's fix: BOTH frames are crops of the same photo, the SAME size, at different positions, so the only motion that fits
# between them is a sideways sweep, and everything shown by either frame is inside the photo (the "cage" = the union of the two crops).
# movement -> ((scale, dx, dy) of the first frame, (scale, dx, dy) of the last frame). scale = fraction of width/height kept (same aspect
# ratio as the photo); dx, dy in [-1, 1] = where the crop sits in its free margin (0 centred, -1 left/top edge, +1 right/bottom edge).
# Only sideways / rotating movements are listed: the forward ones (walk_in_explore, approach_facade, walk_through...) are NOT, because
# a push-in has no pair of equal-size crops, so they keep the normal single start frame. A crop pair has no parallax of its own: the model
# must supply it, so these numbers are a starting point to judge on real clips (backlog), not a finished truth.
FRAME_PAIR = {
    "walk_in_gentle":     ((0.85, -1.0, 0.0), (0.85, 1.0, 0.0)),    # lateral slide, left -> right
    "walk_in_turn_left":  ((0.85, 1.0, 0.0), (0.85, -1.0, 0.0)),    # the view moves to the left
    "walk_in_turn_right": ((0.85, -1.0, 0.0), (0.85, 1.0, 0.0)),    # the view moves to the right
    "subtle_rotate":      ((0.92, -0.8, 0.0), (0.92, 0.8, 0.0)),    # very small sweep
    "outward_view":       ((0.85, -1.0, 0.0), (0.85, 1.0, 0.0)),    # balcony / terrace / garden: sweep across the view
}
# stand_look_around is deliberately absent: video_generation remaps it to walk_in_explore (a forward move)


def crop_box(spec, width: int, height: int):
    """(left, top, right, bottom) pixel box for a (scale, dx, dy) crop spec, always inside the photo, same aspect ratio. None if impossible."""
    if not spec or width < 2 or height < 2:
        return None
    scale, dx, dy = spec
    w, h = max(2, round(width * scale)), max(2, round(height * scale))
    left = round((width - w) / 2 + dx * (width - w) / 2)
    top = round((height - h) / 2 + dy * (height - h) / 2)
    left, top = min(max(0, left), width - w), min(max(0, top), height - h)
    return (left, top, left + w, top + h)


def frame_pair_boxes(movement: str, width: int, height: int):
    """((first box), (last box)) for this movement, or None (forward movements, unknown, tiny image)."""
    pair = FRAME_PAIR.get(movement)
    if not pair:
        return None
    a, b = crop_box(pair[0], width, height), crop_box(pair[1], width, height)
    return (a, b) if a and b else None


# ── Camera direction toward an ANCHOR (2026-10-27, Michele's idea) ───────────────────────────────────────────────────────────
# Luma invents things when the camera is free to wander. The photo analysis (vision_analysis.analyse_input, ONE Claude call per photo)
# also names an ANCHOR: the most prominent, safe thing near the middle of the photo (a door, a window, the view, a bed...). The Luma prompt
# then says "push in toward <anchor>" instead of the generic dolly. Real tests (job 6dddfd66, scenes 5 and 1): natural motion, full
# resolution, clip QC pass. ONLY the straight push-in is proven; turning / arc texts exist for the experiments (exp_luma.py anchormove)
# and are NOT used in production until they are tested one by one.
# OFF unless PVS_ANCHOR=1 in the server environment; with it off (or with no anchor for a scene) every prompt is exactly as before.
import os as _os
import re as _re

PRODUCTION_ANCHOR_MOVEMENTS = ("walk_in_explore", "outward_view")   # AFTER video_generation's remaps (stand_look_around -> walk_in_explore)
ANCHOR_UNSAFE = ("mirror", "mirrors", "reflection", "reflective", "reflect", "shiny", "television", "tv", "screen", "monitor",
                 "person", "people", "man", "woman", "child", "children", "kid", "dog", "cat", "pet")
# Anchor criteria v2 (2026-10-27, after the first full job 26d7a774): the anchor must be FAR, near the CENTRE, FIXED and worth looking at.
#   - a DOOR of any kind is animated by Luma (the balcony door moved while the camera approached it): never an anchor
#   - a utilitarian fixture (sink, toilet, bath, radiator, stove, fridge, counter...) is not worth looking at ("looking into the sink")
#   - a NEAR foreground object (railing, fence...) sits low in the frame and pulls the camera DOWN toward the floor, away from the view
#   - mirrors / reflections / screens / people / animals / curtains / plants / water: unsafe or animated
# Matched on word STEMS ("mirrored", "reflecting", "doorway", "sinks"), after the model has already been told the same rules in the prompt.
ANCHOR_UNSAFE_STEMS = ("mirror", "reflect", "televis", "screen", "monitor", "door", "curtain", "blind", "plant", "railing", "balustrade",
                       "handrail", "fence", "sink", "basin", "toilet", "bidet", "bath", "shower", "radiator", "stove", "oven", "hob", "cooktop",
                       "fridge", "refrigerator", "appliance", "faucet", "counter", "water", "fountain", "flame", "ceiling", "lamp", "chandelier")
_ANCHOR_NONE = ("", "none", "null", "n/a", "no", "nothing", "nessuno")
ANCHOR_SIDES = ("left", "center", "right")
DEPTHS = ("shallow", "medium", "deep")

# the strict first-frame text that was part of every approved anchor test (exp_luma.STRICT_ADD)
ANCHOR_STRICT = ("the first frame is the exact and complete starting image: every object visible in any later frame must already be visible "
                 "in the first frame, never add, replace or move any chair, table, plant, lamp, decoration or other furniture, "
                 "and the camera never leaves the area shown in the first frame")
# the motion text that was approved by eye on scenes 5 and 1 (exp_luma.ANCHOR_MOTION)
ANCHOR_MOTION = ("slow straight forward camera push-in toward {anchor}, the camera never moves sideways, never slides left or right and never turns, "
                 "treat nearby furniture as if it were not there: never steer around it and never dodge it, the path is one straight line toward {anchor}, "
                 "the camera stops well before reaching it, smooth continuous motion, no stepping or bobbing, realistic physics")
_MOVE_TAIL = "smooth continuous motion, no stepping or bobbing, realistic physics"
FIRST_FRAME_ONLY = "the camera only ever shows what is already visible in the first frame"


def anchor_enabled() -> bool:
    return _os.environ.get("PVS_ANCHOR", "0").strip().lower() in ("1", "true", "yes")


def clean_anchor(phrase) -> str:
    """The anchor phrase as it may be used, or '' (empty, 'none', too short/long, or about something unsafe: mirror, screen, person, animal)."""
    s = str(phrase or "").strip().strip('."\'`*').strip()
    if s.lower() in _ANCHOR_NONE or not 2 <= len(s) <= 80:
        return ""
    words = _re.findall(r"[a-z']+", s.lower())
    # exact words AND word stems: "mirrored wardrobe" / "reflecting glass" / "screens" are as unsafe as "mirror" (job 26d7a774, scene 3)
    if any(w in _ANCHOR_UNSAFE_SET or w.startswith(ANCHOR_UNSAFE_STEMS) for w in words):
        return ""
    return s


_ANCHOR_UNSAFE_SET = frozenset(ANCHOR_UNSAFE)


def anchor_usable(anchor, side, height="") -> str:
    """The anchor as it may be used (the cleaned phrase) or '': it must pass clean_anchor, sit at the horizontal CENTRE and not in the
    lower part of the frame (a far window or horizon is naturally in the upper part, that is fine). The side / height come from the photo analysis; a missing height counts as 'middle'."""
    a = clean_anchor(anchor)
    if not a or clean_side(side) != "center":
        return ""
    if str(height or "").strip().lower() in ("lower", "bottom", "low"):
        return ""
    return a


def clean_side(side) -> str:
    s = str(side or "").strip().strip('."\'`*').lower()
    return s if s in ANCHOR_SIDES else "center"


def parse_anchor_answer(txt):
    """'the French doors | right' -> ('the French doors', 'right'); side defaults to 'center'. ('', '') when there is no usable anchor."""
    try:
        line = (txt or "").strip().splitlines()[0]
    except IndexError:
        return "", ""
    phrase, _, side = line.partition("|")
    a = clean_anchor(phrase)
    return (a, clean_side(side)) if a else ("", "")


def intent_kwargs(scene) -> dict:
    """The camera-direction arguments of generate_video_single for ONE scene dict: {} when the switch is off or the scene has no usable
    anchor (so a call with ** is then exactly the call as it was). The ONE place both the main pipeline and the scene rework read it."""
    if not anchor_enabled() or not isinstance(scene, dict):
        return {}
    anchor = clean_anchor(scene.get("anchor"))
    if not anchor or clean_side(scene.get("anchor_side")) != "center":      # an anchor near an edge makes the camera TURN toward it (job 26d7a774)
        return {}
    depth = str(scene.get("depth") or "").strip().lower()
    return {"anchor": anchor, "anchor_side": clean_side(scene.get("anchor_side")), "depth": depth if depth in DEPTHS else ""}


def anchor_motion_for(movement, anchor, side="center", depth=None) -> str:
    """The camera instruction of a movement expressed relative to the anchor. Forward movements = the straight push-in approved by eye
    (a shallow room, with a wall or objects close to the camera, gets a much shorter push). Turning movements pan toward an off-centre
    anchor, the sideways one arcs around it: these two are EXPERIMENTAL (exp_luma.py anchormove), never used by production."""
    if movement in ("walk_in_turn_left", "walk_in_turn_right", "subtle_rotate", "stand_look_around") and side in ("left", "right"):
        deg = 8 if movement == "subtle_rotate" else 12
        return (f"slow gentle pan to the {side} of at most {deg} degrees until {anchor} is at the centre of the frame, then stop, "
                f"the camera only turns and does not move forward or sideways, {FIRST_FRAME_ONLY}, " + _MOVE_TAIL)
    if movement == "walk_in_gentle":
        way = side if side in ("left", "right") else "right"
        return (f"very slow short arc around {anchor}: the camera glides less than half a metre to the {way} while turning slightly so that {anchor} "
                f"stays at the centre of the frame, {FIRST_FRAME_ONLY}, treat nearby furniture as if it were not there and never steer around it, " + _MOVE_TAIL)
    if movement == "subtle_rotate":
        return (f"almost static shot, imperceptibly slow push-in toward {anchor} of less than ten centimetres, the camera does not turn, "
                f"{FIRST_FRAME_ONLY}, " + _MOVE_TAIL)
    text = ANCHOR_MOTION.format(anchor=anchor)
    if depth == "shallow":
        text = text.replace("slow straight forward camera push-in", "very slow, very short straight forward camera push-in of less than half a metre", 1)
    return text
