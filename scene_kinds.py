"""scene_kinds.py - the ONE definition of how a scene is classified for the learning loop (2026-11-25).
Shared by learning_loop.py (offline, reads the past) and learning_apply.py (production, reads the rules): one implementation, so what a rule was
learned on is exactly what is matched later. Pure functions, no I/O."""
GENERIC_ANCHORS = ("centre of the frame", "center of the frame", "centre of", "center of", "middle of the")


def anchor_kind(scene):
    a = str((scene or {}).get("anchor") or "").strip().lower()
    if not a:
        return "none"
    return "generic" if any(g in a for g in GENERIC_ANCHORS) else "specific"


def plan_kind(move):
    m = str(move or "").lower()
    return "static" if m in ("subtle_rotate", "static", "hold") else ("forward" if m and m != "?" else "?")


def scene_features(scene, move, cat, tier):
    s = scene or {}
    return {"cat": str(cat or "?"), "move": str(move or "?"), "tier": str(tier or "?"), "plan_kind": plan_kind(move),
            "anchor_kind": anchor_kind(s), "depth": str(s.get("depth") or "?")}
