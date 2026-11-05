"""test_standard_enforce.py - integration check of the hook in vision_analysis.analyse_output (fakes only: no network, no spend). Run: python3 test_standard_enforce.py"""
import json, os, sys, tempfile, types
from pathlib import Path
import cv2, numpy as np
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_STANDARD_SHADOW_FILE"] = str(tmp / "shadow.jsonl")
os.environ["PVS_STANDARD_SHADOW"] = "1"
os.environ["PVS_STANDARD_ENFORCE"] = "0"  # explicit: vision_analysis load_dotenv() would otherwise bring in the real .env value
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client",):           # only to import vision_analysis in a sandbox without the provider package
    if name not in sys.modules:
        try:
            __import__(name)
        except Exception:
            sys.modules[name] = types.ModuleType(name)
import vision_analysis as va
import clip_standard as cs
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n); fails += 0 if c else 1
rng = np.random.default_rng(3)
base = cv2.GaussianBlur(rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8), (0, 0), 3)
for _ in range(120):
    x, y = int(rng.integers(0, 1500)), int(rng.integers(0, 800))
    cv2.rectangle(base, (x, y), (x + int(rng.integers(20, 90)), y + int(rng.integers(20, 90))), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
def make(name, fn, n=120):
    d = tmp / "jobZ" / "clips"; d.mkdir(parents=True, exist_ok=True)
    p = d / name
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 24, (480, 270))
    for i in range(n):
        x0, y0, cw, ch = fn(i / (n - 1)); w.write(cv2.resize(base[int(y0):int(y0 + ch), int(x0):int(x0 + cw)], (480, 270)))
    w.release(); return str(p)
push = make("push.mp4", lambda t: (800 - 400 * (1 - 0.12 * t), 450 - 225 * (1 - 0.12 * t), 800 * (1 - 0.12 * t), 450 * (1 - 0.12 * t)))
pan = make("pan.mp4", lambda t: (400 + 400 * t, 225, 800, 450))
photo = tmp / "photo.jpg"; cv2.imwrite(str(photo), base[:450, :800])
QC = {"people": False, "same_space": True, "severity": "none", "new_structure": [], "artifacts": False, "first_frame": "a", "last_frame": "b", "photo_elements": []}
JUDGE = '{"verdict": "pass", "reason": "ok", "direction": "static", "speed": "slow"}'
def fake_vision(images, prompt, max_tokens=250, model=None, usage_out=None):
    if usage_out is not None:
        usage_out["calls"] = usage_out.get("calls", 0) + 1
    return json.dumps(QC) if "ORIGINAL PHOTO" in prompt else JUDGE
va._claude_vision_call = fake_vision
va._extract_video_frame = lambda p, pos: str(photo)
a = va.analyse_output(push, str(photo), "large")
b = va.analyse_output(pan, str(photo), "large")
check("E1 enforcement OFF (default): a pan keeps the verdict of the existing QC (pass) and carries the shadow result", b["verdict"] == "pass" and b["standard_shadow"]["measured_verdict"] == "reject" and "standard_enforced" not in b)
check("E2 a push-in is pass either way", a["verdict"] == "pass" and a["standard_shadow"]["measured_verdict"] == "pass")
os.environ["PVS_STANDARD_ENFORCE"] = "1"
b2 = va.analyse_output(pan, str(photo), "large")
a2 = va.analyse_output(push, str(photo), "large")
check("E3 enforcement ON: the pan becomes reject with a readable issue, flagged as enforced", b2["verdict"] == "reject" and b2.get("standard_enforced") and any("Standard qualita'" in i for i in b2["issues"]))
check("E4 enforcement ON: the push-in is untouched", a2["verdict"] == "pass" and "standard_enforced" not in a2)
JUDGE = '{"verdict": "fail", "reason": "invented stuff"}'
a3 = va.analyse_output(push, str(photo), "large")
check("E5 the judge NEVER rejects: judge fail on a clean push-in leaves the verdict pass (recorded only)", a3["verdict"] == "pass" and a3["standard_shadow"]["standard_verdict"] == "reject" and a3["standard_shadow"]["measured_verdict"] == "pass")
QC = dict(QC, people=True)
c = va.analyse_output(push, str(photo), "large")
check("E6 an existing reject is never downgraded", c["verdict"] == "reject" and "standard_enforced" not in c)
QC = dict(QC, people=False)
os.environ["PVS_STANDARD_SHADOW"] = "0"
d = va.analyse_output(pan, str(photo), "large")
check("E7 kill switch: no shadow, no enforcement, verdict of the existing QC", d["verdict"] == "pass" and "standard_shadow" not in d)
os.environ["PVS_STANDARD_SHADOW"] = "1"
cs_eval = cs.evaluate
cs.evaluate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
e = va.analyse_output(pan, str(photo), "large")
cs.evaluate = cs_eval
check("E8 an exception inside the standard never breaks the QC", e["verdict"] == "pass" and "standard_shadow" not in e)
check("E9 the judge cost is added to the clip's claude_usage like the existing QC", a["claude_usage"].get("calls", 0) >= 2)
print("FAILS:", fails); sys.exit(1 if fails else 0)
