"""
exp_prompt.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-11-02). Does a prompt written in POSITIVE form prevent hallucinations in the image-to-video engine?

Why: today's Luma prompt = movement token + pace + _LUMA_RULES, which is ~15 NEGATIONS ("no people", "do not invent", "no new doorways", "no warping"...). Luma's own
documentation says to describe what you want (it has no negative-prompt parameter), and the ghost curtain / second tap (job 91056c3e scenes 1 and 4) happened
with the negative version. This script generates ONE clip per call with the SAME photo, the SAME movement token and the SAME pace as production and ONLY
the rules text replaced by a positive description, then runs the PRODUCTION clip QC (vision_analysis.analyse_output) on the result.
It reuses exp_luma.cmd_run (same photo choice enhanced_lit, same ledger with the EUR 10 cap, same generator): no private copy of the pipeline.

  python3 exp_prompt.py JOB INDEX            shows the prompt, the cost and the spend so far, stops (free)
  python3 exp_prompt.py JOB INDEX --go       generates ONE clip (~EUR 1.1) in 1080p, runs the production QC on it, prints light + full links
Set PVS_JOBS_DIR=/var/www/pvs_test_jobs before running (the test instance jobs). Clips are copied to the public scratch folder; nothing is written in a job.
"""
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PVS_JOBS_DIR", "/var/www/pvs_test_jobs")
from dotenv import load_dotenv
load_dotenv(HERE / ".env")
import exp_luma
import exp_endframe as ef

POSITIVE_RULES = (
    "this is a frozen photograph of an empty, still room: every wall, window, door, curtain, piece of furniture, fixture and decoration keeps exactly the same "
    "place, shape, colour, number and state (open or closed) as in the first frame for the whole shot, and the light stays steady, "
    "the only thing that moves is the camera, which glides forward in one smooth straight line at a constant slow speed, "
    "everything in view at the start stays in view and in place while the nearest parts of the room leave the frame at the edges, "
    "the shot ends on a slightly closer view of the same room that contains exactly the same elements as the first frame, "
    "every shadow and every reflection stays as in the source photo and the room holds only what the source photo shows"
)


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    go = "--go" in sys.argv
    if len(a) != 2:
        raise SystemExit(__doc__)
    job, index = a[0], int(a[1])
    import video_generation as vg
    s = exp_luma.load_scene(job, index)
    movement = s["scene"].get("pov_movement", "walk_in_explore")
    print(f"scene {index}: movement {movement}, space {s['scene'].get('space_type')}, photo {s['image'].name if s['image'] else 'NOT FOUND'}")
    print("TODAY'S RULES (negations):", vg._LUMA_RULES[:260], "...")
    print("POSITIVE RULES (this test):", POSITIVE_RULES)
    vg._LUMA_RULES = POSITIVE_RULES                  # the ONLY change: the rules text; movement token and pace stay production's
    start = time.time()
    rc = exp_luma.cmd_run(job, index, "base", go)
    if not go or rc != 0:
        return rc
    clips = sorted(exp_luma.SCRATCH.glob(f"exp_{job}_{index}_base_*.mp4"), key=lambda p: p.stat().st_mtime)
    if not clips or clips[-1].stat().st_mtime < start:
        print("clip not found after the run")
        return 1
    clip = clips[-1]
    ef.OUT_DIR.mkdir(parents=True, exist_ok=True)
    pos = ef.OUT_DIR / f"positive_{job}_s{index}_{int(start)}.mp4"
    shutil.copyfile(clip, pos)
    import preview_proxy
    light = preview_proxy.light_copy(pos, ef.OUT_DIR)
    print("POSITIVE CLIP LIGHT:", ef.PUBLIC + Path(light).name)
    print("POSITIVE CLIP FULL :", ef.PUBLIC + pos.name)
    from vision_analysis import analyse_output
    q = analyse_output(str(pos), str(s["image"]), s["scene"].get("space_type"))
    print(f"PRODUCTION CLIP QC: {q['verdict']} severity={q['severity']} issues={q['issues']} error={q['error']}")
    print("   first frame:", q["output_description"][:200])
    print("   last frame :", q["last_description"][:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
