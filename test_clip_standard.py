"""test_clip_standard.py - offline checks of the clip acceptance standard (shadow mode). No network, no spend. Run: python3 test_clip_standard.py"""
import json, os, sys, tempfile, types
from pathlib import Path
import cv2, numpy as np
tmp = Path(tempfile.mkdtemp())
td = tmp / "tmpdir"; td.mkdir(); tempfile.tempdir = str(td)
os.environ["PVS_STANDARD_SHADOW_FILE"] = str(tmp / "shadow.jsonl")
os.environ["PVS_STANDARD_SHADOW"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clip_standard as cs
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
rng = np.random.default_rng(3)
base = cv2.GaussianBlur(rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8), (0, 0), 3)
for _ in range(120):
    x, y = int(rng.integers(0, 1500)), int(rng.integers(0, 800))
    cv2.rectangle(base, (x, y), (x + int(rng.integers(20, 90)), y + int(rng.integers(20, 90))), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
def make(job, name, fn, n=120, fps=24):
    d = tmp / job / "clips"; d.mkdir(parents=True, exist_ok=True)
    p = d / name
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps, (480, 270))
    for i in range(n):
        x0, y0, cw, ch = fn(i / (n - 1))
        w.write(cv2.resize(base[int(y0):int(y0 + ch), int(x0):int(x0 + cw)], (480, 270)))
    w.release()
    return p
cx, cy, W0, H0 = 800, 450, 800, 450
push = make("jobA", "sc_1.mp4", lambda t: (cx - W0 * (1 - 0.12 * t) / 2, cy - H0 * (1 - 0.12 * t) / 2, W0 * (1 - 0.12 * t), H0 * (1 - 0.12 * t)))
pan = make("jobA", "sc_2.mp4", lambda t: (cx - W0 / 2 + 400 * t, cy - H0 / 2, W0, H0))
calls = []
def ask_pass(imgs, prompt, usage):
    calls.append((len(imgs), prompt)); 
    if usage is not None: usage["calls"] = usage.get("calls", 0) + 1
    return 'Sure: {"direction": "toward_main_subject", "speed": "slow", "verdict": "pass", "reason": "ok"}'
ask_fail = lambda imgs, prompt, usage: '{"direction": "backward", "speed": "slow", "verdict": "fail", "reason": "curtain animates"}'
ask_junk = lambda imgs, prompt, usage: "no json here"
u = {}
r1 = cs.evaluate(push, usage_out=u, ask=ask_pass)
check("S1 push-in + judge pass = standard pass, geometry measured", r1["standard_verdict"] == "pass" and r1["geo"]["ok"] and r1["geo"]["new_max"] < 0.06 and not r1["reasons"])
check("S2 the judge gets 6 key frames and the 6-frame prompt", calls[0][0] == 6 and "6 frames" in calls[0][1])
r2 = cs.evaluate(pan, ask=ask_pass)
check("S3 big pan (new area > 20%) = reject by geometry even if the judge passes", r2["standard_verdict"] == "reject" and r2["geo"]["new_max"] > 0.2 and "new area" in r2["reasons"][0])
r3 = cs.evaluate(push, ask=ask_fail)
check("S4 judge fail inside the visible area = reject by content", r3["standard_verdict"] == "reject" and "judge: fail" in r3["reasons"][0])
r4 = cs.evaluate(push, ask=lambda i, p, u: '{"verdict": "review", "reason": "x"}')
check("S5 judge review alone never rejects", r4["standard_verdict"] == "pass")
r5 = cs.evaluate(push, ask=ask_junk)
check("S6 unusable judge answer = recorded as error, geometry still decides (pass here), no crash", r5["error"] == "judge answer unusable" and r5["standard_verdict"] == "pass")
r6 = cs.evaluate(tmp / "missing.mp4", ask=ask_pass)
check("S7 missing file never raises", r6["standard_verdict"] is None and r6["error"] is not None)
check("S8 decide(): tracking lost is not a reject", cs.decide({"ok": False, "why": "tracking lost"}, {"verdict": "pass"})[0] == "pass")
check("S9 decide(): limit is strict > 0.20", cs.decide({"ok": True, "new_max": 0.20}, None)[0] == "pass" and cs.decide({"ok": True, "new_max": 0.21}, None)[0] == "reject")
check("S10 no temp key frames are left behind", not any(td.glob("*_std.jpg")))
check("S11 record(): job and scene from the clip path", cs.record(pan, r2) and json.loads(Path(os.environ["PVS_STANDARD_SHADOW_FILE"]).read_text().splitlines()[0])["job"] == "jobA")
cs.record(push, r1); cs.record(push, r3)
s = cs.summary()
check("S12 summary counts clips, rejects, reasons", s["clips"] == 3 and s["standard_reject"] == 2 and s["by_geometry"] == 1 and s["by_judge"] == 1)
os.environ["PVS_STANDARD_SHADOW"] = "0"
check("S13 kill switch", cs.enabled() is False)
os.environ["PVS_STANDARD_SHADOW"] = "1"; os.environ["PVS_FAKE_PROVIDERS"] = "1"
check("S14 fake providers never evaluated", cs.enabled() is False)
os.environ.pop("PVS_FAKE_PROVIDERS")
os.environ["PVS_STANDARD_FEED_NUMBER"] = "1"
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S15 optional number fed to the judge only when switched on", "Software measurement" in calls[0][1])
os.environ.pop("PVS_STANDARD_FEED_NUMBER")
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S16 default: prompt unchanged (calibrated)", "Software measurement" not in calls[0][1])
# analyse_output hook: verdict unchanged, shadow attached, usage merged
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_analysis.py")).read()
check("S17 hook sits in analyse_output, once, after the verdict is built", src.count("clip_standard") == 2 and src.index("standard_shadow") > src.index("def analyse_output"))
import exp_judge as ej, exp_rotation as er
check("S18 experiment tools use the production copy (no duplicate)", ej.JUDGE_PROMPT is cs.JUDGE_PROMPT and er.measures is cs.measures and er.compose is cs.compose)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
