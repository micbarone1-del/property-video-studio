"""test_clip_pace.py - offline checks of the proportional pace fix. No network, no spend. Run: python3 test_clip_pace.py"""
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
for x, y in zip(rng.integers(0, 1500, 120), rng.integers(0, 800, 120)):
    cv2.rectangle(base, (int(x), int(y)), (int(x) + 40, int(y) + 40), (int(x) % 255, int(y) % 255, 128), -1)
def make(name, rate=0.25, n=120):
    p = tmp / name
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 24, (480, 270))
    for i in range(n):
        z = rate * (i / (n - 1)) ** 3                 # accelerating push-in
        cw, ch = 800 * (1 - z), 450 * (1 - z)
        w.write(cv2.resize(base[int(450 - ch / 2):int(450 + ch / 2), int(800 - cw / 2):int(800 + cw / 2)], (480, 270)))
    w.release()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(p), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p) + ".h264.mp4"], check=True)
    os.replace(str(p) + ".h264.mp4", p)
    return p
def geo_of(p):
    return cp.measure_file(p)
for k in ("PVS_PACE_FIX", "PVS_PACE_LIMIT"):
    os.environ.pop(k, None)
c1 = make("a.mp4"); g1 = geo_of(c1); pk = g1["motion_peak"]
check("P0 the QC measures give a peak above the mean for an accelerating clip", g1["ok"] and pk > g1["motion_mean"] * 1.5 and len(g1["motion"]) >= 15)
check("P1 switch OFF by default: nothing touched", cp.apply(c1, g1, limit=pk / 1.25)["reason"] == "switch off" and not cp.marker(c1).exists())
os.environ["PVS_PACE_FIX"] = "1"
check("P2 no limit set = nothing happens (there is deliberately no default)", cp.apply(c1, g1)["reason"].startswith("no limit"))
check("P3 within the limit = untouched", cp.apply(c1, g1, limit=pk * 1.1)["reason"] == "within limit" and not cp.marker(c1).exists())
check("P4 factor is PROPORTIONAL: limit/peak, clamped to 0.6, none when within", abs(cp.factor_for(6, 5) - 5 / 6) < 1e-9 and cp.factor_for(7.5, 5) < cp.factor_for(6, 5) and cp.factor_for(100, 5) == 0.6 and cp.factor_for(5, 5) is None and cp.factor_for(None, 5) is None)
check("P5 not measured = nothing happens", cp.apply(c1, {"ok": False}, limit=1)["reason"] == "speed not measured")
size0 = c1.stat().st_size
r = cp.apply(c1, {"geo": g1}, limit=pk / 1.25)
check("P6 limit 1.25x under the peak -> factor 0.8: keeps 80%, stretched back to 5 s", r["applied"] and abs(r["factor"] - 0.8) < 0.02 and abs(cp._duration(c1) - 5.0) < 0.25)
check("P7 original kept as .pre_pace, marker written, clip readable", cp.backup(c1).exists() and cp.backup(c1).stat().st_size == size0 and cp.marker(c1).exists() and cv2.VideoCapture(str(c1)).read()[0])
check("P8 never slowed twice", cp.apply(c1, g1, limit=pk / 1.25)["reason"] == "already slowed")
g_after = geo_of(c1)
check("P9 after the fix the fastest second is lower, close to the limit", g_after["ok"] and g_after["motion_peak"] < pk * 0.95)
rr = cp.apply(c1, g1, limit=pk / 1.6, redo=True)
check("P10 redo restarts from the original with another proportional factor (0.625), original still there", rr["applied"] and abs(rr["factor"] - 0.625) < 0.02 and cp.backup(c1).exists())
c2 = make("b.mp4"); g2 = geo_of(c2)
check("P11 a very high peak is clamped at 0.6 (3.0 s kept)", cp.apply(c2, g2, limit=pk / 5)["keep_secs"] == 3.0)
c3 = tmp / "short.mp4"; subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(cp.backup(c2)), "-t", "3.2", "-c:v", "libx264", str(c3)], check=True)
check("P12 a clip too short to slow is left alone", cp.apply(c3, g2, limit=pk / 2)["applied"] is False)
check("P13 missing file never raises", cp.apply(tmp / "nope.mp4", g2, limit=pk / 2)["applied"] is False)
c6 = make("f.mp4"); g6 = geo_of(c6)
r6 = cp.apply(c6, g6, limit=g6["motion_peak"] / 3, min_speed=1e6)
check("P16 lower threshold: a result that would end too slow is not applied (closed loop, clip left as is)", r6["applied"] is False and "too slow" in r6["reason"] and not cp.marker(c6).exists())
r7 = cp.apply(c6, g6, limit=g6["motion_peak"] / 3, min_speed=0.01)
check("P17 lower threshold met: applied and the measured result is recorded", r7["applied"] and r7["result_peak"] is not None and r7["min_speed"] == 0.01)
os.environ.pop("PVS_PACE_INTERP", None)
check("P18 interpolation: blend by default, mci when asked", cp.interp_mode() == "blend" and (os.environ.__setitem__("PVS_PACE_INTERP", "mci") or cp.interp_mode() == "mci"))
ok_mci, _ = cp.render(c2 if False else cp.backup(c1), tmp / "mci.mp4", 5.04, 3.5, mode="mci")
check("P19 mci render works and keeps the length", ok_mci and abs(cp._duration(tmp / "mci.mp4") - 5.04) < 0.3)
os.environ.pop("PVS_PACE_INTERP", None)
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_analysis.py"), encoding="utf-8").read()
check("P14 hook: ONE place, inside the judge block, before the shadow record, takes the QC measures", src.count("_cp.apply(") == 1 and "_cp.apply(video_path, _std)" in src and src.index("_cp.apply(") < src.index("_cs.record(video_path, _std)"))
f = tmp / "ev.jsonl"
f.write_text("\n".join(json.dumps(e) for e in [{"speed": "fast"}, {"speed": "slow", "pace": {"applied": True}}, {"speed": None}]), encoding="utf-8")
s = cs.summary(str(f))
check("P15 summary counts applied fixes", s["pace_applied"] == 1)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
