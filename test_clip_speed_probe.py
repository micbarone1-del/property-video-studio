"""test_clip_speed_probe.py - offline checks with synthetic clips (zoom of different speeds)."""
import os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import clip_speed_probe as sp
from PIL import Image
fails = 0
def check(n, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + n); fails += 0 if ok else 1
tmp = Path(tempfile.mkdtemp())
rng = np.random.default_rng(1)
Image.fromarray((rng.random((720, 1280, 3)) * 255).astype("uint8")).filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(3)).save(tmp / "p.png")
def clip(name, zoom_end):
    # 5 s at 24 fps, zoom from 1.0 to zoom_end
    z = f"1+({zoom_end}-1)*on/120"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(tmp / "p.png"), "-vf",
                    f"zoompan=z='{z}':d=120:s=640x360:fps=24", "-t", "5", "-pix_fmt", "yuv420p", str(tmp / name)], check=True)
    return tmp / name
slow, fast = clip("slow.mp4", 1.05), clip("fast.mp4", 1.6)
s, f = sp.speed(slow), sp.speed(fast)
check("P1 a faster zoom has a higher motion energy", f["e_all"] > s["e_all"] * 1.5)
check("P2 the measure returns the five numbers", set(s) == {"e_all", "e_first", "e_last", "accel", "e_peak"})
check("P3 AUC is 1.0 for perfectly separated values and 0.5 for identical ones", sp.separation([3, 4], [1, 2]) == 1.0 and sp.separation([1, 1], [1, 1]) == 0.5)
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
