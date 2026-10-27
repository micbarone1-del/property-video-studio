"""sharp_compare.py: a blurred copy of a clip must score clearly lower than the original; unreadable file -> no crash."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.getcwd())
import sharp_compare as sc
ok_n, fails = 0, []
def check(n, c, e=""):
    global ok_n
    if c: ok_n += 1; print("PASS", n)
    else: fails.append(n); print("FAIL", n, e)
d = tempfile.mkdtemp(); a, b = d + "/sharp.mp4", d + "/blur.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=24:duration=2", "-c:v", "libx264", "-crf", "12", a], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a, "-vf", "scale=960:540,scale=1920:1080", "-c:v", "libx264", "-crf", "12", b], check=True)
ra, rb = sc.frame_sharpness(a), sc.frame_sharpness(b)
check("S1 original scores higher than its upscaled-from-half copy (the 'grainy' case)", ra["sharpness"] > rb["sharpness"] * 1.3, (ra, rb))
check("S2 size and frame count reported", ra["size"] == "1920x1080" and ra["frames"] >= 40, ra)
bad = sc.frame_sharpness(d + "/nope.mp4")
check("S3 missing file: no exception, sharpness None", bad["sharpness"] is None, bad)
print(f"\nRESULT: {'ALL PASS' if not fails else fails} ({ok_n}/{ok_n+len(fails)})"); sys.exit(1 if fails else 0)
