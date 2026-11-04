"""clip_speed_probe.py - objective camera-speed proxy of a clip, calibrated on Michele's blind labels (2026-11-04). READ-ONLY, no API, no spend.

Why: the A/B rounds showed videos that are much more stable, with a few OUTLIERS that rush. If a cheap number separates the "fast" clips from the "ok" ones,
it becomes an automatic check (rework before Michele sees it) and a tool to find what the outliers have in common.
Measure per clip (ffmpeg, 8 fps, 160x90 grey, numpy): motion energy = mean absolute difference between consecutive frames, in grey levels per frame step;
  e_all = mean over the clip, e_last = mean over the last third, accel = e_last / e_first third. It depends on the texture of the photo, so it is also reported
  relative to the median of the clips of the SAME scene (rel) - the number that matters when the prompt variants are compared.
  python3 clip_speed_probe.py                 table of all labelled clips + summary per label + how well each measure separates fast from ok
  python3 clip_speed_probe.py FILE.mp4 [...]  the numbers of single clips
"""
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
JOBS_DIR = Path(os.environ.get("PVS_JOBS_DIR") or (HERE / "jobs"))
SCRATCH = JOBS_DIR / "_test_scratch"
W, H, FPS = 160, 90, 8


def frames(mp4) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(mp4), "-vf", f"fps={FPS},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True, timeout=120).stdout
    n = len(raw) // (W * H)
    return np.frombuffer(raw[: n * W * H], dtype=np.uint8).reshape(n, H, W).astype(np.float32)


def speed(mp4) -> dict:
    f = frames(mp4)
    if len(f) < 6:
        return {}
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))      # one value per frame step
    k = max(1, len(d) // 3)
    return {"e_all": float(d.mean()), "e_first": float(d[:k].mean()), "e_last": float(d[-k:].mean()), "accel": float(d[-k:].mean() / max(d[:k].mean(), 1e-6)),
            "e_peak": float(d.max())}


def separation(vals_fast, vals_ok) -> float:
    """AUC: the chance that a random fast clip scores higher than a random ok clip (0.5 = no information, 1.0 = perfect)."""
    if not vals_fast or not vals_ok:
        return float("nan")
    wins = sum((a > b) + 0.5 * (a == b) for a in vals_fast for b in vals_ok)
    return wins / (len(vals_fast) * len(vals_ok))


def main():
    if len(sys.argv) > 1:
        for p in sys.argv[1:]:
            print(p, {k: round(v, 2) for k, v in speed(p).items()})
        return 0
    labels = json.loads((HERE / "clip_speed_labels.json").read_text())
    rows = []
    for run, codes in labels.items():
        if run.startswith("_"):
            continue
        for code, lab in codes.items():
            mp4 = SCRATCH / f"ab_{run}_{code}.mp4"
            if not mp4.exists():
                mp4 = SCRATCH / "prompt_ab" / f"ab_{run}_{code}.mp4"
            if not mp4.exists():
                continue
            s = speed(mp4)
            if s:
                rows.append({"run": run, "code": code, "label": lab, **s})
    keyf = json.loads  # noqa
    # the scene of a clip comes from the key file of its run
    scene = {}
    for run in labels:
        if run.startswith("_"):
            continue
        kf = SCRATCH / "prompt_ab" / f"key_{run}.json"
        if kf.exists():
            for r in json.loads(kf.read_text()):
                scene[(run, r["code"])] = (r["case"], r["variant"])
    for r in rows:
        r["case"], r["variant"] = scene.get((r["run"], r["code"]), ("?", "?"))
    by_case = {}
    for r in rows:
        by_case.setdefault((r["run"], r["case"]), []).append(r["e_all"])
    for r in rows:
        med = statistics.median(by_case[(r["run"], r["case"])])
        r["rel"] = r["e_all"] / med if med > 0 else float("nan")
    order = {"fast": 0, "slightly_fast": 1, "ok": 2, "slow": 3}
    rows.sort(key=lambda r: (r["case"], order[r["label"]], -r["e_all"]))
    print(f"{len(rows)} clips measured")
    print("case          var code label          e_all e_last accel  rel")
    for r in rows:
        print(f"{r['case']:<13} {r['variant']:<3} {r['code']}  {r['label']:<13} {r['e_all']:6.2f} {r['e_last']:6.2f} {r['accel']:5.2f} {r['rel']:5.2f}")
    print("\nmean per label:")
    for lab in ("fast", "slightly_fast", "ok", "slow"):
        sel = [r for r in rows if r["label"] == lab]
        if sel:
            print(f"  {lab:<14} n={len(sel):<3} e_all={statistics.mean(r['e_all'] for r in sel):5.2f}  rel={statistics.mean(r['rel'] for r in sel):4.2f}  accel={statistics.mean(r['accel'] for r in sel):4.2f}")
    fast = [r for r in rows if r["label"] == "fast"]
    ok = [r for r in rows if r["label"] == "ok"]
    print("\nseparation fast vs ok (AUC; 0.5 = nothing, 1.0 = perfect):")
    for key in ("e_all", "e_last", "accel", "e_peak", "rel"):
        print(f"  {key:<7} {separation([r[key] for r in fast], [r[key] for r in ok]):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
