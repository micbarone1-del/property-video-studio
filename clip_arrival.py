"""clip_arrival.py - did the clip reach the director's target at the planned pace? READ-ONLY, no API, no spend.
The camera director (movement_director) plans, per scene, a forward move ending on a view zoomed by `scale` (1.05 static ... 1.4 long; the travel is already capped by the
scene depth). Here we measure what the clip really did: the accumulated zoom of the view over time (a zoom + translation fit of the dense optical flow of each frame step).
  zoom(t)      = accumulated zoom of frame t relative to frame 0 (1.00 = none)
  overshoot    = ln(final zoom) / ln(planned scale)   (1.0 = reaches the target exactly; 2.0 = travelled twice as far as planned)
  half         = share of the total zoom done in the first half of the clip (0.5 = constant pace; 0.2 = almost all of it in the last moments = the "rush at the end")
  t_arrive     = first second at which the planned scale is reached (None if never)
Depth is NOT a separate input: the director already limits the planned travel by the scene depth, so a clip that goes beyond the plan is fast FOR THAT SCENE.
  python3 clip_arrival.py JOB[:SCENE] ...      (scene 1-based; JOB alone = every scene)"""
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

import clip_flow

FPS = clip_flow.FPS


def zoom_series(mp4):
    """(per-step log zoom list, per-step translation share of frame width list, seconds per step) or None."""
    f = clip_flow._frames(mp4)
    if len(f) < 6:
        return None
    h, w = f.shape[1:]
    ys, xs = np.mgrid[0:h, 0:w]
    xs = (xs - w / 2.0).astype(np.float32).ravel()
    ys = (ys - h / 2.0).astype(np.float32).ravel()
    A = np.stack([np.ones_like(xs), np.zeros_like(xs), xs], 1)           # u = a + s*x
    B = np.stack([np.zeros_like(xs), np.ones_like(xs), ys], 1)           # v = b + s*y
    M = np.vstack([A, B])
    logz, trans = [], []
    for a, b in zip(f[:-1], f[1:]):
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        y = np.concatenate([fl[..., 0].ravel(), fl[..., 1].ravel()])
        sol, *_ = np.linalg.lstsq(M, y, rcond=None)
        logz.append(float(np.log1p(max(sol[2], -0.5))))
        trans.append(float(math.hypot(sol[0], sol[1]) / w))
    return logz, trans, 1.0 / FPS


def profile(mp4, planned_scale=None):
    z = zoom_series(mp4)
    if not z:
        return {}
    logz, trans, dt = z
    cum = np.cumsum(logz)
    total = float(cum[-1])
    n = len(cum)
    out = {"zoom_end": float(math.exp(total)), "half": float(cum[n // 2 - 1] / total) if total > 0.01 else None,
           "trans_end": float(sum(trans)), "secs": n * dt}
    if planned_scale and planned_scale > 1.0:
        lp = math.log(planned_scale)
        out["overshoot"] = total / lp
        hit = np.nonzero(cum >= lp)[0]
        out["t_arrive"] = float((hit[0] + 1) * dt) if len(hit) else None
    return out


def planned_scale_of(clip_path):
    try:
        import movement_director
        p = movement_director.last_plan(clip_path)
        return (float(p.get("scale")), p.get("move"), p.get("travel")) if p else (None, None, None)
    except Exception:
        return (None, None, None)


def main(argv) -> int:
    import clip_provenance
    here = Path(__file__).resolve().parent
    roots = [here / "jobs", Path(os.environ.get("PVS_TEST_JOBS_DIR") or "/var/www/pvs_test_jobs")]
    for arg in argv[1:]:
        job, _, sc = arg.partition(":")
        d = next((r / job for r in roots if (r / job / "job_meta.json").exists()), None)
        if d is None:
            print(arg, "job non trovato")
            continue
        scenes = json.loads((d / "job_meta.json").read_text(encoding="utf-8")).get("scenes_config") or []
        for i, s in enumerate(scenes):
            if sc and int(sc) != i + 1:
                continue
            mp4 = clip_provenance.clip_file_for_scene(d, i, s.get("scene_id"))
            if not mp4:
                continue
            ps, move, travel = planned_scale_of(mp4)
            r = profile(mp4, ps)
            fmt = lambda k, f="%.2f": (f % r[k]) if r.get(k) is not None else "-"
            print(f"{job} scena {i+1} {str(s.get('category')):<10} piano={move}/{travel}/{ps}  zoom finale={fmt('zoom_end')} sforamento={fmt('overshoot')} "
                  f"meta'={fmt('half')} arrivo_s={fmt('t_arrive','%.1f')} traslazione={fmt('trans_end')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
