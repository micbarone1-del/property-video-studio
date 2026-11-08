"""listing_registry.py - the ONE reader of "which Relinx/GIAL listings already have a finished video, from which job, at which resolution" (2026-11-08).

Why: on 2026-11-08 the generation launcher started listing 1337 a second time. Its duplicate guard looked for the draft in the PRODUCTION jobs folder while the
draft lived in the TEST folder, so it never found the listing number. Both folders are read here, by one function, for the guard AND for the registry file.

Resolution is MEASURED, never assumed: the short side of the raw clips of the job (ffprobe on clips/*.mp4): 360 -> "360p", 720 -> "720p", 1080 -> "1080p".
If the clips were cleaned away, the job's own field luma_resolution is used, else the date (jobs created from 2026-11-04 on the test instance ran at 360p)
and the source is reported as "estimated". Michele (2026-11-08): all Relinx test jobs are 360p, so for production at 1080p they must all be done again:
a finished 360p video does NOT block a 1080p run, a finished 1080p video blocks every run.

  python3 listing_registry.py              prints, per listing, the best finished video and every job (read only; no file is written: the jobs are the registry)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROD_JOBS = HERE / "jobs"
TEST_JOBS = Path(os.environ.get("PVS_TEST_JOBS_DIR", "/var/www/pvs_test_jobs"))
RANK = {"360p": 1, "540p": 2, "720p": 3, "1080p": 4}
LOW_RES_FROM = "2026-11-04"      # from this date the test instance ran Luma at 360p (video_generation.py comment of 2026-11-04)


def rank(res) -> int:
    return RANK.get(str(res or "").lower(), 0)


def res_class(short_side: int) -> str:
    return "1080p" if short_side >= 1000 else "720p" if short_side >= 650 else "540p" if short_side >= 450 else "360p"


def clip_short_side(job_dir: Path):
    """Short side in pixels of the first raw clip of the job, or None (no clip / unreadable). Never raises."""
    try:
        clips = sorted(Path(job_dir).glob("clips/*.mp4"))
        for c in clips:
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(c)],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            if "x" in out:
                w, h = (int(x) for x in out.split("x")[:2])
                return min(w, h)
    except Exception:
        pass
    return None


def resolution_of(job_dir: Path, meta: dict, in_test: bool = False) -> tuple:
    """(resolution, source): source is "measured", "field" or "estimated"."""
    side = clip_short_side(job_dir)
    if side:
        return res_class(side), "measured"
    if meta.get("luma_resolution"):
        return str(meta["luma_resolution"]), "field"
    created = str(meta.get("created_at") or "")
    return ("360p" if created >= LOW_RES_FROM else "1080p"), "estimated"


def listing_of(meta: dict, job_id: str):
    """The Relinx listing number, by the ONE reader gial_consolidate.listing_ref; None when the job carries none."""
    import gial_consolidate as gc
    ref = gc.listing_ref(meta, job_id)
    return None if ref == job_id[:8] else ref


def scan(dirs=None) -> list:
    """Every job of the given folders (default: production + test): {listing, job_id, where, status, created_at, resolution, source}."""
    dirs = dirs if dirs is not None else [("prod", PROD_JOBS), ("test", TEST_JOBS)]
    out = []
    for where, root in dirs:
        for p in sorted(Path(root).glob("*/job_meta.json")):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            ref = listing_of(m, p.parent.name)
            if ref is None:
                continue
            res, src = resolution_of(p.parent, m)
            out.append({"listing": ref, "job_id": p.parent.name, "where": where, "status": m.get("status"),
                        "created_at": str(m.get("created_at") or "")[:16], "resolution": res, "source": src})
    return out


def finished_blocking(listing: str, target_res: str, records=None, exclude_job=None) -> list:
    """Finished videos of the listing that make a new run at target_res a duplicate: same or higher resolution. [] when there is none."""
    recs = records if records is not None else scan()
    return [r for r in recs if r["listing"] == listing and r["status"] == "done" and r["job_id"] != exclude_job and rank(r["resolution"]) >= rank(target_res)]


def best_done(records: list, listing: str) -> str:
    done = [r["resolution"] for r in records if r["listing"] == listing and r["status"] == "done"]
    return max(done, key=rank) if done else "-"


def main(argv) -> int:
    """Prints, per listing, the best finished video resolution and every job. Writes NOTHING (no registry file: the jobs ARE the registry)."""
    recs = scan()
    by = {}
    for r in recs:
        by.setdefault(r["listing"], []).append(r)
    for lst in sorted(by, key=lambda x: (len(x), x)):
        print(f"annuncio {lst}: migliore video finito = {best_done(recs, lst)}")
        for r in sorted(by[lst], key=lambda r: r["created_at"]):
            print(f"   {r['job_id']} | {r['where']} | {r['status']} | {r['resolution']} ({r['source']}) | {r['created_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
