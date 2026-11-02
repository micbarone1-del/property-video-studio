"""
exp_pairs.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-11-02). Free, local, read-only, no API.

Michele's question: can a SECOND REAL PHOTO of the same room serve as the end frame of a clip, so that nothing has to be invented?
Before any paid clip: how often does a listing even HAVE such a pair? For every pair of photos of a job it measures with the same SIFT geometry
as exp_geometry (one implementation) how the second photo relates to the first:
  matches / inliers   shared structure (few = a different part of the room, or another room)
  scale               >1 = B is a CLOSER view of A, <1 = B is a wider view
  rotation, expansion point, inside   how much B stays inside A's view (inside ~1 = B shows only what A already shows)
It then lists, for each photo, its best partner and a plain-words reading. Reads the originals in <job>/images, writes nothing.

  python3 exp_pairs.py JOB [--jobs-dir DIR]
"""
import argparse
import itertools
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_geometry as geo

EXTS = (".jpg", ".jpeg", ".png", ".webp")
MIN_INLIERS = 40            # PROPOSED: below this the two photos share too little to be the start and end of one continuous shot


def photos(job_dir: Path):
    meta = json.load(open(job_dir / "job_meta.json"))
    out = []
    for i, sc in enumerate(meta.get("scenes_config") or []):
        sid = sc.get("scene_id")
        cands = ([job_dir / "images" / f"{sid}{e}" for e in EXTS] if sid else []) + [job_dir / "images" / f"scene_{i:03d}{e}" for e in EXTS]
        p = next((c for c in cands if c.is_file()), None)
        if p:
            out.append((i, sc.get("space_type"), (sc.get("caption") or "")[:24], p))
    return out


def reading(r):
    if not r.get("ok"):
        return "no shared structure (another part of the room or another room)"
    if r["inliers"] < MIN_INLIERS:
        return f"weak overlap ({r['inliers']} shared points)"
    near = "B is a closer view of A" if r["scale"] >= 1.12 else ("B is a wider view of A" if r["scale"] <= 0.9 else "B is about the same distance as A")
    side = "" if (r["foe_x"] is not None and max(abs(r["foe_x"]), abs(r["foe_y"])) <= 0.2) else ", seen from a different side"
    inside = "B stays inside A's view" if r["inside"] >= 0.9 else f"only {round(r['inside'] * 100)}% of B is inside A's view"
    return f"{near}{side}; {inside}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--jobs-dir", default="/var/www/pvs_test_jobs")
    a = ap.parse_args()
    ph = photos(Path(a.jobs_dir) / a.job_id)
    print(f"job {a.job_id}: {len(ph)} photos")
    for i, st, cap, p in ph:
        print(f"  scene {i}: {st} | {cap} | {p.name}")
    best = {}
    for (i, _, _, pa), (j, _, _, pb) in itertools.permutations(ph, 2):
        r = geo.analyse(pa, pb)
        score = r.get("inliers", 0) if r.get("ok") else 0
        if score > best.get(i, (0,))[0]:
            best[i] = (score, j, r)
    print("--- best partner of each photo (A -> B), the photo whose view relates most to A ---")
    for i, st, cap, p in ph:
        if i not in best:
            print(f"  scene {i} ({st}): no other photo shares enough structure")
            continue
        score, j, r = best[i]
        usable = "CANDIDATE" if score >= MIN_INLIERS else "not usable"
        print(f"  scene {i} ({st}) -> scene {j}: {usable} | shared points {score} | scale {r.get('scale')} rot {r.get('rotation_deg')} "
              f"expansion ({r.get('foe_x')}, {r.get('foe_y')}) inside {r.get('inside')} | {reading(r)}")
    n = sum(1 for i in best if best[i][0] >= MIN_INLIERS)
    print(f"photos with at least one candidate partner: {n} of {len(ph)} (threshold {MIN_INLIERS} shared points is a PROPOSAL)")


if __name__ == "__main__":
    main()
