"""exp_rotation.py - FREE measure of "how much NEW content does the camera reveal" in a clip (2026-11-05), calibrated on Michele's labels. EXPERIMENT TOOL, NOT PRODUCTION.
Why: the Claude judge misses wide rotations (cis, qus: 'too much rotation to the left, outside the frame') and single motion numbers (e_all, drift) cannot tell a rotation from a normal push-in.
Idea: follow the picture with the same tracking as exp_clipeval.motion (a similarity transform per 0.25 s), COMPOSE the steps into one transform first frame -> last frame, and ask how much of the
LAST frame was already inside the FIRST frame. A push-in only zooms into the first picture (new content ~0); a pan or a rotation or a backward move shows content that was never there.
  new_max   = the largest of those shares over all the sampled frames (0.25 s steps)
  new_frac  = 1 - area(first frame mapped into the last frame, intersected with the last frame) / area(last frame)       0 = nothing new, 1 = a different scene
  pan_frac  = net sideways shift of the picture centre / frame width (signed: + = picture moved right = camera turned left)
  zoom_net  = net scale (>1 = closer, <1 = pulled back)
  python3 exp_rotation.py calibrate [--labels motion_labels.json]     PVS_VOLUME_SCRATCH = where the runs are; prints the class means, the best threshold, and the judge + new_frac together
  python3 exp_rotation.py archive [--dir jobs] [--limit 300]            the clips of the jobs already produced: how many normal clips each threshold would flag
  python3 exp_rotation.py clip FILE.mp4                                 one clip
"""
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (HERE / "jobs" / "_test_scratch"))
OUT = SCRATCH / "facade"
STEP_S = 0.25
WORK_W = 480
MIN_TRACKED = 20


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
    return {"ok": True, "new_frac": round(shares[-1], 3), "new_max": round(max(shares), 3), "pan_frac": round(float((c[0] - W / 2) / W), 3), "zoom_net": round(s, 3)}


def clip(path) -> dict:
    frames, fps = read_frames(path)
    return measures(frames, fps)


def calibrate(labels_file) -> int:
    import exp_motion_cal as mc
    rows = []
    for run, code, cls in mc.load_labels(labels_file):
        p = OUT / run / f"{code}.mp4"
        if not p.is_file():
            continue
        m = clip(p)
        if m.get("ok"):
            rows.append(dict(m, run=run, code=code, cls=cls, abs_pan=abs(m["pan_frac"])))
    print(f"{len(rows)} labelled clips measured")
    for k in ("new_frac", "new_max", "abs_pan"):
        print("=" * 10, k)
        for cls in ("bad", "part", "ok"):
            v = sorted(r[k] for r in rows if r["cls"] == cls)
            if v:
                print(f"  {cls:4s} n {len(v):3d} | median {v[len(v) // 2]:.3f} | 80th pct {v[int(len(v) * 0.8)]:.3f} | max {v[-1]:.3f}")
        bad = [r[k] for r in rows if r["cls"] == "bad"]
        ok = [r[k] for r in rows if r["cls"] == "ok"]
        b = mc.best_threshold(bad, ok)
        if b:
            print(f"  best threshold {b[0]} catches {round(b[1] * 100)}% of bad, flags {round(b[2] * 100)}% of ok")
    # together with the judge (saved answers of exp_judge), OR rule
    jv = {}
    for run in {r["run"] for r in rows}:
        jv[run] = mc.judge_by_code(run)
    rr = [r for r in rows if r["code"] in jv.get(r["run"], {})]
    if rr:
        bad = [r for r in rr if r["cls"] == "bad"]
        ok = [r for r in rr if r["cls"] == "ok"]
        print("=" * 10, f"with the judge ({len(rr)} clips: {len(bad)} bad, {len(ok)} ok)")
        for thr in (0.15, 0.2, 0.25, 0.3, 0.4, 0.5):
            def flag(r):
                return jv[r["run"]][r["code"]] in ("review", "fail") or r["new_frac"] >= thr
            print(f"  judge OR new_frac>={thr}: catches {sum(1 for r in bad if flag(r))}/{len(bad)} bad, flags {sum(1 for r in ok if flag(r))}/{len(ok)} ok")
        print("  judge alone: catches %d/%d bad, flags %d/%d ok" % (sum(1 for r in bad if jv[r["run"]][r["code"]] in ("review", "fail")), len(bad), sum(1 for r in ok if jv[r["run"]][r["code"]] in ("review", "fail")), len(ok)))
    (OUT / "rotation_calibration.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"(saved in {OUT}/rotation_calibration.json)")
    return 0


def archive(root: Path, limit: int) -> int:
    """distribution of new_frac / new_max over the clips of the jobs already produced (NOT labelled): what share of normal production clips each threshold would flag."""
    vals, mx = [], []
    for p in sorted(root.glob("*/clips/*.mp4"))[:limit]:
        m = clip(p)
        if m.get("ok"):
            vals.append(m["new_frac"]); mx.append(m["new_max"])
    if not vals:
        print("no clip measured"); return 1
    n = len(vals)
    print(f"{n} clips of {root}")
    for name, v in (("new_frac", sorted(vals)), ("new_max", sorted(mx))):
        print("%-9s median %.3f | 75%% %.3f | 90%% %.3f | 95%% %.3f | max %.3f" % (name, v[n // 2], v[int(n * .75)], v[int(n * .9)], v[int(n * .95)], v[-1]))
        print("  flagged at: " + " | ".join(f"{t}: {sum(1 for x in v if x >= t)} ({100 * sum(1 for x in v if x >= t) // n}%)" for t in (0.1, 0.15, 0.2, 0.25, 0.3, 0.4)))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["clip"] and len(a) > 1:
        print(clip(a[1])); sys.exit(0)
    if a[:1] == ["calibrate"]:
        sys.exit(calibrate(Path(a[a.index("--labels") + 1]) if "--labels" in a else HERE / "motion_labels.json"))
    if a[:1] == ["archive"]:
        sys.exit(archive(Path(a[a.index("--dir") + 1]) if "--dir" in a else HERE / "jobs", int(a[a.index("--limit") + 1]) if "--limit" in a else 300))
    print(__doc__); sys.exit(1)
