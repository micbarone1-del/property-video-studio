"""test_exp_conservative.py - offline checks of exp_conservative (no network, no spend)."""
import json, os, sys, tempfile, types
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_JOBS_DIR"] = str(tmp)
os.environ["PVS_VOLUME_SCRATCH"] = str(tmp / "scratch")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
md = types.ModuleType("movement_director"); md.STATIC_SCALE = 1.05; md.TAIL = "smooth"
md.forward_sentence = lambda t, s=False: "x"; md._clip_scale = lambda t: 1.1
vg = types.ModuleType("video_generation"); vg._LUMA_MOVEMENT_TOKENS = {"subtle_rotate": "almost static shot with imperceptibly subtle 3D micro-parallax"}
sys.modules["movement_director"] = md; sys.modules["video_generation"] = vg
import exp_conservative as ec
import exp_facade as ef
check("C1 scenes parsed, bad items skipped", ec.parse_scenes("a:1, b:2 ,bad,c:x") == [("a", 1), ("b", 2)])
check("C2 default list = 7 scenes", len(ec.parse_scenes(ec.DEFAULT_SCENES)) == 7)
p = ec.static_plan({"move": "forward", "target": "sofa", "scale": 1.12, "sentence": "push", "reason": "r"})
check("C3 static plan: move static, token sentence, no target, reason kept", p["move"] == "static" and "micro-parallax" in p["sentence"] and p["target"] == "" and p["reason"] == "r")
check("C4 luma still prompt per room, default room", ec.luma_still_prompt("kitchen") == "Stationary view of the kitchen. Locked off camera." and "room" in ec.luma_still_prompt("zzz"))
check("C5 luma prompt passes the Luma lint", ef.lint(ec.luma_still_prompt("living")) == {"forbidden": [], "movable": []})
(tmp / "j1").mkdir(); (tmp / "j1" / "job_meta.json").write_text(json.dumps({"scenes_config": [{"category": "living"}, {"room": "Bathrooms"}]}))
check("C6 category read from the draft (category or room, lower case)", ec.category_of("j1", 0) == "living" and ec.category_of("j1", 1) == "bathrooms" and ec.category_of("nojob", 0) == "")
calls = []
def fake_capture(job, i, force_building=False, transform=None):
    pl = {"move": "forward", "target": "sofa", "scale": 1.12, "sentence": "s", "travel": "short"}
    ef.capture_prompt.last_plan = pl
    t = transform(dict(pl)) if transform else pl
    calls.append(t["move"]); return f"prompt-{t['move']}-{t.get('scale')}", f"{t['move']} -> {t.get('target')}", Path("/x.jpg")
ef.capture_prompt = fake_capture
cases = ec.build_cases_r([("j1", 0)])
check("C7 one case with 4 distinct variants R0..R3", len(cases) == 1 and sorted(cases[0]["prompts"]) == ["R0", "R1", "R2", "R3"])
check("C8 R1 is built from the static plan, R0 and R3 from the director's", cases[0]["prompts"]["R1"].startswith("prompt-static") and cases[0]["prompts"]["R0"].startswith("prompt-forward"))
check("C9 R2 is the Luma still phrase", cases[0]["prompts"]["R2"] == "Stationary view of the living room. Locked off camera.")
check("C10 without --go nothing is spent and the budget guard works", ec.main(["--scenes", "j1:0"]) == 0 and ec.main(["--scenes", "j1:0", "--budget", "0.1"]) == 1)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
