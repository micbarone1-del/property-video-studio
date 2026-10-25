"""Clip QC validation (2026-10-25, backlog 83). READ-ONLY on the jobs, costs a few cents of Claude, no Luma, no fal.

For every scene of a finished job it runs the NEW clip QC (Claude: photo + first + last frame, vision_analysis.analyse_output) on the
clip and the photo that already exist, and prints it NEXT TO the verdict the old QC stored in job_meta.json. Nothing is written
(not in the job, not anywhere): output goes to the terminal only.

    python3 qc_validate.py <job_id> [<job_id> ...]
"""
import json
import sys
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parent / "jobs"
_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def plan(job_id: str, jobs_dir: Path = JOBS_DIR) -> list:
    """[{scene, photo, clip, space_type, old_verdict, old_issues}] for the scenes that have a photo and a clip. Side-effect free."""
    if not job_id or "/" in job_id or "\\" in job_id or job_id.startswith((".", "_")):
        raise ValueError(f"not a job id: {job_id!r}")
    jdir = Path(jobs_dir) / job_id
    if not jdir.is_dir():
        raise FileNotFoundError(f"job folder not found: {jdir}")
    meta = json.loads((jdir / "job_meta.json").read_text(encoding="utf-8"))
    scenes = {s.get("index"): s for s in (meta.get("scenes") or []) if isinstance(s, dict)}
    old = {q.get("scene"): q for q in (meta.get("qc_results") or []) if isinstance(q, dict) and q.get("type") == "video"}
    rows = []
    for i in range(len(meta.get("scenes_config") or scenes or [])):
        clip = jdir / "clips" / f"scene_{i:03d}.mp4"
        photo = next((jdir / "images" / f"scene_{i:03d}{e}" for e in _EXTS if (jdir / "images" / f"scene_{i:03d}{e}").is_file()), None)
        if clip.is_file() and photo:
            rows.append({"scene": i, "photo": photo, "clip": clip, "space_type": (scenes.get(i) or {}).get("space_type"),
                         "old_verdict": (old.get(i) or {}).get("verdict"), "old_issues": (old.get(i) or {}).get("issues")})
    return rows


def run(job_id: str, jobs_dir: Path = JOBS_DIR) -> None:
    import listing_scraper as ls
    from vision_analysis import analyse_output
    rows = plan(job_id, jobs_dir)
    ls.reset_claude_usage()
    print(f"=== job {job_id}: {len(rows)} scenes with photo and clip")
    for r in rows:
        q = analyse_output(str(r["clip"]), str(r["photo"]), r["space_type"])
        print(f"--- scena {r['scene']} (space_type={r['space_type']})")
        print(f"    VECCHIO QC : {r['old_verdict']}  {r['old_issues']}")
        print(f"    NUOVO QC   : {q['verdict']}  severity={q['severity']}  issues={q['issues']}  error={q['error']}")
        print(f"    primo frame: {q['output_description'][:220]}")
        print(f"    ultimo     : {q['last_description'][:220]}")
    u = ls.get_claude_cost()
    print(f"=== Claude: {u['calls']} chiamate, {u['input_tokens']} token in / {u['output_tokens']} out, EUR {u['cost_eur']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for jid in sys.argv[1:]:
        run(jid)
