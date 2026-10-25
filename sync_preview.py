"""Sync preview (2026-10-25, test tool, costs NOTHING: no Luma, no ElevenLabs, no Claude).

Builds a video with the TIMELINE and the NARRATION of one job (e.g. a new draft) over the CLIPS of another job that already has them
(same listing, same scene order). It calls the very same functions as the real assembly (video_assembly.assemble_property_video with
the job's `timeline.targets` = clip speeds + cross-fades, then api_server._overlay_narration_audio) - no second implementation.

Safety: both jobs are only READ. The only file written is jobs/_test_scratch/sync_preview_<timeline>_with_<clips>.mp4
(served by the app at /test-scratch/<file>). No job state is touched, nothing is deleted.

    python3 sync_preview.py <timeline_job_id> <clips_job_id>
"""
import json
import sys
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parent / "jobs"
SCRATCH_NAME = "_test_scratch"


def _job_dir(jobs_dir: Path, job_id: str) -> Path:
    if not job_id or "/" in job_id or "\\" in job_id or job_id.startswith(".") or job_id.startswith("_"):
        raise ValueError(f"not a job id: {job_id!r}")
    d = Path(jobs_dir) / job_id
    if not d.is_dir():
        raise FileNotFoundError(f"job folder not found: {d}")
    return d


def plan(timeline_job: str, clips_job: str, jobs_dir: Path = JOBS_DIR) -> dict:
    """Everything the build needs, checked, with NO side effect: {targets, clips, narration, out, transition, output_format}."""
    tdir, cdir = _job_dir(jobs_dir, timeline_job), _job_dir(jobs_dir, clips_job)
    meta = json.loads((tdir / "job_meta.json").read_text(encoding="utf-8"))
    tl = meta.get("timeline") or {}
    if tl.get("mode") != "anchored" or not tl.get("targets"):
        raise ValueError(f"job {timeline_job} has no anchored timeline (narration_mode {meta.get('narration_mode')})")
    targets = [float(x) for x in tl["targets"]]
    clips = [cdir / "clips" / f"scene_{i:03d}.mp4" for i in range(len(targets))]
    missing = [str(c) for c in clips if not c.is_file()]
    if missing:
        raise FileNotFoundError(f"clips missing in job {clips_job}: {missing}")
    narration = tdir / "narration.mp3"
    if not narration.is_file():
        raise FileNotFoundError(f"narration missing: {narration}")
    out = Path(jobs_dir) / SCRATCH_NAME / f"sync_preview_{timeline_job}_with_{clips_job}.mp4"
    return {"targets": targets, "clips": clips, "narration": narration, "out": out,
            "transition": meta.get("transition_style", "fade"), "output_format": meta.get("output_format", "landscape")}


def light_copy_cmd(src, dst) -> list:
    """ffmpeg command for the LIGHT copy (480 p, fast start): loads in seconds instead of minutes. The full video stays untouched."""
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "29", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dst)]


def build(timeline_job: str, clips_job: str, jobs_dir: Path = JOBS_DIR) -> Path:
    p = plan(timeline_job, clips_job, jobs_dir)
    p["out"].parent.mkdir(parents=True, exist_ok=True)
    from video_assembly import assemble_property_video
    n = len(p["targets"])
    ok = assemble_property_video(
        scenes_config=[{} for _ in range(n)], video_clip_paths=[str(c) for c in p["clips"]], audio_paths=[None] * n,
        image_paths=[str(c) for c in p["clips"]], output_path=str(p["out"]), property_name="sync preview",
        transition_style=p["transition"], output_format=p["output_format"], logo_path=None, show_captions=False,
        scene_target_secs=p["targets"])
    if not ok:
        raise RuntimeError("assembly failed")
    from api_server import _overlay_narration_audio
    _overlay_narration_audio(str(p["out"]), str(p["narration"]), p["transition"])
    import subprocess
    light = p["out"].with_name(p["out"].stem + "_light.mp4")
    subprocess.run(light_copy_cmd(p["out"], light), check=True, timeout=300)
    return p["out"]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    out = build(sys.argv[1], sys.argv[2])
    print(f"READY: {out}")
    print(f"Open the LIGHT copy (fast): http://187.77.196.94:8000/test-scratch/{out.stem}_light.mp4")
    print(f"Full quality:               http://187.77.196.94:8000/test-scratch/{out.name}")
