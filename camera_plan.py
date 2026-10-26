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


# ── End frame (2026-10-26, Michele's idea) ───────────────────────────────────────────────────────────────────────────────
# Luma can be given the LAST frame as well as the first. If the last frame is a CROP of the same photo, the clip has to end on
# something that really is inside the photo, so it cannot drift out of the photo's space or invent furniture on the way.
# movement -> (scale, dx, dy): scale = fraction of the width/height kept (same aspect ratio as the photo); dx, dy in [-1, 1] = where the
# crop sits inside the free margin (0 = centred, -1 = left/top edge, +1 = right/bottom edge). None / missing = no end frame.
# A crop has no parallax: the model must invent the 3D motion between the two frames, so these values are a starting point to be
# judged on real clips (backlog), not a finished truth.
END_FRAME_CROP = {
    "approach_facade":    (0.80, 0.0, 0.0),
    "walk_toward":        (0.80, 0.0, 0.0),
    "walk_in_explore":    (0.85, 0.0, 0.0),
    "walk_through":       (0.75, 0.0, 0.0),
    "step_out_onto":      (0.85, 0.0, 0.0),
    "approach_reveal":    (0.90, 0.0, 0.0),
    "outward_view":       (0.90, 0.0, 0.0),
    "walk_in_gentle":     (0.92, 0.6, 0.0),
    "walk_in_turn_left":  (0.88, -0.8, 0.0),
    "walk_in_turn_right": (0.88, 0.8, 0.0),
    "stand_look_around":  (0.88, 0.8, 0.0),
    "subtle_rotate":      (0.95, 0.5, 0.0),
    # reveal_pullback: reverse dolly, no end frame
}


def end_frame_box(movement: str, width: int, height: int):
    """(left, top, right, bottom) pixel box of the end frame for this movement, or None. Always inside the photo, same aspect ratio."""
    spec = END_FRAME_CROP.get(movement)
    if not spec or width < 2 or height < 2:
        return None
    scale, dx, dy = spec
    w, h = max(2, round(width * scale)), max(2, round(height * scale))
    left = round((width - w) / 2 + dx * (width - w) / 2)
    top = round((height - h) / 2 + dy * (height - h) / 2)
    left, top = min(max(0, left), width - w), min(max(0, top), height - h)
    return (left, top, left + w, top + h)
