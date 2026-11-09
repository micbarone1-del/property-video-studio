"""test_clip_pace.py - offline checks of the pace fix. No network, no spend. Run: python3 test_clip_pace.py"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clip_pace as cp, clip_standard as cs
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
tmp = Path(tempfile.mkdtemp())
rng = np.random.default_rng(5)
base = cv2.GaussianBlur(rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8), (0, 0), 3)
def make(name, n=120, fps=24):
    p = tmp / name
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 180))
    for i in range(n):
        t = (i / (n - 1)) ** 3                       # accelerating push-in
        cw, ch = 800 * (1 - 0.3 * t), 450 * (1 - 0.3 * t)
        w.write(cv2.resize(base[int(450 - ch / 2):int(450 + ch / 2), int(800 - cw / 2):int(800 + cw / 2)], (320, 180)))
    w.release()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(p), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p) + ".h264.mp4"], check=True)
    os.replace(str(p) + ".h264.mp4", p)
    return p
os.environ.pop("PVS_PACE_FIX", None)
c1 = make("a.mp4")
check("P1 switch OFF by default: nothing is touched", cp.apply(c1, "very_fast") == {"applied": False, "reason": "switch off"} and not cp.marker(c1).exists())
check("P2 not fast = not slowed (even forced)", cp.apply(c1, "slow", force=True)["reason"] == "speed not fast" and cp.apply(c1, None, force=True)["applied"] is False and cp.apply(c1, "static", force=True)["applied"] is False)
size0 = c1.stat().st_size
r = cp.apply(c1, "very_fast", force=True)
d = cp._duration(c1)
check("P3 very_fast keeps 3.0 s and stretches to the original length (scene stays 5 s)", r["applied"] and r["keep_secs"] == 3.0 and abs(d - 5.0) < 0.25 and abs(r["factor"] - 0.6) < 0.01)
check("P4 original kept as .pre_pace, marker written, clip readable", cp.backup(c1).exists() and cp.backup(c1).stat().st_size == size0 and cp.marker(c1).exists() and cv2.VideoCapture(str(c1)).read()[0])
check("P5 never slowed twice", cp.apply(c1, "very_fast", force=True) == {"applied": False, "reason": "already slowed"})
c2 = make("b.mp4")
r2 = cp.apply(c2, "fast", force=True)
check("P6 fast keeps 4.0 s (0.8x)", r2["applied"] and r2["keep_secs"] == 4.0 and abs(cp._duration(c2) - 5.0) < 0.25)
os.environ["PVS_PACE_FIX"] = "1"
c3 = make("c.mp4")
check("P7 switch ON slows without force", cp.apply(c3, "fast")["applied"] is True)
c4 = tmp / "short.mp4"; subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(c3) + ".pre_pace", "-t", "3.2", "-c:v", "libx264", str(c4)], check=True)
check("P8 a clip too short to slow is left alone", cp.apply(c4, "very_fast")["applied"] is False)
check("P9 missing file never raises", cp.apply(tmp / "nope.mp4", "fast")["applied"] is False)
# hook + monitoring
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_analysis.py"), encoding="utf-8").read()
check("P10 hook: ONE place, inside the judge block, before the shadow record", src.count("_cp.apply(") == 1 and src.index("_cp.apply(") < src.index("_cs.record(video_path, _std)"))
f = tmp / "ev.jsonl"
f.write_text("\n".join(json.dumps(e) for e in [{"speed": "fast"}, {"speed": "slow", "pace": {"applied": True}}, {"speed": None}, {"speed": "weird"}]), encoding="utf-8")
s = cs.summary(str(f))
check("P11 summary monitors unrecognised speed and applied fixes", s["speed_unknown"] == 2 and s["speed_unknown_rate"] == 0.5 and s["speed"]["fast"] == 1 and s["pace_applied"] == 1)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
