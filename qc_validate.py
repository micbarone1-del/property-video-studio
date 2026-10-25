"""Clip QC validation (2026-10-25, backlog 83). READ-ONLY on the jobs, costs a few cents of Claude, no Luma, no fal.

For every scene of a finished job it runs the NEW clip QC (Claude: photo + first + last frame, vision_analysis.analyse_output) on the
clip and the photo that already exist, and prints it NEXT TO the verdict the old QC stored in job_meta.json. Nothing is written
(not in the job, not anywhere): output goes to the terminal only.

    python3 qc_validate.py [--model <claude model id>] <job_id> [<job_id> ...]

--model tries another Claude model for the QC (e.g. claude-haiku-5-5, claude-sonnet-5-5) WITHOUT changing the project's default.
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


def run(job_id: str, jobs_dir: Path = JOBS_DIR, model: str = None) -> dict:
    import vision_analysis as va
    from vision_analysis import analyse_output
    import listing_scraper as ls
    if model:
        va.CLIP_QC_MODEL = model
    rows = plan(job_id, jobs_dir)
    tot = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cost_eur": 0.0}
    print(f"=== job {job_id}: {len(rows)} scenes with photo and clip | model: {va.CLIP_QC_MODEL or ls.MODEL}")
    for r in rows:
        q = analyse_output(str(r["clip"]), str(r["photo"]), r["space_type"])
        tot = ls.merge_claude_usage(tot, q.get("claude_usage"))
        print(f"--- scena {r['scene']} (space_type={r['space_type']})")
        print(f"    VECCHIO QC : {r['old_verdict']}  {r['old_issues']}")
        print(f"    NUOVO QC   : {q['verdict']}  severity={q['severity']}  issues={q['issues']}  error={q['error']}")
        if q.get("photo_elements"):
            print(f"    elementi foto: {q['photo_elements']}")
        print(f"    primo frame: {q['output_description'][:220]}")
        print(f"    ultimo     : {q['last_description'][:220]}")
    print(f"=== Claude: {tot['calls']} chiamate, {tot['input_tokens']} token in / {tot['output_tokens']} out, EUR {tot['cost_eur']}")
    return tot


if __name__ == "__main__":
    args = sys.argv[1:]
    model = None
    if "--model" in args:
        i = args.index("--model")
        model = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    if not args:
        print(__doc__)
        sys.exit(2)
    for jid in args:
        run(jid, model=model)
