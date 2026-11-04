"""Positive Luma prompt with a described last view (2026-11-02, Michele: "prompt positivo con descrizione target frame come standard").

Why: the old Luma rules (video_generation._LUMA_RULES) are ~15 NEGATIONS, and Luma has no negative-prompt parameter. Tests on job 91056c3e
(bathroom: pass/pass twice) used the rules below instead: a positive description of a frozen room, PLUS Claude's two-sentence description of the view the
shot is expected to END on, written from the central 1/scale crop of the real photo. The crop is NEVER sent to Luma (no end frame, no 2D zoom): it is only
the source of the words. Evidence is small (n=2 per scene, one listing); the switch below goes back to the old rules at any time.

  PVS_POSITIVE_PROMPT=0   -> the old _LUMA_RULES, exactly as before. Unset/anything else -> on.
Any failure of the description (no key, bad answer) falls back to the old rules for that clip, logged: a clip is never blocked by this.
This module is the ONLY place for these texts; exp_prompt.py imports them from here.
Cost: one Claude call per clip (a few cents at most); its REAL usage is written next to the clip (<clip>.view.json) and merged into the job's
claude_usage by merge_usage_into_job (called at the two places a clip is generated: the pipeline and the rework runner).
"""
import json
import logging
import os
import re
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

POSITIVE_RULES = (
    "this is a frozen photograph of an empty, still room: every wall, window, door, curtain, piece of furniture, fixture and decoration keeps exactly the same "
    "place, shape, colour, number and state (open or closed) as in the first frame for the whole shot, and the light stays steady, "
    "the only thing that moves is the camera, which makes the movement described above smoothly, at a constant slow speed, "
    "everything in view at the start stays in view and in place while the parts of the room nearest the edges leave the frame, "
    "the shot ends on a view of the same room that contains exactly the same elements as the first frame, "
    "every shadow and every reflection stays as in the source photo and the room holds only what the source photo shows"
)

DESCRIBE_PROMPT = """Image 1 is a photo of a room. Image 2 is the central part of image 1: exactly what will still be in view at the END of a short shot in which the camera glides straight forward.
Write the description of image 2 for a video prompt, as 2 plain sentences of at most 70 words in total, in the present tense, beginning "The shot ends on a view of the room showing ...". Mention only the 6 to 8 most prominent fixed elements.
Name every fixed element you can clearly see in image 2 (furniture, fixtures, openings, wall features) with its count, its position (left, centre, right; foreground, background) and its state (door closed, window with a curtain or without one, tap count and place...). Describe only what is really visible in image 2: if you are not sure that something is there, leave it out. Positive statements only: say what IS there, never what is absent or must not appear.
Answer with JSON only: {"last_view": "..."}"""

# 2026-11-02: appended when the movement director has a plan: the description is written FOR the move (target, direction), to keep Luma on the path
# and give it nothing to invent. Word limit 60 (the whole Luma prompt must not grow: it is about 200 words with the old rules and with these).
PLAN_ADDENDUM = """
The camera move for this shot: {move_text}. Image 2 is the view where this move ends, centred on {target}. Write the description so that it also tells the direction of the move: say what lies on the path between the camera and {target}, what stays at the left and right edges, and what {target} looks like (state, count). Use at most 60 words in total and the 5 to 7 most prominent fixed elements. Mention an element only if you clearly see it in image 2."""

# a straight forward move ends on the central 1/1.3 of the photo; a gentle rotation or lateral move ends on almost the whole photo (PROPOSAL, tested on interiors)
FORWARD_MOVEMENTS = ("walk_in_explore", "walk_toward", "walk_through", "approach_facade")
SCALE_FORWARD = 1.3
SCALE_OTHER = 1.1
OPEN_AIR = ("outdoor", "elevated")          # the tested wording says "room"; for these scenes it is changed to "scene" (NOT yet tested on a real clip)
SIDECAR_SUFFIX = ".view.json"


def enabled() -> bool:
    return os.getenv("PVS_POSITIVE_PROMPT", "1").strip().lower() not in ("0", "false", "no", "off")


def crop_scale(movement: str) -> float:
    return SCALE_FORWARD if movement in FORWARD_MOVEMENTS else SCALE_OTHER


def _scene_words(text: str, space_type: str) -> str:
    if space_type not in OPEN_AIR:
        return text
    for a, b in (("an empty, still room", "a still scene"), ("photo of a room", "photo of a scene"), ("the same room", "the same scene"),
                 ("parts of the room", "parts of the scene"), ("the room holds", "the scene holds"), ("view of the room", "view of the scene")):
        text = text.replace(a, b)
    return text


# 2026-11-03 (Luma support: avoid "move / moving / down"; blind A/B on 360p clips: 0 flawed clips of 15 with the clause below changed, 4 of 15 with the original).
# Default ON since 2026-11-04 (Michele: "se funzionano perche spenti?"); PVS_LUMA_NOMOVE=0 restores the old clause. ONE clause of the rules is swapped.
NOMOVE_FROM = "the only thing that moves is the camera, which makes the movement described above"
NOMOVE_TO = "the only thing that changes is the camera position, which makes the movement described above"


# 2026-11-04 EXPERIMENTAL (off): two candidate root causes of the rushing outliers, tested by the blind A/B (exp_prompt_ab variants N1 / N2) before any default changes.
# N1: the standard addendum asks Claude to say "what lies on the PATH between the camera and {target}" and what {target} looks like, so the description of the end
#     view says "a walkway that leads ... to a closed double glass door": a destination sits in the prompt even when the movement target is near.
PLAN_ADDENDUM_NEUTRAL = """
The camera move for this shot: {move_text}. Image 2 is the view where this move ends, centred on {target}. Describe only what is visible in image 2: what fills the foreground, the centre and the left and right edges, each with its count and state. Write it as a still view, without any movement, path, direction or destination: no words such as toward, along, leads, reaches, ahead or path, and a door, entrance or gate is named only as a part of the wall where it stands. Use at most 60 words in total and the 5 to 7 most prominent fixed elements. Mention an element only if you clearly see it in image 2."""
# N2: the rules paragraph is about 150 of the ~240 words of the prompt; the movement sentence is the first fifth. A short version keeps the same ideas.
SHORT_RULES = ("this is a frozen photograph of a still scene: every wall, window, door, fixture and piece of furniture keeps exactly the same place, shape, colour, number and state "
               "as in the first frame, the light stays steady, only the camera position changes, smoothly at a constant slow speed")


def neutral_enabled() -> bool:
    # 2026-11-04: ON by default after the blind round 4 (N1 0/12 defects vs N 4/12 vs N2 3/12); PVS_DESCRIBE_NEUTRAL=0 restores the old description (rollback)
    return os.getenv("PVS_DESCRIBE_NEUTRAL", "1").strip().lower() not in ("0", "false", "no", "off")


def short_rules_enabled() -> bool:
    return os.getenv("PVS_LUMA_SHORT_RULES", "0").strip().lower() in ("1", "true", "yes", "on")


def plan_addendum() -> str:
    return PLAN_ADDENDUM_NEUTRAL if neutral_enabled() else PLAN_ADDENDUM


def nomove_enabled() -> bool:
    return os.getenv("PVS_LUMA_NOMOVE", "1").strip().lower() not in ("0", "false", "no", "off")


def rules_for(last_view: str, space_type: str = "") -> str:
    """The text that REPLACES _LUMA_RULES in the Luma prompt."""
    rules = POSITIVE_RULES.replace(NOMOVE_FROM, NOMOVE_TO) if nomove_enabled() else POSITIVE_RULES
    if short_rules_enabled():
        rules = SHORT_RULES
    return _scene_words(rules, space_type) + ", " + last_view.strip()


def sidecar_path(clip_path) -> Path:
    return Path(str(clip_path) + SIDECAR_SUFFIX)


def _write(clip_path, data: dict):
    try:
        p = sidecar_path(clip_path)
        old = {}
        if p.exists() and data.get("_merge"):
            old = json.loads(p.read_text(encoding="utf-8"))
        data = {k: v for k, v in data.items() if k != "_merge"}
        old.update(data)
        p.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning(f"[DescribedView] could not write the note next to {clip_path}: {e}")


def describe(photo_path, movement: str, space_type: str, clip_path, scale: float = None, plan: dict = None) -> str:
    """Claude's description of the expected last view ('' on any failure -> the caller keeps the old rules). Writes <clip>.view.json."""
    try:
        from PIL import Image
        import vision_analysis as va
        scale = scale if scale and scale >= 1.0 else crop_scale(movement)     # the movement director gives the real travel; otherwise the tested defaults
        im = Image.open(photo_path).convert("RGB")
        w, h = im.size
        cw, ch = round(w / scale), round(h / scale)
        cx, cy = (plan or {}).get("center") or (0.5, 0.5)       # the movement director's target: the shot ends centred on it, inside the photo
        x0 = min(max(0, round(cx * w - cw / 2)), w - cw)
        y0 = min(max(0, round(cy * h - ch / 2)), h - ch)
        question = _scene_words(DESCRIBE_PROMPT, space_type)
        if plan and plan.get("move") in ("forward", "lateral_left", "lateral_right", "rotate_left", "rotate_right"):
            question = question.replace("Answer with JSON only", _scene_words(plan_addendum(), space_type).format(
                move_text=str(plan.get("sentence", ""))[:220], target=plan.get("target") or "the centre of the frame") + "\nAnswer with JSON only", 1)
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        usage = {}
        try:
            im.crop((x0, y0, x0 + cw, y0 + ch)).save(tmp, quality=92)
            raw = va._claude_vision_call([str(photo_path), tmp], question, 400,
                                         model=va.CLIP_QC_MODEL, usage_out=usage)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        text = str(json.loads(m.group(0)).get("last_view", "")).strip() if m else ""
        if not text or len(text) > 700:
            log.warning(f"[DescribedView] no usable description (len={len(text)}): old rules for this clip")
            _write(clip_path, {"used": False, "reason": "no usable description", "usage": usage, "counted": False})
            return ""
        _write(clip_path, {"used": True, "last_view": text, "scale": scale, "center": [cx, cy], "movement": movement, "usage": usage, "counted": False})
        log.info(f"[DescribedView] {movement} (crop 1/{scale:g}): {text}")
        return text
    except Exception as e:
        log.warning(f"[DescribedView] description failed ({e}): old rules for this clip")
        return ""


def note_prompt(clip_path, prompt: str, positive: bool):
    """The exact prompt sent to Luma, kept next to the clip (it was never logged per clip before)."""
    if positive:
        _write(clip_path, {"prompt": prompt, "positive_prompt": True, "_merge": True})
    else:      # old rules: replace any older note of a previous generation of this clip
        _write(clip_path, {"prompt": prompt, "positive_prompt": False})


def merge_usage_into_job(job: dict, clip_path) -> bool:
    """Adds the REAL Claude usage of the description to job['claude_usage'] once (the note is marked counted). False if nothing to add."""
    try:
        p = sidecar_path(clip_path)
        if not p.exists() or job is None:
            return False
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("counted") or not d.get("usage"):
            return False
        import listing_scraper as ls
        job["claude_usage"] = ls.merge_claude_usage(job.get("claude_usage"), d["usage"])
        d["counted"] = True
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        log.warning(f"[DescribedView] could not add the description cost to the job: {e}")
        return False
