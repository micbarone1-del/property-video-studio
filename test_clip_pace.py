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
check("P4 factor is PROPORTIONAL: limit/peak, clamped to 0.65, none when within", abs(cp.factor_for(6, 5) - 5 / 6) < 1e-9 and cp.factor_for(7.5, 5) < cp.factor_for(6, 5) and cp.factor_for(100, 5) == 0.65 and cp.factor_for(5, 5) is None and cp.factor_for(None, 5) is None)
check("P5 not measured = nothing happens", cp.apply(c1, {"ok": False}, limit=1)["reason"] == "speed not measured")
size0 = c1.stat().st_size
r = cp.apply(c1, {"geo": g1}, limit=pk / 1.25)
check("P6 limit 1.25x under the peak -> factor 0.8: keeps 80%, stretched back to 5 s", r["applied"] and abs(r["factor"] - 0.8) < 0.02 and abs(cp._duration(c1) - 5.0) < 0.25)
check("P7 original kept as .pre_pace, marker written, clip readable", cp.backup(c1).exists() and cp.backup(c1).stat().st_size == size0 and cp.marker(c1).exists() and cv2.VideoCapture(str(c1)).read()[0])
check("P8 never slowed twice", cp.apply(c1, g1, limit=pk / 1.25)["reason"] == "already slowed")
g_after = geo_of(c1)
check("P9 after the fix the fastest second is lower, close to the limit", g_after["ok"] and g_after["motion_peak"] < pk * 0.95)
rr = cp.apply(c1, g1, limit=pk / 1.6, redo=True)
check("P10 redo restarts from the original; the factor never goes below the minimum 0.65, original still there", rr["applied"] and rr["factor"] >= 0.63 and cp.backup(c1).exists())
c2 = make("b.mp4"); g2 = geo_of(c2)
check("P11 a very high peak is clamped at 0.65 (3.25 s kept)", abs(cp.apply(c2, g2, limit=pk / 5)["keep_secs"] - 3.25) < 0.06)
c3 = tmp / "short.mp4"; subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(cp.backup(c2)), "-t", "3.2", "-c:v", "libx264", str(c3)], check=True)
check("P12 a clip too short to slow is left alone", cp.apply(c3, g2, limit=pk / 2)["applied"] is False)
check("P13 missing file never raises", cp.apply(tmp / "nope.mp4", g2, limit=pk / 2)["applied"] is False)
c6 = make("f.mp4"); g6 = geo_of(c6)
r6 = cp.apply(c6, g6, limit=g6["motion_peak"] / 3, min_speed=1e6)
check("P16 every try below the lower threshold: still applied (slow is accepted, the original does not come back), in_range False", r6["applied"] is True and r6["in_range"] is False and cp.marker(c6).exists())
cp.apply(c6, g6, limit=g6["motion_peak"] / 3, min_speed=0.01, redo=True)
r7 = cp.apply(c6, g6, limit=g6["motion_peak"] / 3, min_speed=0.01, redo=True)
check("P17 lower threshold met: applied and the measured result is recorded", r7["applied"] and r7["result_peak"] is not None and r7["min_speed"] == 0.01)
os.environ.pop("PVS_PACE_INTERP", None)
check("P18 interpolation: mci by default (blend was judged jerky), blend only when asked", cp.interp_mode() == "mci" and (os.environ.__setitem__("PVS_PACE_INTERP", "blend") or cp.interp_mode() == "blend"))
ok_mci, _ = cp.render(c2 if False else cp.backup(c1), tmp / "mci.mp4", 5.04, 3.5, mode="mci")
check("P19 mci render works and keeps the length", ok_mci and abs(cp._duration(tmp / "mci.mp4") - 5.04) < 0.3)
os.environ.pop("PVS_PACE_INTERP", None)
check("P20 next_factor: in range = stop; too slow -> speed UP a little; too fast -> DOWN, clamped", cp.next_factor(0.7, 12, 15, 6) is None and cp.next_factor(0.7, 3, 15, 6) > 0.7 and cp.next_factor(0.8, 25, 15, 6) < 0.8 and cp.next_factor(0.7, 99, 15, 6) == 0.65 and cp.next_factor(0.7, None, 15, 6) is None and cp.next_factor(0.7, 4, 15) > 0.7)
c7 = make("g.mp4"); g7 = geo_of(c7)
r8 = cp.apply(c7, g7, limit=g7["motion_peak"] / 1.05)
check("P21 factor >= 0.9 (excess too small): clip untouched, no marker, no render", r8["applied"] is False and "too small" in r8["reason"] and not cp.marker(c7).exists() and not cp.backup(c7).exists())
r9 = cp.apply(c7, g7, limit=g7["motion_peak"] / 1.4)
check("P22 marker records tries, in_range, interp (mci by default), render time", r9["applied"] and r9["interp"] == "mci" and isinstance(r9["tries"], list) and 1 <= len(r9["tries"]) <= 3 and "in_range" in r9 and r9["render_secs"] >= 0 and json.loads(cp.marker(c7).read_text())["tries"] == r9["tries"])
c8 = make("h.mp4"); g8 = geo_of(c8)
seq = iter([5.0, 10.0, 10.5]); real = cp.measure_file
cp.measure_file = lambda path: {"ok": True, "motion_peak": next(seq)}
r10 = cp.apply(c8, {"ok": True, "motion_peak": 22.0}, limit=15.0, min_speed=6.0)
cp.measure_file = real
check("P23 result too SLOW (5 < 6): the factor is raised and re-tried (not the original); the final result is measured once", r10["applied"] and len(r10["tries"]) == 2 and r10["tries"][1]["factor"] > r10["tries"][0]["factor"] and r10["in_range"] and r10["result_peak"] == 10.5)
c9 = make("i.mp4"); g9 = geo_of(c9)
seq = iter([8.6, 20.0, 12.0]); cp.measure_file = lambda path: {"ok": True, "motion_peak": next(seq)}
r11 = cp.apply(c9, {"ok": True, "motion_peak": 38.44}, limit=26.0, min_speed=6.0)
cp.measure_file = real
check("P24 MINIMUM slowdown: of the valid tries (peak in range) the weakest slowdown is used, not the first that fits", r11["applied"] and len(r11["tries"]) == 2 and r11["factor"] == r11["tries"][1]["factor"] and r11["factor"] > r11["tries"][0]["factor"] and r11["in_range"])
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_analysis.py"), encoding="utf-8").read()
check("P14 hook: ONE place, BEFORE the Claude QC (independent of its answer), measures the clip itself", src.count("_cp.apply(") == 1 and "_cp.apply(video_path, _cp.measure_file(video_path))" in src and src.index("_cp.apply(") < src.index("first_frame = _extract_video_frame(video_path"))
f = tmp / "ev.jsonl"
f.write_text("\n".join(json.dumps(e) for e in [{"speed": "fast"}, {"speed": "slow", "pace": {"applied": True}}, {"speed": None}]), encoding="utf-8")
s = cs.summary(str(f))
check("P15 summary counts applied fixes", s["pace_applied"] == 1)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
