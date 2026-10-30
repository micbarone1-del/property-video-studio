"""
exp_endclip.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-10-30).

Generates ONE Luma ray-3.2 clip (5 s, 1080p, ~EUR 1.1) from a START frame and an END frame (a real new viewpoint made by
exp_endframe.py), with a short prompt written only in positive terms. Purpose: see whether an end frame stops Luma from
animating things that are not in the photo (the curtain of job 91056c3e scene 1, the second tap of scene 4).
Uses the SAME production function (video_generation._generate_luma_direct, one implementation); writes only to jobs/_test_scratch.
NOTE the test changes TWO things at once (end frame + short positive prompt): it can say "this combination works", not which part did it.

  python3 exp_endclip.py LABEL --start PATH_START --end PATH_END            plan only (nothing spent)
  python3 exp_endclip.py LABEL --start PATH_START --end PATH_END --go       generates ONE clip
"""
import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")

OUT_DIR = Path(os.environ.get("PVS_SCRATCH_DIR", "/var/www/property-video-studio/jobs/_test_scratch"))
PUBLIC = "https://api.propertyvideostudioai.com/test-scratch/"
PROMPT = ("One continuous shot with a smooth, slow forward camera move at constant speed, from the first frame to the last frame. "
          "The room is completely still, nothing moves except the camera. Everything looks exactly as in the first frame.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()

    from PIL import Image
    start, end = Path(a.start), Path(a.end)
    for p in (start, end):
        if not p.is_file():
            raise SystemExit(f"file not found: {p}")
    si, ei = Image.open(start), Image.open(end)
    print(f"start {start.name} {si.size[0]}x{si.size[1]} | end {end.name} {ei.size[0]}x{ei.size[1]}")
    ra, rb = si.size[0] / si.size[1], ei.size[0] / ei.size[1]
    if abs(ra - rb) / ra > 0.03:
        raise SystemExit(f"aspect ratios differ too much ({ra:.3f} vs {rb:.3f}): stop, nothing spent")
    print("prompt:", PROMPT)
    print("estimated cost: ~EUR 1.1 (one 5 s clip, 1080p)")
    if not a.go:
        print("PLAN ONLY (nothing spent). Add --go to run.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # end frame resized to the START frame's exact size (same pixels in and out, no hidden rescale by the provider)
    s_name, e_name = f"endclip_{a.label}_start.jpg", f"endclip_{a.label}_end.jpg"
    si.convert("RGB").save(OUT_DIR / s_name, quality=95)
    ei.convert("RGB").resize(si.size, Image.LANCZOS).save(OUT_DIR / e_name, quality=95)

    import video_generation as vg
    w, h = si.size
    ar = vg._detect_aspect_ratio(w, h, model="luma")
    print("aspect ratio:", ar)
    t0 = time.time()
    url = vg._generate_luma_direct(PUBLIC + s_name, PROMPT, 5, aspect_ratio=ar, end_frame_url=PUBLIC + e_name)
    if not url:
        print("GENERATION FAILED (may still be billed: see the server log for the generation id)")
        return 1
    out = OUT_DIR / f"endclip_{a.label}_{int(time.time())}.mp4"
    out.write_bytes(requests.get(url, timeout=120).content)
    print(f"DONE in {time.time() - t0:.0f} s ({out.stat().st_size // 1024} KB)")
    try:
        import preview_proxy
        light = preview_proxy.light_copy(out, OUT_DIR)
        print("LIGHT:", PUBLIC + light.name)
    except Exception as e:
        print("light copy not made:", e)
    print("FULL :", PUBLIC + out.name)


if __name__ == "__main__":
    sys.exit(main() or 0)
