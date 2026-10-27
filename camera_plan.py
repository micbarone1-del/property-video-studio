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
