"""
exp_prompt.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-11-02). Does a prompt written in POSITIVE form prevent hallucinations in the image-to-video engine?

Why: today's Luma prompt = movement token + pace + _LUMA_RULES, which is ~15 NEGATIONS ("no people", "do not invent", "no new doorways", "no warping"...). Luma's own
documentation says to describe what you want (it has no negative-prompt parameter), and the ghost curtain / second tap (job 91056c3e scenes 1 and 4) happened
with the negative version. This script generates ONE clip per call with the SAME photo, the SAME movement token and the SAME pace as production and ONLY
the rules text replaced by a positive description, then runs the PRODUCTION clip QC (vision_analysis.analyse_output) on the result.
It reuses exp_luma.cmd_run (same photo choice enhanced_lit, same ledger with the EUR 10 cap, same generator): no private copy of the pipeline.

  python3 exp_prompt.py JOB INDEX            shows the prompt, the cost and the spend so far, stops (free)
  python3 exp_prompt.py JOB INDEX --go       generates ONE clip (~EUR 1.1) in 1080p, runs the production QC on it, prints light + full links
  python3 exp_prompt.py JOB INDEX --described [--go] [--scale 1.3]
        same, but the rules ALSO carry a positive DESCRIPTION of the expected last frame (Michele's idea, 2026-11-02). The description is written by Claude
        from the central region of the photo (1/scale of it: where a straight forward move ends). That crop is NEVER given to Luma as an image (no end frame, no 2D zoom):
        it is only the source of the words. The crop is saved so a person can check what is being described.
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

from described_view import POSITIVE_RULES, DESCRIBE_PROMPT   # 2026-11-02: ONE definition, now the production one (was a private copy here)


def described_rules(photo, scale, job, index, usage):
    """(rules text, crop path): POSITIVE_RULES plus Claude's description of the central 1/scale region of the photo."""
    from PIL import Image
    import exp_director as dr
    im = Image.open(photo).convert("RGB")
    w, h = im.size
    cw, ch = round(w / scale), round(h / scale)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    ef.OUT_DIR.mkdir(parents=True, exist_ok=True)
    crop = ef.OUT_DIR / f"described_crop_{job}_s{index}.jpg"
    im.crop((x0, y0, x0 + cw, y0 + ch)).save(crop, quality=92)
    q = dr.ask_claude(DESCRIBE_PROMPT, [photo, crop], usage)
    text = str(q.get("last_view", "")).strip()
    if not text:
        raise SystemExit("Claude gave no description: nothing generated")
    return POSITIVE_RULES + ", " + text, crop, text


def main():
    argv = list(sys.argv[1:])
    scale = None
    if "--scale" in argv:
        i = argv.index("--scale")
        scale = float(argv[i + 1])
        del argv[i:i + 2]                              # the value of --scale is not a positional argument (the first version dropped the scene INDEX instead)
    go = "--go" in argv
    described = "--described" in argv
    a = [x for x in argv if not x.startswith("--")]
    if len(a) != 2:
        raise SystemExit(__doc__)
    job, index = a[0], int(a[1])
    import video_generation as vg
    s = exp_luma.load_scene(job, index)
    movement = s["scene"].get("pov_movement", "walk_in_explore")
    if scale is None:       # a straight forward move ends on the central 1/1.3 of the photo; a gentle rotation ends on almost the whole photo
        scale = 1.3 if movement in ("walk_in_explore", "walk_toward") else 1.1
    print(f"scene {index}: movement {movement}, space {s['scene'].get('space_type')}, photo {s['image'].name if s['image'] else 'NOT FOUND'}")
    print("TODAY'S RULES (negations):", vg._LUMA_RULES[:260], "...")
    print(f"POSITIVE RULES (this test; crop scale for the description {scale:g}):", POSITIVE_RULES)
    rules, label = POSITIVE_RULES, "positive"
    if described:
        usage = {}
        rules, crop, text = described_rules(s["image"], scale, job, index, usage)
        label = "described"
        print("CROP USED ONLY AS THE SOURCE OF THE WORDS (never sent to Luma):", ef.PUBLIC + crop.name)
        print("DESCRIPTION OF THE EXPECTED LAST FRAME:", text)
    vg._LUMA_RULES = rules                           # the ONLY change: the rules text; movement token and pace stay production's
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
    pos = ef.OUT_DIR / f"{label}_{job}_s{index}_{int(start)}.mp4"
    shutil.copyfile(clip, pos)
    import preview_proxy
    light = preview_proxy.light_copy(pos, ef.OUT_DIR)
    print(f"{label.upper()} CLIP LIGHT:", ef.PUBLIC + Path(light).name)
    print(f"{label.upper()} CLIP FULL :", ef.PUBLIC + pos.name)
    from vision_analysis import analyse_output
    q = analyse_output(str(pos), str(s["image"]), s["scene"].get("space_type"))
    print(f"PRODUCTION CLIP QC: {q['verdict']} severity={q['severity']} issues={q['issues']} error={q['error']}")
    print("   first frame:", q["output_description"][:200])
    print("   last frame :", q["last_description"][:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
