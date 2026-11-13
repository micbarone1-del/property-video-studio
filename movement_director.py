"""Movement director (2026-11-02, Michele: "i movimenti devono essere guidati da Claude in base a profondita e anchor, non predefiniti").

Before: the camera movement of a Luma clip came from a fixed table (camera_plan / video_generation._LUMA_MOVEMENT_TOKENS) chosen by room type only.
Now: Claude looks at the photo and DECIDES the move (forward, short sideways glide, small rotation, or almost static), how far it may travel,
and writes the movement sentence. Code never invents a movement: it only (1) validates Claude's answer against the lessons learned and
(2) refuses what the environment does not allow (a sideways move in a shallow/small room, in portrait, with a bulky foreground object or a mirror).
Those two are SAFETY GATES, not a preset: inside them the agent takes the risk (Michele: "dobbiamo dare il rischio all'agente").

  PVS_DIRECTOR=1  -> on (default OFF until the paid experiment is approved). Anything else -> the old table, exactly as before.
Failure policy: no key / no answer at all -> plan() returns None and the caller keeps the old movement table for that clip.
An answer that fails validation -> a SAFE plan (proven straight push-in toward the centre, or almost static in a shallow room), recorded as such.
Aerial / drone photos: the plan is almost static and carries aerial=True (a drone view may show a local landmark, not the property): the
photo selection decides whether to use it at all (open item), the camera never flies toward anything.

History (Michele wants to examine Claude's reasoning): every call appends one entry to <clip>.plan.json (input hints, QC feedback of the
previous attempt, raw answer, validation problems, final plan, real usage). merge_into_job copies the entries into job["director_history"]
and the Claude cost into job["claude_usage"], once each. One implementation: first generation and rework both reach plan() through
video_generation.generate_video_single.
"""
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".plan.json"
MOVES = ("forward", "lateral_left", "lateral_right", "rotate_left", "rotate_right", "static")
SIDEWAYS = ("lateral_left", "lateral_right", "rotate_left", "rotate_right")
TRAVEL_SCALE = {"short": 1.12, "medium": 1.25, "long": 1.4}      # crop scale of the expected last view (described_view); same numbers the tests used
DEPTH_MAX_TRAVEL = {"shallow": "short", "medium": "medium", "deep": "long"}
SIDEWAYS_SCALE = 1.1
STATIC_SCALE = 1.05
MAX_WORDS = 75
MAX_ROTATION_DEG = 12
BANNED = ("orbit", "360", "reveal", "rise", "rising", "descend", "crane", "tilt", "zoom", "fast", "quick", "whip", "backward", "reverse",
          "pull back", "pull-back", "turn around", "spin", "mirror", "reflection", "door", "curtain", "behind the", "around the")
TAIL = "smooth continuous motion at a constant slow speed, no stepping or bobbing, realistic physics"
_TRAVEL_ORDER = ("short", "medium", "long")

PROMPT = """You are the camera director of a real-estate video made from ONE still photo. An image-to-video model (Luma) will animate the photo with the camera move you write.
Decide the safest move that still looks good, and write it. Reply with ONLY a JSON object.

What the model can and cannot do (lessons learned on real clips):
- A slow, straight, constant-speed move FORWARD never shows anything new: everything that appears was already in the photo. This is the safe default.
- A sideways glide or a rotation brings NEW content in from the edges of the frame, and the model then invents it (a shelving unit that did not exist). Choose
  one ONLY if the room is deep enough and open enough that the new content at the edges is clearly just more of the same wall or floor, and nothing bulky or
  unusual sits near the edges. When in doubt choose forward or static. Never combine moves.
- The camera keeps the same height and the same direction for the whole shot. It never rises, drops, orbits, pulls back or zooms.
- Stop well before any furniture, wall or object: shallow rooms (wall or furniture close to the camera) get a very short move or none.
- Aim at something FAR, fixed and worth looking at near the centre of the frame (far wall, window with a view, far end of the space, bed, sofa area). Never aim at
  a door, mirror or other reflective surface, curtain, plant, water, screen, person, animal or a utilitarian fixture (sink, toilet, bath, radiator, stove).
- Photo seen from the AIR (drone, map, satellite) or taken from a high point looking clearly DOWN at the street, roofs or garden below (view "aerial"): move "static", whatever it shows. Pushing forward over such a view makes the video model drop the camera and invent the ground.
- Facade and outdoor photos: an EXTREMELY slow advance of less than three metres toward the building or the view, at the same height, stopping well before any gate, wall or railing.
- Write in positive terms (what the camera DOES). No negations, no list of things that must not happen.

Facts from the photo analysis (may be wrong, trust your own eyes): {facts}
{feedback}
JSON keys:
 "view": "interior" | "ground" | "aerial"   (ground = outdoors at ground level; aerial = drone, map, or a high viewpoint looking down)
 "move": one of forward, lateral_left, lateral_right, rotate_left, rotate_right, static
 "target": a short English noun phrase for the far fixed thing the camera heads toward (forward) or keeps in the centre, or "centre of the frame". A forward target MUST sit near the horizontal middle of the photo (target_x between 0.42 and 0.58) and its phrase names no side ("far right wall", "left corner"): the video model turns the camera towards any target that is off to one side. If the interesting thing is at a side, use "centre of the frame"
 "target_x", "target_y": where the target sits in the photo, as fractions from 0 to 1 (x from the left edge, y from the top edge); the shot ends centred on it
 "travel": "short" | "medium" | "long"   (forward: how far the camera glides; sideways moves ignore this)
 "risk": "low" | "medium" | "high"   (your honest chance that the model invents something with the move you chose)
 "sentence": the camera instruction for the video prompt, English, one sentence of at most 60 words, present tense. Forward: say "slow straight forward camera push-in toward <target>",
   that the camera keeps the same height and direction and stops well before it. Sideways glide: less than half a metre. Rotation: say "at most N degrees" with N <= 12.
   Static: "almost static shot with imperceptibly subtle depth parallax".
 "bulky_near_camera": true | false   (a large plant, curtain, furniture or other bulky object stands close to the camera near an edge or low in the frame)
 "mirror_visible": true | false   (a mirror, mirrored wardrobe or large glass surface is in the photo, anywhere)
 "reason": at most 40 words: why this move for this room (depth, what is at the edges, what could go wrong)."""


# 2026-11-03 (Michele, A/B on 360p clips of job 3fcff5a9): "se dai un obiettivo a Luma in 5 s cercherà di arrivarci in 5 s": the deep facade scene aimed at "entrance and far row
# of houses" and the camera rushed (3 clips of 4 too fast, one cut across the grass); shortening the written travel (G) did not help, only the target distance matters.
# NEAR target is now the STANDARD (default ON since 2026-11-04, Michele: "se funzionano perche spenti?"; PVS_DIRECTOR_NEAR=0 restores the old FAR-target text).
# It swaps three sentences of the prompt: the target is a NEAR/middle-distance fixed feature that can be reached calmly in five seconds.
# The anchor / target / described_view principle is kept: there is still a target, it is only close enough to reach slowly.
_FAR_LINE = """- Aim at something FAR, fixed and worth looking at near the centre of the frame (far wall, window with a view, far end of the space, bed, sofa area). Never aim at
  a door, mirror or other reflective surface, curtain, plant, water, screen, person, animal or a utilitarian fixture (sink, toilet, bath, radiator, stove)."""
_FACADE_LINE = """- Facade and outdoor photos: an EXTREMELY slow advance of less than three metres toward the building or the view, at the same height, stopping well before any gate, wall or railing."""
_TARGET_PHRASE = """a short English noun phrase for the far fixed thing the camera heads toward (forward) or keeps in the centre, or "centre of the frame"."""
NEAR_REPLACEMENTS = (
    (_FAR_LINE, """- Aim at something NEAR enough to reach calmly within the five seconds of the shot: a fixed feature in the foreground or middle distance, about a third of the way
  into the visible depth (the nearest part of the paved yard or drive, a stretch of the near wall, the sofa or table area). The video model tries to ARRIVE at its target
  before the shot ends, so a far target makes the camera rush: in a deep scene (long drive, garden, large hall) never aim at the far background. Never aim at
  a door, entrance, gate, mirror or other reflective surface, curtain, plant, water, screen, person, animal or a utilitarian fixture (sink, toilet, bath, radiator, stove)."""),
    (_FACADE_LINE, """- Facade and outdoor photos: aim at the ground or the nearest fixed feature in front of the building (the paved yard, the drive, the lawn edge), not at the building or its
  entrance: an EXTREMELY slow advance of a few metres at the same height, stopping well before any gate, wall or railing."""),
    (_TARGET_PHRASE, """a short English noun phrase for the NEAR fixed thing the camera heads toward (forward) or keeps in the centre, or "centre of the frame"."""),
)


# 2026-11-04 (blind rounds 1 and 3, judged by Michele): the NEAR rule above lets the director choose the FLOOR or the ground as the target ("the floor in the middle of the room",
# "asphalt road surface ahead"): the camera then tilts down to the floor (e7f516e3 scenes 0 and 1) or runs along the road (facades). EYE: the target is a vertical fixed feature at about
# eye level, and a deterministic guard (_too_low) sends any floor / ground / low target to the centre of the frame. ON by default since 2026-11-04 (Michele approved after the blind round 4:
# 0 clips of 36 tilted down, against 2 of 24 in round 3 with the floor targets); PVS_DIRECTOR_EYE=0 restores the NEAR text exactly (rollback). Rollback commit of the repo: 4eeccb6.
_EYE_NEAR = """- Aim at a fixed VERTICAL feature at about eye level, NEAR enough to reach calmly within the five seconds of the shot: a stretch of the near or middle wall, a window, the front of the
  sofa, table or counter (not the floor, the ground, the road or paving: a low target makes the camera tilt down). The video model tries to ARRIVE at its target before the shot ends,
  so a far target makes the camera rush: in a deep scene (long drive, garden, large hall) never aim at the far background. Never aim at
  a door, entrance, gate, mirror or other reflective surface, curtain, plant, water, screen, person, animal or a utilitarian fixture (sink, toilet, bath, radiator, stove)."""
_EYE_FACADE = """- Facade and outdoor photos: aim at the building itself, at a wall section or a window of its front at about eye level (never the ground, the road, the yard or the lawn): an EXTREMELY slow
  advance of a few metres at the same height, stopping well before any gate, wall or railing."""
EYE_REPLACEMENTS = ((NEAR_REPLACEMENTS[0][1], _EYE_NEAR), (NEAR_REPLACEMENTS[1][1], _EYE_FACADE))
LOW_WORDS = re.compile(r"\b(floor|ground|road|asphalt|paving|pavement|paved|tiles?|tiled|yard|lawn|drive|carpet|grass|street|path|walkway)\b", re.I)
LOW_Y = 0.68


def eye_enabled() -> bool:
    return os.getenv("PVS_DIRECTOR_EYE", "1").strip().lower() not in ("0", "false", "no", "off")


def _too_low(raw: dict, target: str) -> bool:
    """A forward target on the floor / ground (words) or low in the photo (target_y): the camera would tilt down or follow the road."""
    if target and LOW_WORDS.search(target):
        return True
    try:
        return float(raw.get("target_y")) > LOW_Y
    except (TypeError, ValueError):
        return False


def near_enabled() -> bool:
    return os.getenv("PVS_DIRECTOR_NEAR", "1").strip().lower() not in ("0", "false", "no", "off")


def prompt_text() -> str:
    """The director prompt: the near-target version (standard), or with PVS_DIRECTOR_NEAR=0 the old far-target one. ONE place, used by plan()."""
    out = PROMPT
    if near_enabled():
        for a, b in NEAR_REPLACEMENTS:
            out = out.replace(a, b)
        if eye_enabled():
            for a, b in EYE_REPLACEMENTS:
                out = out.replace(a, b)
    return out


# ── switch ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def enabled() -> bool:
    return os.getenv("PVS_DIRECTOR", "0").strip().lower() in ("1", "true", "yes", "on")


# ── pure helpers (tested without Claude) ────────────────────────────────────────────────────────────────────────────────────
def _clip_scale(travel: str) -> float:
    return TRAVEL_SCALE.get(travel, TRAVEL_SCALE["short"])


def _cap_travel(travel: str, hints: dict) -> str:
    """Travel can never exceed what the room depth allows; outdoor / elevated scenes and bulky foreground objects are held to 'short'
    (job 4c34217d: the facade advance ran past a gate that was very close to the wall)."""
    t = travel if travel in _TRAVEL_ORDER else "short"
    cap = DEPTH_MAX_TRAVEL.get(str(hints.get("depth") or "").lower(), "medium")
    if hints.get("space_type") in ("outdoor", "elevated", "small", "corridor") or hints.get("foreground_risk"):
        cap = "short"
    return t if _TRAVEL_ORDER.index(t) <= _TRAVEL_ORDER.index(cap) else cap


def sideways_allowed(hints: dict) -> str:
    """'' when a sideways move / rotation is allowed here, else the reason why not (the environment gate, not a preset)."""
    if hints.get("output_format") == "portrait":
        return "portrait frame (too narrow: new content enters at once)"
    if str(hints.get("depth") or "").lower() not in ("medium", "deep"):
        return "room not deep enough"
    if hints.get("space_type") in ("small", "corridor", "outdoor", "elevated"):
        return f"{hints.get('space_type')} space"
    if hints.get("foreground_risk"):
        return "bulky object near the camera"
    if hints.get("reflective_surface") in ("small", "large"):
        return "mirror or large glass in view"
    return ""


def forward_sentence(target: str, slow: bool = False) -> str:
    """The positive forward-move sentence (2026-11-02, after jobs 73fed155 / de90cbaf / 50472245: the old negative CENTRE_MOTION text was the safe plan in
    6 of 18 scenes and 3 of those 6 were flagged or rejected, one of them turning the camera towards the dining area). Slow scenes (facade, outdoors, terrace)
    say 'very slow' and a total advance of less than three metres: Luma runs at the facade even when told 'slow' (jobs 4c34217d, 73fed155)."""
    if slow:
        return (f"Very slow straight forward camera push-in toward {target}, advancing less than three metres in total, the camera keeps the same height "
                f"and direction and stops well before it, {TAIL}")
    return f"Slow straight forward camera push-in toward {target}, the camera keeps the same height and direction and stops well before it, {TAIL}"


def _is_slow_scene(hints: dict) -> bool:
    return hints.get("space_type") in ("outdoor", "elevated")


def safe_plan(hints: dict, why: str, aerial: bool = False) -> dict:
    """The plan used when Claude's answer is unusable: a straight push-in toward the centre of the frame (forward_sentence), or an almost
    static shot where the room is shallow / small / aerial. Never anything the lessons learned flag."""
    import camera_plan
    still = aerial or str(hints.get("depth") or "").lower() == "shallow" or hints.get("space_type") in ("small", "corridor")
    if still:
        import video_generation as vg
        return {"move": "static", "sentence": vg._LUMA_MOVEMENT_TOKENS["subtle_rotate"], "scale": STATIC_SCALE, "risk": "low",
                "target": "", "travel": "short", "aerial": aerial, "source": "fallback", "reason": f"safe plan: {why}"}
    return {"move": "forward", "sentence": forward_sentence(camera_plan.CENTRE_ANCHOR, _is_slow_scene(hints)), "scale": _clip_scale("short"), "risk": "low",
            "target": camera_plan.CENTRE_ANCHOR, "travel": "short", "aerial": aerial, "source": "fallback", "reason": f"safe plan: {why}",
            "slow": _is_slow_scene(hints)}


def validate(raw: dict, hints: dict):
    """(plan or None, problems). Plan = Claude's decision after the environment gates; None = unusable (caller uses safe_plan)."""
    import camera_plan
    problems = []
    if not isinstance(raw, dict):
        return None, ["answer is not a JSON object"]
    hints = dict(hints)     # Claude's own sight adds to what the analysis stored: a mirror or bulky object it sees closes the gates too
    if str(raw.get("bulky_near_camera")).strip().lower() in ("true", "yes", "1"):
        hints["foreground_risk"] = True
    if str(raw.get("mirror_visible")).strip().lower() in ("true", "yes", "1") and hints.get("reflective_surface") not in ("small", "large"):
        hints["reflective_surface"] = "large"
    move = str(raw.get("move", "")).strip().lower()
    view = str(raw.get("view", "")).strip().lower()
    risk = str(raw.get("risk", "")).strip().lower()
    sentence = " ".join(str(raw.get("sentence", "")).split())
    target = str(raw.get("target", "")).strip()
    if move not in MOVES:
        problems.append(f"unknown move {move!r}")
    if risk not in ("low", "medium", "high"):
        problems.append(f"unknown risk {risk!r}")
    if not sentence:
        problems.append("empty sentence")
    elif len(sentence.split()) > MAX_WORDS:
        problems.append(f"sentence too long ({len(sentence.split())} words)")
    low = sentence.lower()
    for w in BANNED:
        if re.search(r"\b" + re.escape(w), low):
            problems.append(f"banned word {w!r} in the sentence")
    if problems:
        return None, problems
    aerial = view == "aerial"
    downgraded = ""
    if aerial and move != "static":
        move, downgraded = "static", "aerial view: static"
    if move in SIDEWAYS:
        why = sideways_allowed(hints)
        if not why and risk != "low":
            why = f"Claude's own risk is {risk}"
        if not why and move.startswith("rotate"):
            degs = [int(x) for x in re.findall(r"(\d+)\s*degrees?", low)]
            if not degs or max(degs) > MAX_ROTATION_DEG:
                return None, [f"rotation without a clear limit of at most {MAX_ROTATION_DEG} degrees"]
        if not why:
            side = "left" if move.endswith("left") else "right"
            if side not in low:
                return None, [f"sentence does not say {side}"]
        if why:
            downgraded = f"{move} not allowed ({why})"
            # a sideways request that the environment refuses becomes the SAFE plan, not Claude's sentence for another move
            sp = safe_plan(hints, downgraded, aerial)
            sp["claude_target"], sp["claude_risk"], sp["adjusted"] = target, risk, downgraded
            return sp, []
    if move == "forward":
        if not re.search(r"forward|push-in|advance|dolly", low):
            return None, ["forward move whose sentence does not say forward"]
        tgt_ok = camera_plan.clean_anchor(target) if target and target.lower() != camera_plan.CENTRE_ANCHOR else camera_plan.CENTRE_ANCHOR
        unsafe = ""
        if not tgt_ok:
            unsafe = f"target {target!r} unsafe or empty"
        elif hints.get("reflective_surface") in ("small", "large") and re.search(r"glass|mirror", tgt_ok.lower()):
            unsafe = f"target {target!r} is glass while a mirror is in view"
        elif _off_centre(raw, tgt_ok):
            unsafe = f"target {target!r} is off to one side (the video model turns the camera towards it)"
        elif eye_enabled() and _too_low(raw, tgt_ok):
            unsafe = f"target {target!r} is on the floor or ground, or low in the photo (the camera would tilt down)"
        if unsafe:
            # keep Claude's decision (a forward move) and only change WHERE it heads: the centre of the frame, in the positive sentence
            downgraded = f"retargeted to the centre: {unsafe}"
            target = camera_plan.CENTRE_ANCHOR
            sentence = forward_sentence(target, _is_slow_scene(hints))
            low = sentence.lower()
        else:
            target = tgt_ok
            if _is_slow_scene(hints):
                sentence = forward_sentence(target, True)      # slow scenes always get the tested very-slow wording
    if move == "static" and not aerial and not re.search(r"static|still", low):
        return None, ["static move whose sentence does not say static"]
    travel = _cap_travel(str(raw.get("travel", "short")).strip().lower(), hints)
    scale = _clip_scale(travel) if move == "forward" else (SIDEWAYS_SCALE if move in SIDEWAYS else STATIC_SCALE)
    if move == "static":
        # a static plan is not Claude's free text for another move: the proven almost-static token
        import video_generation as vg
        sentence = vg._LUMA_MOVEMENT_TOKENS["subtle_rotate"]
    elif TAIL not in sentence and "constant" not in low:
        sentence = sentence.rstrip(".") + ", " + TAIL
    plan = {"move": move, "sentence": sentence, "center": _center(raw) if (move == "forward" and not downgraded) else (0.5, 0.5), "scale": scale, "risk": risk, "target": target, "travel": travel, "aerial": aerial,
            "source": "claude", "reason": str(raw.get("reason", ""))[:300], "slow": bool(move == "forward" and _is_slow_scene(hints))}
    if downgraded:
        plan["adjusted"] = downgraded
    return plan, []


# 2026-11-13 (job b05655b9 scene 1, Michele): a target at x=0.38 (orange sofa, a little left of the middle) made Luma turn the camera and show a wall that is not in
# the photo, although it passed the old 0.3-0.7 band. The band is now narrow: only a target on the camera's own axis keeps the straight push-in; anything else
# becomes 'the centre of the frame'. ONE place: the guard below uses these two numbers, the director's question (text above) must say the same (test MD75).
CENTRAL_X_MIN, CENTRAL_X_MAX = 0.42, 0.58
SIDE_WORDS = re.compile(r"\b(left|right|corner|side|edge)\b", re.I)


def _off_centre(raw: dict, target: str) -> bool:
    """2026-11-03 (job 3fcff5a9 scene 2): 'toward the glazed French doors on the far right wall' made Luma turn the camera to the right and invent what
    lies beyond the photo. A forward target must be near the horizontal middle, and its phrase must name no side. The centre of the frame is the cure."""
    import camera_plan
    if target and target.lower() != camera_plan.CENTRE_ANCHOR and SIDE_WORDS.search(target):
        return True
    try:
        x = float(raw.get("target_x"))
    except (TypeError, ValueError):
        return False
    return x < CENTRAL_X_MIN or x > CENTRAL_X_MAX


def _center(raw: dict):
    """(x, y) the shot ends centred on: the target's place in the photo, kept near the middle (a far target is near it anyway; the crop
    stays inside the photo). Missing or unusable numbers -> the exact centre."""
    out = []
    for k in ("target_x", "target_y"):
        try:
            v = float(raw.get(k))
        except (TypeError, ValueError):
            v = 0.5
        out.append(round(min(max(v, 0.35), 0.65), 3))
    return tuple(out)


def _facts(hints: dict) -> str:
    keys = ("room", "space_type", "size", "depth", "anchor", "anchor_side", "anchor_height", "foreground_risk", "reflective_surface", "output_format")
    return "; ".join(f"{k}={hints[k]}" for k in keys if hints.get(k) not in (None, "", "none"))


def qc_feedback_for(job: dict, scene_idx, scene_id=None) -> str:
    """Text for a REWORK: the issues the clip QC found on the previous attempt of this scene (plan() adds the move that attempt used),
    so Claude changes the approach (rework used to reuse the very same prompt and give the same result)."""
    parts = []
    try:
        for q in reversed((job or {}).get("qc_results") or []):
            if q.get("type") == "video" and q.get("scene") == scene_idx and q.get("issues"):
                parts.append("clip QC issues: " + "; ".join(str(x) for x in q["issues"])[:400])
                break
    except Exception:
        pass
    try:    # the first generation wrote its plan under another clip file name (scene_NNN.mp4): the job history links it by scene id
        for e in reversed((job or {}).get("director_history") or []):
            if scene_id and e.get("scene_id") == scene_id and e.get("plan"):
                pl = e["plan"]
                parts.append(f"previous attempt used move={pl.get('move')}: {str(pl.get('sentence', ''))[:200]}")
                break
    except Exception:
        pass
    return " | ".join(parts)


# ── sidecar history ───────────────────────────────────────────────────────────────────────────────────────────────────────
def sidecar_path(clip_path) -> Path:
    return Path(str(clip_path) + SIDECAR_SUFFIX)


def read_history(clip_path) -> dict:
    try:
        return json.loads(sidecar_path(clip_path).read_text(encoding="utf-8"))
    except Exception:
        return {"entries": []}


def _append(clip_path, entry: dict):
    try:
        d = read_history(clip_path)
        d.setdefault("entries", []).append(entry)
        sidecar_path(clip_path).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning(f"[Director] could not write the history next to {clip_path}: {e}")


def last_plan(clip_path):
    for e in reversed(read_history(clip_path).get("entries", [])):
        if e.get("plan"):
            return e["plan"]
    return None


# ── Claude call ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _claude(photo_path, prompt, usage):
    import vision_analysis as va
    return va._claude_vision_call([str(photo_path)], prompt, 1000, model=va.CLIP_QC_MODEL, usage_out=usage)


def plan(photo_path, hints: dict, clip_path, qc_feedback: str = ""):
    """The plan for ONE clip, or None when Claude could not be reached at all (the caller then keeps the old movement table).
    hints: room, space_type, size, depth, anchor, anchor_side, anchor_height, foreground_risk, reflective_surface, output_format."""
    try:
        prev = last_plan(clip_path)
        if prev and "previous attempt" not in qc_feedback:
            qc_feedback = (qc_feedback + " | " if qc_feedback else "") + f"previous attempt used move={prev.get('move')}: {str(prev.get('sentence', ''))[:200]}"
        feedback = f"\nThis is a REWORK: the previous clip was rejected or flagged ({qc_feedback}). Choose a different, SAFER approach.\n" if qc_feedback else ""
        prompt = prompt_text().format(facts=_facts(hints) or "none", feedback=feedback)
        usage = {}
        raw_text = _claude(photo_path, prompt, usage)
        if not raw_text:
            _append(clip_path, {"ts": int(time.time()), "hints": hints, "qc_feedback": qc_feedback, "raw": None, "plan": None,
                                "problems": ["no answer from Claude"], "usage": usage, "counted": False})
            return None
        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
        try:
            raw = json.loads(m.group(0)) if m else None
        except Exception:
            raw = None
        result, problems = validate(raw, hints)
        if result is None:
            aerial = isinstance(raw, dict) and str(raw.get("view", "")).lower() == "aerial"
            result = safe_plan(hints, "; ".join(problems) or "unreadable answer", aerial)
        _append(clip_path, {"ts": int(time.time()), "hints": hints, "qc_feedback": qc_feedback, "raw": raw if raw is not None else raw_text[:800],
                            "plan": result, "problems": problems, "usage": usage, "counted": False})
        log.info(f"[Director] {result['source']}: move={result['move']} travel={result.get('travel')} risk={result['risk']} :: {result['sentence'][:160]}")
        return result
    except Exception as e:
        log.warning(f"[Director] failed ({e}): old movement table for this clip")
        return None


def merge_into_job(job: dict, clip_path, scene_id=None) -> bool:
    """Adds the real Claude cost of the entries not yet counted to job['claude_usage'] and copies them into job['director_history'] (once each)."""
    try:
        if job is None:
            return False
        d = read_history(clip_path)
        new = [e for e in d.get("entries", []) if not e.get("counted")]
        if not new:
            return False
        import listing_scraper as ls
        for e in new:
            if e.get("usage"):
                job["claude_usage"] = ls.merge_claude_usage(job.get("claude_usage"), e["usage"])
            e["counted"] = True
            job.setdefault("director_history", []).append({"scene_id": scene_id, "clip": Path(str(clip_path)).name, **{k: v for k, v in e.items() if k != "counted"}})
        sidecar_path(clip_path).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        log.warning(f"[Director] could not add the plan history/cost to the job: {e}")
        return False
