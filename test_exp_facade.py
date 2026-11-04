"""test_exp_facade.py - offline checks of exp_facade (no network, no spend)."""
import json, os, sys, tempfile, types
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_JOBS_DIR"] = str(tmp)
os.environ["PVS_VOLUME_SCRATCH"] = str(tmp / "scratch")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_facade as ef
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
(tmp / "j1").mkdir(); (tmp / "j2").mkdir()
(tmp / "j1" / "job_meta.json").write_text(json.dumps({"scenes_config": [{"category": "exterior"}, {"category": "living"}, {"category": "exterior"}]}))
(tmp / "j2" / "job_meta.json").write_text(json.dumps({"scenes_config": [{"category": "kitchen"}, {"room": "Exterior"}]}))
check("F1 facade scenes = the exterior ones, any draft", ef.facade_scenes(["j1", "j2", "nojob"]) == [("j1", 0), ("j1", 2), ("j2", 1)])
# fake production modules: capture_prompt must record the prompt of the Luma call, send nothing, and restore everything
md = types.ModuleType("movement_director")
md.plan = lambda *a, **k: {"move": "static", "target": "centre of the frame", "scale": 1.05, "travel": "short", "sentence": "almost static"}
md.last_plan = lambda p: {"move": "forward", "target": "ground"}
md._clip_scale = lambda t: 1.12; md.TAIL = "smooth tail"; md.STATIC_SCALE = 1.05
md.forward_sentence = lambda target, slow=False: f"Very slow push-in toward {target}"
vg = types.ModuleType("video_generation"); vg.LUMA_DIRECT = True; vg.FAL_FALLBACK_ENABLED = True
vg._generate_luma_direct = lambda *a, **k: "REAL-SENT"; vg._generate_luma = lambda *a, **k: "FAL"; vg._generate_veo = lambda *a, **k: "VEO"
seen = {}
def gvs(img, dur, out, **kw):
    plan = md.plan("p", {}, "c")
    r = vg._generate_luma_direct("url", "PROMPT-X " + plan["sentence"] + " " + plan["move"], 5)
    seen["direct"] = r; seen["fal"] = vg.FAL_FALLBACK_ENABLED
    return False
vg.generate_video_single = gvs
sys.modules["movement_director"] = md; sys.modules["video_generation"] = vg
real_plan = md.plan
ef.ev.scene_args = lambda j, i: ("/x.jpg", {}, {})
p, plan, img = ef.capture_prompt("j1", 0)
check("F2 the production prompt is captured with the director's own plan (G)", p == "PROMPT-X almost static static" and plan == "static -> centre of the frame")
check("F3 nothing is sent while capturing and the fal fallback is off", seen["direct"] is None and seen["fal"] is False)
p2, plan2, _ = ef.capture_prompt("j1", 0, True)
check("F4b the plan shown is the one really used (building target), not the director's history", plan2 == "forward -> the base of the front wall of the building")
check("F4 the building variant overrides move and target after the director answers", p2 == "PROMPT-X Very slow push-in toward the base of the front wall of the building forward")
check("F5 everything is restored afterwards", vg._generate_luma_direct("u", "p", 5) == "REAL-SENT" and vg.FAL_FALLBACK_ENABLED is True and md.plan is real_plan)
vg.LUMA_DIRECT = False
try:
    ef.capture_prompt("j1", 0); refused = False
except SystemExit:
    refused = True
check("F6 refuses when the production Luma path is off (no fal.ai spend)", refused)
check("F7 three variants and the plan costs 3 x reps x scenes", ef.VARIANTS == ("G", "B", "S") and ef.run(["j1", "j2"], 2, 4.5, 12, False) == 0)
# round 2 (D1 / D2)
pr = "x frozen photograph of an empty, still room: every wall, window, door, curtain, piece of furniture, fixture and decoration keeps exactly the same place, shape"
n, miss = ef.frozen_outdoor(pr)
check("F8 the interior list becomes the outdoor frozen-scene list, once, no 'no people' wording", miss == 0 and "parked vehicle" in n and "curtain" not in n and "no people" not in n.lower() and n.endswith("place, shape"))
check("F9 a prompt without the clause is reported, not silently kept", ef.frozen_outdoor("nothing here")[1] == 1)
sen = ef.minimal_sentence("the facade")
check("F10 the minimal move has a framing goal and no metres", "slightly larger" in sen and "metre" not in sen and "the facade" in sen)
mp = ef.minimal_plan({"move": "forward", "target": "the facade", "scale": 1.12})
check("F11 minimal plan keeps the director's anchor and shrinks the end view", mp["target"] == "the facade" and mp["scale"] == 1.05 and "slightly larger" in mp["sentence"])
check("F12 a static plan of the director is left alone", ef.minimal_plan({"move": "static", "target": "centre"}) == {"move": "static", "target": "centre"})
check("F13 round 2 is D1 and D2 and costs 2 x reps x scenes", ef.VARIANTS_D == ("D1", "D2") and ef.run(["j1", "j2"], 2, 4.5, 12, False, ef.VARIANTS_D) == 0)
os.environ["PVS_X"] = "keep"
with ef._env(PVS_X="tmp"):
    inside = os.environ["PVS_X"]
check("F14 the env override is restored", inside == "tmp" and os.environ["PVS_X"] == "keep")
sys.exit(1 if fails else 0)
