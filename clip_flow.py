"""clip_flow.py - camera speed as APPARENT MOTION, the same unit for every room: % of the frame width travelled per second (dense optical flow, OpenCV).
Why: clip_speed_probe.speed() measures grey-level change, which depends on the texture of the photo (a facade scores higher than a bedroom at the same camera speed).
Optical flow measures how far image points move, independent of texture. READ-ONLY, no API.
  flow(mp4) -> {"pct_s": median over the clip, "first": first third, "last": last third, "peak": 95th percentile}"""
import subprocess

import cv2
import numpy as np

W, H, FPS = 160, 90, 8


def _frames(mp4) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(mp4), "-vf", f"fps={FPS},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True, timeout=120).stdout
    n = len(raw) // (W * H)
    return np.frombuffer(raw[: n * W * H], dtype=np.uint8).reshape(n, H, W)


def flow(mp4) -> dict:
    f = _frames(mp4)
    if len(f) < 6:
        return {}
    mags = []
    for a, b in zip(f[:-1], f[1:]):
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mags.append(float(np.median(np.hypot(fl[..., 0], fl[..., 1]))))      # px per frame step, robust to small moving objects
    m = np.array(mags) / W * 100 * FPS                                         # % of frame width per second
    k = max(1, len(m) // 3)
    return {"pct_s": float(np.median(m)), "first": float(m[:k].mean()), "last": float(m[-k:].mean()), "peak": float(np.percentile(m, 95))}


def main(argv) -> int:
    """python3 clip_flow.py JOB:SCENE [JOB:SCENE ...]   (scene 1-based; JOB alone = all scenes) - prints flow % of width per second, plus the old grey-change number."""
    import json
    import os
    from pathlib import Path

    import clip_provenance
    import clip_speed_probe as old
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
            if mp4:
                r, o = flow(mp4), old.speed(mp4)
                print(f"{job} scena {i+1} {str(s.get('category')):<10} flusso={r['pct_s']:.1f}%/s (inizio {r['first']:.1f}, fine {r['last']:.1f}, picco {r['peak']:.1f})  vecchia misura e_all={o['e_all']:.1f}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
