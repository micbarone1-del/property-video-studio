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
