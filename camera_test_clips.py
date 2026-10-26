"""Camera test round (2026-10-26). Generates 3 REAL Luma clips (about USD 1.20 each) from photos of job 41ae5a44 with the CANDIDATE camera
movements, through the production function video_generation.generate_video_single (no copy of the prompt or upload logic), then runs the
clip QC on each. Nothing under jobs/<job>/ is touched: the clips go to jobs/_test_scratch/ (served at /test-scratch/<file>).

    python3 camera_test_clips.py            -> only prints the plan and the exact prompts (NO cost)
    python3 camera_test_clips.py --go       -> generates the 3 clips (REAL cost)
"""
import glob
import os
import sys
import time

import video_generation as vg

JOB = "jobs/41ae5a44"
SCRATCH = "jobs/_test_scratch"
BASE = os.environ.get("PVS_PUBLIC_URL", "http://187.77.196.94:8000")
# name, photo index, space_type, candidate movement, reflective_surface
CASES = [
    ("facade",  0, "outdoor",  "approach_facade", "none"),
    ("terrace", 5, "elevated", "outward_view",    "none"),
    ("mirror",  3, "bedroom",  "subtle_rotate",   "large"),
]


def photo_of(idx: int):
    hits = sorted(glob.glob(f"{JOB}/images/scene_{idx:03d}.*"))
    return hits[0] if hits else None


def main(go: bool) -> int:
    os.makedirs(SCRATCH, exist_ok=True)
    plan = []
    for name, idx, space, move, refl in CASES:
        photo = photo_of(idx)
        prompt = vg.assemble_pov_prompt(space, move, "bright_natural", vg.DEFAULT_INTENSITY, "luma", "landscape", refl)
        plan.append((name, photo, space, move, refl, prompt))
        print(f"--- {name}: photo={photo} space={space} movement={move} reflective={refl}")
        print(f"    PROMPT: {prompt}")
    if not all(p[1] for p in plan):
        print("ERROR: a photo is missing, nothing generated")
        return 2
    print(f"LUMA_DIRECT={vg.LUMA_DIRECT} FAL_FALLBACK_ENABLED={vg.FAL_FALLBACK_ENABLED} | 3 clips, about USD 3.60 if Luma direct works")
    if not go:
        print("DRY RUN: add --go to generate (REAL cost).")
        return 0
    import vision_analysis as va
    stamp = time.strftime("%H%M%S")
    for name, photo, space, move, refl, _ in plan:
        out = f"{SCRATCH}/camera_{name}_{stamp}.mp4"
        ok = vg.generate_video_single(photo, 5, out, space_type=space, pov_movement=move, lighting="bright_natural",
                                      intensity=vg.DEFAULT_INTENSITY, model_tier="luma", reflective_surface=refl)
        print(f"=== {name}: generated={ok}")
        if not ok:
            print("    stopped: no further clip is generated after a failure")
            return 1
        print(f"    VIDEO: {BASE}/test-scratch/camera_{name}_{stamp}.mp4")
        q = va.analyse_output(out, photo, space)
        print(f"    QC ({va.CLIP_QC_MODEL}): {q['verdict']} {q['issues']}  claude EUR {(q.get('claude_usage') or {}).get('cost_eur')}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--go" in sys.argv[1:]))
