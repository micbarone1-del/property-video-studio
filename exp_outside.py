"""exp_outside.py - % of each sampled frame that lies OUTSIDE the field of view of the FIRST frame (2026-11-05, Michele's method). EXPERIMENT TOOL, NOT PRODUCTION. Free: no Luma, no Claude.
Idea (Michele): do not count objects and do not measure rotation. Take the first frame as the original field of view; for sampled frames of the clip find where the original frame sits inside
the sampled frame and measure how much of the sampled frame is NOT covered by it. A small share is normal (perspective: a detail of the corridor glimpsed while moving); a big share means the
camera turned / pulled back and everything there is invented. That share then goes to the judge as an input and the rule on the number is automatic.
How: each sampled frame is registered DIRECTLY to frame 1 (SIFT matches + RANSAC homography, no chain of steps, no drift). outside = 1 - area(original frame mapped into the sampled frame, clipped to it) / area(sampled frame).
A frame that cannot be registered at all is a different picture: it counts as outside = 1.0 in `outside_cons` (reported apart, because a bare wall could also fail the registration in a good clip).
  outside_max   largest share over the frames that could be registered         outside_last  share at the last registered frame
  outside_cons  like outside_max but an unregistered frame counts as 1.0         unreg         how many sampled frames could not be registered
  python3 exp_outside.py clip FILE.mp4
  python3 exp_outside.py calibrate [--labels motion_labels.json]       the labelled clips (PVS_VOLUME_SCRATCH = where the runs are): class means, thresholds, with the judge
  python3 exp_outside.py archive [--dir jobs] [--limit 300]            the clips of the jobs already produced: distribution of outside_max (what share of normal clips each threshold would flag)
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
WORK_W = 480
STEP_S = 0.25
MIN_INLIERS = 12


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


def _features(sift, frame):
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    return sift.detectAndCompute(g, None)


def register(k0, d0, kt, dt):
    """homography frame 1 -> sampled frame, or None when the two pictures cannot be matched."""
    if d0 is None or dt is None or len(k0) < MIN_INLIERS or len(kt) < MIN_INLIERS:
        return None
    good = []
    for pair in cv2.BFMatcher().knnMatch(d0, dt, k=2):
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
            good.append(pair[0])
    if len(good) < MIN_INLIERS:
        return None
    src = np.float32([k0[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kt[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None or int(mask.sum()) < MIN_INLIERS:
        return None
    return H


def outside_share(H, W, Hh):
    """share of the sampled frame NOT covered by frame 1 mapped with H (None when the mapping is not usable)."""
    quad = np.array([[0, 0], [W, 0], [W, Hh], [0, Hh]], np.float32)
    pts = (H @ np.vstack([quad.T, np.ones(4)])).T
    if np.any(np.abs(pts[:, 2]) < 1e-6):
        return None
    mapped = (pts[:, :2] / pts[:, 2:3]).astype(np.float32)
    if not np.all(np.isfinite(mapped)) or not cv2.isContourConvex(mapped.reshape(-1, 1, 2)):
        return None
    area, _ = cv2.intersectConvexConvex(mapped, quad)
    return max(0.0, min(1.0, 1.0 - float(area) / float(W * Hh)))


def measures(frames, fps) -> dict:
    if len(frames) < 12:
        return {"ok": False, "why": "too few frames"}
    H0, W0 = frames[0].shape[:2]
    sift = cv2.SIFT_create(nfeatures=1500)
    k0, d0 = _features(sift, frames[0])
    step = max(1, round(STEP_S * fps))
    vals, unreg, n = [], 0, 0
    for i in range(step, len(frames), step):
        n += 1
        kt, dt = _features(sift, frames[i])
        H = register(k0, d0, kt, dt)
        s = outside_share(H, W0, H0) if H is not None else None
        if s is None:
            unreg += 1
        else:
            vals.append(s)
    if n == 0:
        return {"ok": False, "why": "no samples"}
    omax = max(vals) if vals else None
    return {"ok": True, "samples": n, "unreg": unreg, "outside_max": None if omax is None else round(omax, 3),
            "outside_last": None if not vals else round(vals[-1], 3),
            "outside_cons": round(1.0 if unreg else (omax or 0.0), 3)}


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
            rows.append(dict(m, run=run, code=code, cls=cls))
    print(f"{len(rows)} labelled clips measured")
    for k in ("outside_max", "outside_cons"):
        print("=" * 10, k)
        for cls in ("bad", "part", "ok"):
            v = sorted(r[k] for r in rows if r["cls"] == cls and r.get(k) is not None)
            if v:
                print(f"  {cls:4s} n {len(v):3d} | median {v[len(v) // 2]:.3f} | 80th pct {v[int(len(v) * .8)]:.3f} | 95th pct {v[min(len(v) - 1, int(len(v) * .95))]:.3f} | max {v[-1]:.3f}")
        bad = [r[k] for r in rows if r["cls"] == "bad" and r.get(k) is not None]
        ok = [r[k] for r in rows if r["cls"] == "ok" and r.get(k) is not None]
        print("  threshold: " + " | ".join(f"{t}: bad {sum(1 for v in bad if v >= t)}/{len(bad)}, ok {sum(1 for v in ok if v >= t)}/{len(ok)}" for t in (0.1, 0.15, 0.2, 0.3, 0.4, 0.5)))
    print("unregistered frames: bad %.1f / ok %.1f per clip (mean)" % tuple(
        (sum(r["unreg"] for r in rows if r["cls"] == c) / max(1, sum(1 for r in rows if r["cls"] == c))) for c in ("bad", "ok")))
    (OUT / "outside_calibration.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"(saved in {OUT}/outside_calibration.json)")
    return 0


def archive(root: Path, limit: int) -> int:
    files = sorted(root.glob("*/clips/*.mp4"))[:limit]
    vals, cons = [], []
    for p in files:
        m = clip(p)
        if m.get("ok") and m["outside_max"] is not None:
            vals.append(m["outside_max"]); cons.append(m["outside_cons"])
    if not vals:
        print("no clip measured"); return 1
    vals.sort()
    n = len(vals)
    print(f"{n} clips of {root} (delivered or not: NOT labelled, only the distribution of normal production clips)")
    print("outside_max: median %.3f | 75%% %.3f | 90%% %.3f | 95%% %.3f | max %.3f" % (vals[n // 2], vals[int(n * .75)], vals[int(n * .9)], vals[int(n * .95)], vals[-1]))
    print("flagged at: " + " | ".join(f"{t}: {sum(1 for v in vals if v >= t)} ({100 * sum(1 for v in vals if v >= t) // n}%)" for t in (0.1, 0.15, 0.2, 0.3, 0.4)))
    print("clips with an unregistered frame (outside_cons=1.0): %d (%d%%)" % (sum(1 for v in cons if v >= 1.0), 100 * sum(1 for v in cons if v >= 1.0) // len(cons)))
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
