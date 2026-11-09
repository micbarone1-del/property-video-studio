"""speed_baseline.py - READ-ONLY. Motion distribution of every job clip (production + test) per scene category, to derive speed thresholds.
No API, no spend, writes nothing. Uses clip_speed_probe.speed (the ONE motion measure).
  python3 speed_baseline.py            distribution per category + the outliers (top 5% by e_all) with job/scene
  python3 speed_baseline.py JOBID      per-scene numbers of one job (to compare with Michele's judgment)"""
import json
import os
import sys
from pathlib import Path

import clip_provenance
import clip_speed_probe as probe

HERE = Path(__file__).resolve().parent
ROOTS = [HERE / "jobs", Path(os.environ.get("PVS_TEST_JOBS_DIR") or "/var/www/pvs_test_jobs")]
KEYS = ("e_all", "e_first", "e_last", "e_peak")


def job_rows(job_dir: Path):
    try:
        meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
    except Exception:
        return
    for i, sc in enumerate(meta.get("scenes_config") or []):
        mp4 = clip_provenance.clip_file_for_scene(job_dir, i, sc.get("scene_id"))
        if not mp4:
            continue
        try:
            s = probe.speed(mp4)
        except Exception:
            continue
        if s:
            cat = sc.get("category") or sc.get("room") or sc.get("room_type") or sc.get("label") or "?"
            yield {"job": job_dir.name, "scene": i + 1, "cat": str(cat), **s}


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))]


def main(argv):
    only = argv[1] if len(argv) > 1 else None
    seen, rows = set(), []
    for root in ROOTS:
        for d in sorted(Path(root).glob("*/")):
            if d.name in seen or d.name.startswith("_") or (only and d.name != only):
                continue
            seen.add(d.name)
            rows += list(job_rows(d))
    if only:
        for r in rows:
            print(f"scena {r['scene']} {r['cat']:<14} " + " ".join(f"{k}={r[k]:.2f}" for k in KEYS) + f" accel={r['accel']:.2f}")
        return 0
    print(f"clip misurati: {len(rows)} in {len(seen)} job")
    by = {}
    for r in rows:
        by.setdefault(r["cat"], []).append(r)
    for cat, rs in sorted(by.items(), key=lambda x: -len(x[1])):
        v = [r["e_all"] for r in rs]
        print(f"{cat:<14} n={len(rs):<4} e_all mediana={pct(v,.5):.2f} p75={pct(v,.75):.2f} p90={pct(v,.9):.2f} max={max(v):.2f}")
    print("--- 5% piu' veloci (e_all)")
    for r in sorted(rows, key=lambda r: -r["e_all"])[: max(5, len(rows) // 20)]:
        print(f"{r['job']} scena {r['scene']} {r['cat']:<12} e_all={r['e_all']:.2f} e_last={r['e_last']:.2f} e_peak={r['e_peak']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
