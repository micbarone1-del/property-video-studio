"""clip_standard.py - the CLIP ACCEPTANCE STANDARD v0, SHADOW MODE (2026-11-05, Michele: reject rules black and white, flags only in validation).
ONE production module (the experiment tools exp_rotation / exp_judge import from here: no second copy).

Standard v0 (calibrated on 126 labelled clips + 228 archive clips, see status.md):
  1. GEOMETRY  new_max = largest share of a sampled frame (0.25 s steps) that lies OUTSIDE the first frame's field of view. new_max > NEW_MAX_LIMIT (0.20) = reject.
  2. CONTENT   the judge (Claude vision, 6 key frames) says "fail" = something invented/animated inside what was already visible, or backward/downward/very fast = reject.
               "review" never rejects (reported only).
  3. standard_verdict = "reject" if 1 or 2 else "pass". Tracking lost = geometry not measured (never a reject by itself).
SHADOW: evaluate() only MEASURES. Nothing here changes a verdict, a rework or a job state. Hooked ONCE, in vision_analysis.analyse_output (first generation AND rework both call it).
ENFORCEMENT (2026-11-05, Michele: "A"): only the MEASURED part (geometry) may change a verdict, and only with PVS_STANDARD_ENFORCE=1 (default OFF): analyse_output then turns the clip verdict into "reject", which pauses the job at the
existing QC gate (operator review) exactly like any other reject; no automatic retry here (a retry inside the first-generation loop would bypass the per-scene cost accounting). The judge never rejects.
Kill switch: PVS_STANDARD_SHADOW=0. Never runs for fake providers or from a test_*.py script. Optional PVS_STANDARD_FEED_NUMBER=1 hands the measured number to the judge (NOT validated yet, default off).
Extra cost: one judge call per clip (about 0.06 USD per video), counted in the job's claude_usage like the existing QC.
"""
import json
import logging
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
NEW_MAX_LIMIT = 0.20
ZOOM_RATE_LIMIT = 0.28        # PROVISIONAL (one clip, bhl): recorded as speed_over_limit, NOT enforced yet
SPEED_WORDS = ("static", "slow", "fast", "very_fast")      # the only values the judge may answer for speed (see JUDGE_PROMPT)
STEP_S = 0.25
WORK_W = 480
MIN_TRACKED = 20
_LOCK = threading.Lock()

JUDGE_PROMPT = """These {n} frames are in time order from a 5 second real-estate video made from ONE still photo (frame 1 is the photo). The camera may glide slowly forward or stay still; everything else in the scene must stay exactly as in frame 1: nothing may appear, disappear, move, animate, flash or deform.
Judge the clip like a strict quality inspector for a real-estate agency:
- invented: anything NOT in frame 1 that shows up later (new buildings or parts of buildings, arches, garages, balconies, doors, windows, staircases, signs, people, animals, black or white flashes). Do not count things that merely come into view at the edges as the camera moves.
- animated: people, vehicles, curtains, flags, water or leaves that MOVE or change.
- direction: where the camera travels, one of "toward_main_subject" (the building / room feature that dominates frame 1 gets closer), "along_street_or_path", "sideways", "backward", "downward", "upward", "static".
- speed: "static", "slow", "fast", "very_fast" (fast = the picture changes a lot within one second).
- verdict: "fail" if something is invented, or people/vehicles animate, or the camera goes away from the main subject, backward or downward, or it is very fast; "review" if the camera drifts sideways/along a path, is fast, you are unsure, or the clip is essentially a STILL PICTURE with no visible camera motion at all; otherwise "pass".
Answer with JSON only: {{"invented": [{{"frames": "3-5", "what": "short"}}], "animated": [{{"frames": "2-6", "what": "short"}}], "direction": "...", "speed": "...", "verdict": "pass", "reason": "one short sentence"}}"""


def read_frames(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        k = WORK_W / f.shape[1]
        frames.append(f if k >= 1 else cv2.resize(f, (WORK_W, round(f.shape[0] * k))))
    cap.release()
    return frames, fps


def compose(frames, fps):
    """list of the cumulative 3x3 transforms first frame -> frame k (one per 0.25 s step, composed similarities as in exp_clipeval.motion), or None when the tracking lost the picture
    in some interval (then nothing is claimed)."""
    step = max(1, round(STEP_S * fps))
    total = np.eye(3)
    out = []
    for i in range(0, len(frames) - step, step):
        a = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        b = cv2.cvtColor(frames[i + step], cv2.COLOR_BGR2GRAY)
        p0 = cv2.goodFeaturesToTrack(a, 300, 0.01, 8)
        if p0 is None or len(p0) < MIN_TRACKED:
            return None
        p1, st, _ = cv2.calcOpticalFlowPyrLK(a, b, p0, None)
        ok = st.ravel() == 1
        if ok.sum() < MIN_TRACKED:
            return None
        M, _ = cv2.estimateAffinePartial2D(p0[ok], p1[ok], method=cv2.RANSAC, ransacReprojThreshold=2.0)
        if M is None:
            return None
        total = np.vstack([M, [0, 0, 1]]) @ total
        out.append(total.copy())
    return out if len(out) >= 4 else None


def measures(frames, fps) -> dict:
    """new_frac = share of the LAST frame outside the first frame; new_max = the largest such share over all the sampled frames (Michele: sampled frames, not only the last)."""
    if len(frames) < 12:
        return {"ok": False, "why": "too few frames"}
    Ts = compose(frames, fps)
    if Ts is None:
        return {"ok": False, "why": "tracking lost"}
    H, W = frames[0].shape[:2]
    quad = np.array([[0, 0], [W, 0], [W, H], [0, H]], np.float32)

    def new_area(T):
        mapped = (T @ np.vstack([quad.T, np.ones(4)])).T[:, :2].astype(np.float32)
        area, _ = cv2.intersectConvexConvex(mapped, quad)
        return max(0.0, min(1.0, 1.0 - float(area) / float(W * H)))
    shares = [new_area(T) for T in Ts]
    T = Ts[-1]
    c = T @ np.array([W / 2, H / 2, 1.0])
    s = math.sqrt(abs(np.linalg.det(T[:2, :2])))
    dur = len(frames) / (fps or 24.0)
    zoom_rate = math.log(s) / dur if s > 0 and dur else 0.0     # = the zoom_rate_mean_per_s of exp_clipeval (checked: bhl 0.302, mfq 0.245)
    return {"ok": True, "new_frac": round(shares[-1], 3), "new_max": round(max(shares), 3), "pan_frac": round(float((c[0] - W / 2) / W), 3), "zoom_net": round(s, 3),
            "zoom_rate": round(zoom_rate, 3)}


def enabled() -> bool:
    if os.getenv("PVS_FAKE_PROVIDERS", "").strip() == "1":
        return False
    v = os.getenv("PVS_STANDARD_SHADOW")
    if v is not None:
        return v.strip().lower() not in ("0", "false", "no", "off")
    return not os.path.basename(sys.argv[0] or "").startswith("test_")


def keyframes(path, n=6) -> list:
    """n evenly spaced frames as temporary JPEGs (the caller deletes them)."""
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out = []
    for idx in np.linspace(0, max(0, total - 2), max(2, int(n))).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, f = cap.read()
        if ok:
            fd, p = tempfile.mkstemp(suffix="_std.jpg")
            os.close(fd)
            cv2.imwrite(p, f, [cv2.IMWRITE_JPEG_QUALITY, 88])
            out.append(p)
    cap.release()
    return out


def parse_judge(raw):
    """Claude's text -> dict with verdict pass/review/fail, or None when unusable."""
    if not raw:
        return None
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b < a:
        return None
    try:
        d = json.loads(raw[a:b + 1])
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    v = str(d.get("verdict") or "").lower()
    d["verdict"] = v if v in ("pass", "review", "fail") else "review"
    return d


def decide(geo: dict, judge) -> tuple:
    """(standard_verdict, reasons). Pure function: the whole rule in one place."""
    reasons = []
    if geo and geo.get("ok") and geo.get("new_max", 0) > NEW_MAX_LIMIT:
        reasons.append(f"new area {geo['new_max']:.2f} of the frame > {NEW_MAX_LIMIT}")
    if judge and judge.get("verdict") == "fail":
        reasons.append("judge: fail - " + str(judge.get("reason") or "")[:140])
    return ("reject" if reasons else "pass"), reasons


def measured_verdict(geo: dict) -> tuple:
    """The part of the standard that is MEASURED (no model opinion): (verdict, reasons); (None, []) when the geometry could not be measured. This is the only part that can be enforced:
    on the 36 watched clips of the validation batch the judge was wrong on most of its rejects, the geometry rule on 1 of 4 (2026-11-05)."""
    if not geo or not geo.get("ok"):
        return None, []
    if geo.get("new_max", 0) > NEW_MAX_LIMIT:
        return "reject", [f"{round(geo['new_max'] * 100)}% of the frame lies outside the original photo's field of view (limit {round(NEW_MAX_LIMIT * 100)}%)"]
    return "pass", []


def enforce() -> bool:
    """PVS_STANDARD_ENFORCE=1 lets the MEASURED rule change the clip QC verdict (default OFF). Needs the shadow evaluation to be on."""
    return enabled() and os.getenv("PVS_STANDARD_ENFORCE", "").strip() == "1"


def evaluate(clip_path, usage_out=None, ask=None, model=None) -> dict:
    """Measures one clip. NEVER raises. `ask(images, prompt, usage_out)` -> text can be injected (tests); default = vision_analysis._claude_vision_call."""
    res = {"standard": "v0", "geo": None, "judge": None, "standard_verdict": None, "reasons": [], "error": None,
           "measured_verdict": None, "measured_reasons": [], "speed_over_limit": None}
    frames_tmp = []
    try:
        frames, fps = read_frames(clip_path)
        if not frames:
            raise ValueError("clip not readable")
        res["geo"] = measures(frames, fps)
        res["measured_verdict"], res["measured_reasons"] = measured_verdict(res["geo"])
        if res["geo"].get("ok"):
            res["speed_over_limit"] = res["geo"].get("zoom_rate", 0) >= ZOOM_RATE_LIMIT
        del frames
        frames_tmp = keyframes(clip_path, 6)
        geo_line = ""
        if os.getenv("PVS_STANDARD_FEED_NUMBER", "").strip() == "1" and res["geo"].get("ok"):
            geo_line = f"\nSoftware measurement: {round(res['geo']['new_max'] * 100)}% of the picture in some frame lies outside the area visible in frame 1."
        prompt = JUDGE_PROMPT.format(n=len(frames_tmp)) + geo_line
        if ask is None:
            import vision_analysis as va
            raw = va._claude_vision_call(frames_tmp, prompt, max_tokens=va.CLIP_QC_MAX_TOKENS, model=model or va.CLIP_QC_MODEL, usage_out=usage_out)
        else:
            raw = ask(frames_tmp, prompt, usage_out)
        res["judge"] = parse_judge(raw)
        if res["judge"] is None:
            res["error"] = "judge answer unusable"
        res["standard_verdict"], res["reasons"] = decide(res["geo"], res["judge"])
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        log.warning(f"[clip_standard] could not evaluate {clip_path}: {e}")
    finally:
        for p in frames_tmp:
            try:
                os.remove(p)
            except Exception:
                pass
    return res


def _file() -> Path:
    p = os.getenv("PVS_STANDARD_SHADOW_FILE")
    return Path(p) if p else Path(os.getenv("PVS_DATA_DIR") or HERE) / "standard_shadow_events.jsonl"


def record(clip_path, res, stage=None) -> bool:
    """One JSON line per evaluated clip (job and scene read from .../<job>/clips/<scene>.mp4). NEVER raises."""
    try:
        p = Path(clip_path)
        g, j = (res.get("geo") or {}), (res.get("judge") or {})
        ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": p.parent.parent.name, "scene": p.stem, "new_max": g.get("new_max"), "new_frac": g.get("new_frac"),
              "geo_ok": g.get("ok"), "judge": j.get("verdict"), "direction": j.get("direction"), "speed": j.get("speed"),
              "standard": res.get("standard_verdict"), "reasons": res.get("reasons"), "error": res.get("error"),
              "measured": res.get("measured_verdict"), "zoom_rate": g.get("zoom_rate"), "speed_over": res.get("speed_over_limit"),
              "pace": res.get("pace")}
        if stage:
            ev["stage"] = stage
        with _LOCK:
            f = _file()
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def summary(path=None) -> dict:
    """FREE: counts of the shadow file. judge_vs_standard etc. for the validation report."""
    f = Path(path) if path else _file()
    ev = []
    try:
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                ev.append(json.loads(ln))
            except Exception:
                pass
    except FileNotFoundError:
        pass
    n = len(ev)
    rej = [e for e in ev if e.get("standard") == "reject"]
    return {"clips": n, "standard_reject": len(rej), "reject_rate": round(len(rej) / n, 3) if n else None,
            "by_geometry": sum(1 for e in rej if (e.get("new_max") or 0) > NEW_MAX_LIMIT), "by_judge": sum(1 for e in rej if e.get("judge") == "fail"),
            "geo_not_measured": sum(1 for e in ev if not e.get("geo_ok")), "errors": sum(1 for e in ev if e.get("error")),
            "judge": {k: sum(1 for e in ev if e.get("judge") == k) for k in ("pass", "review", "fail")},
            # 2026-11-09: the judge's speed word drives the pace fix (clip_pace); a clip whose speed was NOT recognised is monitored here
            "speed": {k: sum(1 for e in ev if e.get("speed") == k) for k in SPEED_WORDS},
            "speed_unknown": sum(1 for e in ev if e.get("speed") not in SPEED_WORDS),
            "speed_unknown_rate": round(sum(1 for e in ev if e.get("speed") not in SPEED_WORDS) / n, 3) if n else None,
            "pace_applied": sum(1 for e in ev if (e.get("pace") or {}).get("applied"))}

# ── Verification of the judge's "new object" claims (2026-11-05, EXPERIMENT: not called by evaluate() yet) ──────────────────────────────────────────────────
VERIFY_PROMPT = """These {n} frames are in time order from a 5 second real-estate video made from ONE still photo (frame 1 is the photo itself).
A first inspector claims this about the clip: {claims}
Your job is to CHECK the claim, not to repeat it. For each claimed object or change decide:
- "real_invention": clearly NOT in frame 1 (not even small, far away, dark, behind something or reflected) and clearly present in a later frame, as a solid object or a clear change of what frame 1 shows (a new wall, door, furniture, building, person, flame, bird, a lit light that was off...)
- "already_visible": it is already in frame 1 (maybe small, far, dark or partly hidden) and only looks bigger or clearer because the camera moves closer
- "edge_reveal": it is a part of the same room/street that simply comes into view at the edge as the camera moves; nothing was changed or invented
- "artefact": only a compression/blur/noise difference, no object
- "not_in_clip": the frames do not show it
Moving cars or people far away that look natural, and a TV screen changing, are NOT invented objects: mark them "natural_motion". Mark "deformed" only for unrealistic melting, stretching or warping.
Answer with JSON only: {{"claims": [{{"what": "short", "truth": "real_invention", "evidence": "one short sentence naming frames"}}], "confirmed": true}}
"confirmed" is true only if at least one claim is "real_invention" or "deformed"."""


def claims_text(judge: dict) -> str:
    j = judge or {}
    parts = [f"invented in frames {x.get('frames')}: {x.get('what')}" for x in (j.get("invented") or []) if isinstance(x, dict)]
    parts += [f"animated in frames {x.get('frames')}: {x.get('what')}" for x in (j.get("animated") or []) if isinstance(x, dict)]
    if j.get("reason"):
        parts.append(f"summary: {j['reason']}")
    return " | ".join(parts) or "something new appears"


def verify(clip_path, judge, usage_out=None, ask=None, model=None) -> dict:
    """Second, focused look at the judge's claims. NEVER raises. Returns {"confirmed": bool|None, "claims": [...], "error": str|None}."""
    res = {"confirmed": None, "claims": [], "error": None}
    frames_tmp = []
    try:
        frames_tmp = keyframes(clip_path, 6)
        if len(frames_tmp) < 2:
            raise ValueError("clip not readable")
        prompt = VERIFY_PROMPT.format(n=len(frames_tmp), claims=claims_text(judge))
        if ask is None:
            import vision_analysis as va
            raw = va._claude_vision_call(frames_tmp, prompt, max_tokens=va.CLIP_QC_MAX_TOKENS, model=model or va.CLIP_QC_MODEL, usage_out=usage_out)
        else:
            raw = ask(frames_tmp, prompt, usage_out)
        d = parse_judge_like(raw)
        if d is None:
            res["error"] = "verification answer unusable"
        else:
            res["claims"] = d.get("claims") or []
            bad = [c for c in res["claims"] if isinstance(c, dict) and c.get("truth") in ("real_invention", "deformed")]
            res["confirmed"] = bool(bad)
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        for p in frames_tmp:
            try:
                os.remove(p)
            except Exception:
                pass
    return res


def parse_judge_like(raw):
    """Any JSON object in the text, or None."""
    if not raw:
        return None
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b < a:
        return None
    try:
        d = json.loads(raw[a:b + 1])
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def contact_sheet(clip_path, out_path, caption="") -> bool:
    """One JPEG with the 6 key frames (3 x 2) and a caption: what Michele opens to look at a disputed clip."""
    ps = keyframes(clip_path, 6)
    try:
        ims = [cv2.imread(p) for p in ps]
        if len(ims) < 6 or any(i is None for i in ims):
            return False
        ims = [cv2.resize(i, (640, 360)) for i in ims]
        grid = np.vstack([np.hstack(ims[0:3]), np.hstack(ims[3:6])])
        pad = np.full((60, grid.shape[1], 3), 255, np.uint8)
        cv2.putText(pad, str(caption)[:110], (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        return bool(cv2.imwrite(str(out_path), np.vstack([pad, grid]), [cv2.IMWRITE_JPEG_QUALITY, 85]))
    finally:
        for p in ps:
            try:
                os.remove(p)
            except Exception:
                pass



if __name__ == "__main__":
    print(json.dumps(summary(), indent=1))
