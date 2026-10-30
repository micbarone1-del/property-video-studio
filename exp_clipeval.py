"""
exp_clipeval.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-10-30). Evaluates a PRODUCED clip (not a still), the check the 'lean' direction needs.

Two independent readings of the same clip:
 A) MOTION (free, local, OpenCV): tracks features between frames 0.25 s apart and fits a similarity (scale, shift of the picture centre) per interval:
      zoom rate per second     -> accel = (zoom rate of the LAST second) / (zoom rate of the FIRST second); 1.0 = steady; part of any growth is natural perspective
      path wobble              -> sideways / vertical drift of the picture centre per interval: number of direction reversals and their size (zig-zag)
      jerk                     -> largest interval-to-interval change of the zoom rate relative to its mean
 B) CONTENT (Claude vision, cents, only with --claude): 6 key frames in time order; asks for elements that appear, disappear, animate or deform
      (ghost curtain, extra tap, bending door / radiator) while ignoring what merely leaves the frame or gets bigger by approaching.
It only reports numbers and findings: no pass/fail thresholds are proposed here until they are checked against clips with known defects.

  python3 exp_clipeval.py [--claude] LABEL=path.mp4 [LABEL=path.mp4 ...]
Key frames are saved in jobs/_test_scratch (never inside a job).
"""
import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_endframe as ef

STEP_S = 0.25
WORK_W = 480

CONTENT_PROMPT = """These {n} frames are in time order from a 5 second real-estate clip. The camera moves slowly forward; the room itself must stay completely STILL, with nothing appearing, disappearing, moving, animating or changing shape. Compare every frame with frame 1.
Report only real problems: elements that APPEAR (not just come into view at the edges), DISAPPEAR, MOVE or ANIMATE (curtains waving or falling into place, water, fabric, people, lights, steam), CHANGE (a second tap, a different object, a door or window opening or closing), or DEFORM (door, window frame, radiator, fixture, furniture bending, melting or stretching differently from the room). Do NOT report things that merely leave the frame at the edges or get bigger because the camera comes closer.
Answer with JSON only: {{"static_scene_ok": true, "events": [{{"frames": "3-5", "what": "short description"}}], "deformations": [{{"frames": "5-6", "what": "short description"}}], "verdict": "pass", "reasons": ["short sentence"]}}
verdict is "pass" only when events and deformations are both empty."""


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


def motion(frames, fps):
    step = max(1, round(STEP_S * fps))
    H, W = frames[0].shape[:2]
    c = np.array([W / 2, H / 2])
    zr, cx, cy = [], [], []
    for i in range(0, len(frames) - step, step):
        a = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        b = cv2.cvtColor(frames[i + step], cv2.COLOR_BGR2GRAY)
        p0 = cv2.goodFeaturesToTrack(a, 300, 0.01, 8)
        if p0 is None or len(p0) < 20:
            continue
        p1, st, _ = cv2.calcOpticalFlowPyrLK(a, b, p0, None)
        ok = st.ravel() == 1
        if ok.sum() < 20:
            continue
        M, _ = cv2.estimateAffinePartial2D(p0[ok], p1[ok], method=cv2.RANSAC, ransacReprojThreshold=2.0)
        if M is None:
            continue
        s = math.sqrt(abs(np.linalg.det(M[:, :2])))
        d = M[:, :2] @ c + M[:, 2] - c                     # where the picture centre goes: sideways / vertical drift of the path
        dt = step / fps
        zr.append(math.log(max(s, 1e-6)) / dt)
        cx.append(d[0] / dt)
        cy.append(d[1] / dt)
    return np.array(zr), np.array(cx), np.array(cy)


def reversals(v, thr):
    s = [np.sign(x) for x in v if abs(x) > thr]
    return int(sum(1 for i in range(1, len(s)) if s[i] != s[i - 1]))


def summarise(frames, fps):
    zr, cx, cy = motion(frames, fps)
    if len(zr) < 6:
        return {"ok": False, "reason": f"too few tracked intervals ({len(zr)})"}
    per_sec = max(1, round(1.0 / STEP_S))
    first, last = float(np.mean(zr[:per_sec])), float(np.mean(zr[-per_sec:]))
    mean = float(np.mean(zr))
    return {"ok": True, "frames": len(frames), "fps": round(fps, 1), "zoom_rate_mean_per_s": round(mean, 3),
            "accel_last_over_first": round(last / first, 2) if first > 1e-3 else None,
            "jerk": round(float(np.max(np.abs(np.diff(zr)))) / mean, 2) if mean > 1e-3 else None,
            "wobble_x_reversals": reversals(cx, 1.0), "wobble_y_reversals": reversals(cy, 1.0),
            "drift_x_std_px_s": round(float(np.std(cx)), 1), "drift_y_std_px_s": round(float(np.std(cy)), 1),
            "zoom_rate_by_interval": [round(float(x), 2) for x in zr]}


def keyframes(path, label, n=6):
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out = []
    for k, idx in enumerate(np.linspace(0, max(0, total - 2), n).astype(int)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, f = cap.read()
        if ok:
            p = ef.OUT_DIR / f"clipeval_{label}_f{k + 1}.jpg"
            cv2.imwrite(str(p), f, [cv2.IMWRITE_JPEG_QUALITY, 88])
            out.append(p)
    cap.release()
    return out


def content(path, label, usage):
    import exp_director as dr
    ks = keyframes(path, label)
    return dr.ask_claude(CONTENT_PROMPT.format(n=len(ks)), ks, usage), ks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", help="LABEL=path.mp4")
    ap.add_argument("--claude", action="store_true", help="also ask Claude about the content of 6 key frames (cents)")
    a = ap.parse_args()
    ef.OUT_DIR.mkdir(parents=True, exist_ok=True)
    usage = {}
    for item in a.clips:
        label, _, path = item.partition("=")
        if not path or not Path(path).is_file():
            print(f"{label}: file not found ({path})")
            continue
        frames, fps = read_frames(path)
        if len(frames) < 24:
            print(f"{label}: too few frames")
            continue
        m = summarise(frames, fps)
        if not m.get("ok"):
            print(f"{label:28s} MOTION not measurable: {m.get('reason')}")
        else:
            print(f"{label:28s} accel {m['accel_last_over_first']} | jerk {m['jerk']} | wobble reversals x {m['wobble_x_reversals']} y {m['wobble_y_reversals']} | "
                  f"drift std x {m['drift_x_std_px_s']} y {m['drift_y_std_px_s']} px/s | zoom/s {m['zoom_rate_mean_per_s']} | by interval {m['zoom_rate_by_interval']}")
        if a.claude:
            try:
                q, ks = content(path, label, usage)
                print(f"{'':28s} CONTENT verdict {q.get('verdict')} | events {q.get('events')} | deformations {q.get('deformations')} | {q.get('reasons')}")
                print(f"{'':28s} key frames: {ef.PUBLIC + ks[0].name} ... {ef.PUBLIC + ks[-1].name}")
            except Exception as e:
                print(f"{'':28s} CONTENT error: {str(e)[:200]}")
    if usage:
        print(f"Claude tokens in/out {usage.get('in')}/{usage.get('out')} (~USD {round((usage.get('in', 0) * 2 + usage.get('out', 0) * 10) / 1e6, 3)})")


if __name__ == "__main__":
    main()
