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
check("S19 measured_verdict: only geometry, None when not measured", cs.measured_verdict({"ok": True, "new_max": 0.21})[0] == "reject" and cs.measured_verdict({"ok": True, "new_max": 0.2})[0] == "pass" and cs.measured_verdict({"ok": False})[0] is None)
check("S20 evaluate(): a pan is a MEASURED reject even when the judge passes; a push-in is not", r2["measured_verdict"] == "reject" and r1["measured_verdict"] == "pass" and r3["measured_verdict"] == "pass")
check("S21 zoom_rate recorded (push-in 12%: small; speed flag off)", r1["geo"]["zoom_rate"] < 0.1 and r1["speed_over_limit"] is False)
os.environ.pop("PVS_STANDARD_ENFORCE", None)
check("S22 enforce() is OFF by default and needs the switch", cs.enforce() is False)
os.environ["PVS_STANDARD_ENFORCE"] = "1"
check("S23a enforce() stays OFF with only the old switch (2026-11-16: geometry no longer rejects)", cs.enforce() is False)
os.environ["PVS_STANDARD_GEOMETRY_REJECT"] = "1"
check("S23 enforce() ON only with BOTH switches", cs.enforce() is True)
os.environ["PVS_STANDARD_SHADOW"] = "0"
check("S24 enforce() is OFF when the shadow evaluation is off (kill switch wins)", cs.enforce() is False)
os.environ["PVS_STANDARD_SHADOW"] = "1"; os.environ.pop("PVS_STANDARD_ENFORCE"); os.environ.pop("PVS_STANDARD_GEOMETRY_REJECT", None)
check("S25 hook: enforcement only when enforce() and measured reject, never touches the judge verdict path", "_cs.enforce()" in src and 'measured_verdict") == "reject"' in src and src.count('out["verdict"] = "reject"') == 1)

calls.clear(); cs.evaluate(pan, ask=ask_pass, plan={"move": "forward", "travel": "short", "target": "the door"})
check("S26 plan given: the same judge call also asks how the camera compares with the plan (no extra call)", "PLANNED" in calls[0][1] and "plan_check" in calls[0][1] and len(calls) == 1)
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S27 no plan: prompt unchanged", "PLANNED" not in calls[0][1])
rp = cs.evaluate(pan, ask=lambda im, p, u: '{"verdict": "pass", "plan_check": {"past_target": true}}', plan={"move": "static", "travel": "short", "target": "x"})
check("S28 plan_check passes through and is recorded; verdict untouched", rp["judge"]["plan_check"]["past_target"] is True and rp["plan"]["move"] == "static" and '"plan_check": j.get("plan_check")' in open(cs.__file__).read())
# 2026-11-23: extra questions (revealed, extended_scene) in the SAME call, shadow only, default OFF
os.environ.pop("PVS_STANDARD_EXTRA", None)
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S29 extra OFF by default: prompt has no extra questions", "extended_scene" not in calls[0][1] and cs.extra_enabled() is False)
os.environ["PVS_STANDARD_EXTRA"] = "1"
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S30 extra ON: the two questions travel in the same single call, verdict rules untouched", len(calls) == 1 and "extended_scene" in calls[0][1] and "revealed" in calls[0][1] and cs.JUDGE_PROMPT.split("{n}")[1][:40] in calls[0][1])
ans = '{"verdict": "pass", "speed": "slow", "direction": "static", "revealed": [{"what": "wall", "frames": "4-6", "in_frame1": "no"}, {"what": "lamp", "frames": "2", "in_frame1": "hint"}, "junk"], "extended_scene": true}'
rx = cs.evaluate(pan, ask=lambda im, p, u: ans)
rn = cs.evaluate(pan, ask=lambda im, p, u: '{"verdict": "pass", "speed": "slow", "direction": "static"}')
check("S31 answers parsed; standard_verdict is the same with or without the extra keys", rx["standard_verdict"] == rn["standard_verdict"] and rx["judge"]["speed"] == "slow")
check("S32 extra_flags counts no/hint, ignores junk, never raises", cs.extra_flags(rx["judge"]) == {"revealed_no": 1, "revealed_hint": 1, "extended_scene": True} and cs.extra_flags(None) == {} and cs.extra_flags({"verdict": "pass"}) == {} and cs.extra_flags({"revealed": "x", "extended_scene": "yes"}) == {"revealed_no": 0, "revealed_hint": 0, "extended_scene": None})
ef = tmp / "extra.jsonl"; os.environ["PVS_STANDARD_SHADOW_FILE"] = str(ef)
cs.record(pan, rx); cs.record(pan, rn)
evs = [json.loads(l) for l in ef.read_text().splitlines()]
check("S33 record: extra fields only on the clip that answered them", evs[0].get("revealed_no") == 1 and evs[0].get("extended_scene") is True and "revealed_no" not in evs[1])
sm = cs.summary(str(ef))
check("S34 summary counts the extra answers", sm["extra"]["asked"] == 1 and sm["extra"]["revealed_no"] == 1 and sm["extra"]["extended"] == 1 and sm["extra"]["flag_and_geo"] in (0, 1))
os.environ.pop("PVS_STANDARD_EXTRA", None)
# 2026-11-23 v2: extra keys inside the answer example + tolerant parse of a two-object answer
RAW_A = '{"invented":[{"frames":"3-6","what":"A light grey curtain appears on the right edge."}],"animated":[],"direction":"sideways","speed":"slow","verdict":"review","reason":"needs a check."}\n\nExtra keys:\n\n"revealed": [{"what":"Curtain","frames":"3-6","in_frame1":"hint"}],\n"extended_scene": false\n\nHere is the full JSON with the extra keys merged in:\n\n{"invented":[],"animated":[],"direction":"sideways","speed":"slow","verdict":"review","reason":"x","revealed":[{"what":"Curtain","frames":"3-6","in_frame1":"hint"},{"what":"Tile","frames":"4-6","in_frame1":"no"}],"extended_scene":false}'
RAW_B = '{"invented":[{"frames":"4-6","what":"white car"}],"animated":[],"direction":"sideways","speed":"slow","verdict":"fail","reason":"Vehicles move."}\n\nExtra keys:\n\n{"revealed":[{"what":"side wall","frames":"5-6","in_frame1":"hint"}],"extended_scene":true}'
os.environ["PVS_STANDARD_EXTRA"] = "1"
pe = cs.judge_prompt_extra()
check("S35 extra prompt: the keys sit inside the answer example, single-object instruction, old rules untouched", pe.index("ONE single JSON object") < pe.index('"extended_scene": false}') and "Add two keys" not in pe and cs.JUDGE_PROMPT.split("{n}")[1][:40] in pe and pe.format(n=6).count("{") == pe.format(n=6).count("}"))
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S36 evaluate sends exactly that prompt, once", len(calls) == 1 and calls[0][1].startswith(pe.format(n=6)[:200]) and "ONE single JSON object" in calls[0][1])
os.environ.pop("PVS_STANDARD_EXTRA", None)
calls.clear(); cs.evaluate(pan, ask=ask_pass)
check("S37 extra OFF: prompt identical to the original judge prompt", calls[0][1] == cs.JUDGE_PROMPT.format(n=6) and "ONE single JSON" not in calls[0][1])
check("S41 switch OFF: a two-object answer is still unusable (behaviour unchanged)", cs.parse_judge(RAW_A) is None and cs.parse_judge(RAW_B) is None)
os.environ["PVS_STANDARD_EXTRA"] = "1"
pa, pb = cs.parse_judge(RAW_A), cs.parse_judge(RAW_B)
check("S38 two-object answers are recovered (merged), verdict and extra keys present", pa["verdict"] == "review" and len(pa["revealed"]) == 2 and pb["verdict"] == "fail" and pb["extended_scene"] is True and pb["revealed"][0]["in_frame1"] == "hint")
check("S39 plain JSON parses as before; garbage and verdict-less fragments stay None", cs.parse_judge('{"verdict": "pass", "speed": "slow"}')["verdict"] == "pass" and cs.parse_judge("no json here") is None and cs.parse_judge('{"revealed": []} and {"x": 1}') is None and cs.parse_judge('{"verdict": "pa') is None)
rb = cs.evaluate(pan, ask=lambda im, p, u: RAW_B)
check("S40 evaluate with a two-object answer: judge usable, no error", rb["judge"] is not None and rb["error"] is None and rb["judge"]["verdict"] == "fail")
os.environ.pop("PVS_STANDARD_EXTRA", None)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
