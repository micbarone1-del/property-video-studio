"""test_learning_apply.py - learning loop phases 3-4 (2026-11-25). Run: python3 test_learning_apply.py"""
import os, sys, json, tempfile, time, importlib
D = tempfile.mkdtemp()
os.environ.update(PVS_DATA_DIR=D, PVS_FAKE_PROVIDERS="0", PVS_SCENE_RISK="1")
for k in ("PVS_LEARN_APPLY", "PVS_LEARN_APPLY_UNTIL", "PVS_LEARNING_RULES_FILE", "PVS_SCENE_RISK_FILE"): os.environ.pop(k, None)
FAILS = 0
def chk(n, ok, info=""):
    global FAILS
    print(("PASS " if ok else "FAIL ") + n + (" " + str(info) if info and not ok else ""))
    if not ok: FAILS += 1
src = lambda f: open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), encoding="utf-8").read()
import scene_kinds, learning_apply as la, scene_risk as sr
import learning_loop as ll
RF = os.path.join(D, "learning_rules.json")
def put_rules(rules): open(RF, "w").write(json.dumps({"rules": rules}))
chk("A1 no rules file -> no rules, no error", la.load_rules() == [] and la.matching({}, "x", "bedroom", "t") == [])
chk("A2 one shared classifier", ll.anchor_kind is scene_kinds.anchor_kind and ll.plan_kind is scene_kinds.plan_kind)
open(RF, "w").write("{broken"); chk("A3 broken file -> no rules", la.load_rules() == [])
time.sleep(0.02)
put_rules([{"id": "l_qc:move=walk_in_explore&cat=bedroom", "label": "l_qc", "cond": [["move", "walk_in_explore"], ["cat", "bedroom"]]},
           {"id": "l_qc:tier=lux", "label": "l_qc", "cond": [["tier", "lux"]]},
           {"id": "l_qc:anchor_kind=generic", "label": "l_qc", "cond": [["anchor_kind", "generic"]]}])
sc = {"anchor": "the centre of the frame"}
chk("A4 matching with tier", set(la.matching(sc, "walk_in_explore", "bedroom", "lux")) == {"l_qc:move=walk_in_explore&cat=bedroom", "l_qc:tier=lux", "l_qc:anchor_kind=generic"}, la.matching(sc, "walk_in_explore", "bedroom", "lux"))
chk("A5 tier unknown -> tier rules do not match", "l_qc:tier=lux" not in la.matching(sc, "walk_in_explore", "bedroom", None))
chk("A6 apply OFF by default", la.apply_enabled() is False)
os.environ["PVS_LEARN_APPLY"] = "1"
chk("A7 switch without expiry date stays OFF", la.apply_enabled() is False)
os.environ["PVS_LEARN_APPLY_UNTIL"] = "2026-12-31"
chk("A8 switch + date -> ON; past date -> OFF", la.apply_enabled("2026-12-01") is True and la.apply_enabled("2027-01-01") is False)

def ev(job, move, bad, ts, stage="first", **x):
    return {"ts": ts, "job": job, "scene": "s", "cat": "bedroom", "move": move, "tier": "lux", "stage": stage, "verdict": "flag" if bad else "pass", **x}
base = [ev(f"j{i}", "walk_in_explore", i % 2 == 0, f"2026-11-01T00:{i:02d}:00") for i in range(20)] + \
       [ev(f"k{i}", "outward_view", i % 10 == 0, f"2026-11-02T00:{i:02d}:00") for i in range(20)]
chk("A9 alternative movement chosen from the registry", la.pick_alt_move("walk_in_explore", base) == "outward_view")
chk("A10 no alternative when data is thin", la.pick_alt_move("walk_in_explore", base[:5]) is None and la.pick_alt_move("zzz", base) is None)
with open(sr._file(), "w") as f:
    for e in base: f.write(json.dumps(e) + "\n")
scene = {"pov_movement": "walk_in_explore", "category": "bedroom", "anchor": "the wardrobe", "caption": "keep", "voiceover": "keep"}
before = json.dumps({k: v for k, v in scene.items() if k != "pov_movement"})
chk("A11 on_plan changes only the movement", la.on_plan(scene, "bedroom") is True and scene["pov_movement"] == "outward_view" and scene["learn_prev_move"] == "walk_in_explore"
    and json.dumps({k: v for k, v in scene.items() if k not in ("pov_movement", "learn_prev_move", "learn_applied")}) == before, scene)
s2 = {"pov_movement": "walk_in_explore", "category": "kitchen"}
chk("A12 rule not about movement -> shadow only", la.on_plan(s2, "kitchen") is False and s2["pov_movement"] == "walk_in_explore")
os.environ["PVS_LEARN_APPLY"] = "0"
s3 = {"pov_movement": "walk_in_explore", "category": "bedroom"}
chk("A13 switch off -> nothing changes", la.on_plan(s3, "bedroom") is False and s3["pov_movement"] == "walk_in_explore")
chk("A14 garbage input never raises", la.on_plan(None) is False and la.on_plan("x") is False and la.matching(None, None, None, None) is not None)
os.environ["PVS_LEARN_APPLY"] = "1"

# record carries shadow + applied fields
open(sr._file(), "w").close()
sr.record("jobX", "sc_1", {"category": "bedroom", "anchor": "the centre of the frame", "learn_applied": ["r1"], "learn_prev_move": "walk_in_explore"}, "flag", stage="first", movement="walk_in_explore", tier="lux")
e = json.loads(open(sr._file()).read().strip())
chk("A15 registry line carries learn_shadow / learn_applied / learn_prev_move", e.get("learn_applied") == ["r1"] and e.get("learn_prev_move") == "walk_in_explore" and len(e.get("learn_shadow", [])) == 3, e)
rep = la.report([e])
chk("A16 report counts firing scenes and flags due date", rep["scenes_firing"] == 1 and rep["target"] == 40 and rep["per_rule"], rep)

# revert check
good = [ev(f"b{i}", "x", i % 4 == 0, f"2026-11-01T01:{i:02d}:00") for i in range(30)]
app_ok = [ev(f"a{i}", "y", False, f"2026-11-10T01:{i:02d}:00", learn_applied=["r"]) for i in range(12)] + [ev(f"c{i}", "x", i % 4 == 0, f"2026-11-10T02:{i:02d}:00") for i in range(12)]
chk("A17 applied scenes better, overall not worse -> ok", la.revert_check(good + app_ok, write=False)["status"] == "ok", la.revert_check(good + app_ok, write=False))
app_bad = [ev(f"a{i}", "y", i < 9, f"2026-11-10T01:{i:02d}:00", learn_applied=["r"]) for i in range(12)] + [ev(f"c{i}", "x", i % 4 == 0, f"2026-11-10T02:{i:02d}:00") for i in range(12)]
chk("A18 applied scenes not better than the rest -> REVERT", la.revert_check(good + app_bad, write=False)["status"] == "REVERT")
chk("A19 too few applied scenes -> no decision", la.revert_check(good + app_ok[:3], write=False)["status"] == "not enough applied scenes")
la.revert_check(good + app_bad, write=True)
chk("A20 revert file switches apply OFF", os.path.exists(la.revert_file()) and la.apply_enabled("2026-12-01") is False)
os.remove(la.revert_file())

# export from learning_loop
rep = {"video": {"labels": {"l_qc": {"holding": [{"cond": [("cat", "bedroom"), ("move", "m")], "rate": .6, "hold_rate": .5, "hold_baseline": .3, "n": 12, "hold_n": 11}], "all": []}}}}
ex = ll.export_rules(rep)
chk("A21 export keeps only holding rules with an id", len(ex["rules"]) == 1 and ex["rules"][0]["id"] == "l_qc:cat=bedroom&move=m", ex)
a = src("api_server.py")
chk("A22 hook is wrapped in try and calls only on_plan", "learning_apply.on_plan(_sc)" in a and a.count("learning_apply") == 2)
chk("A23 production modules do not import learning_loop", all(("import learning_loop" not in src(x) and "from learning_loop" not in src(x)) for x in ("api_server.py", "scene_risk.py", "learning_apply.py", "scene_kinds.py")))
chk("A24 learning_apply never writes into jobs/", "jobs" not in src("learning_apply.py").replace("jobs not used", "").replace("jobs that", "").replace("unseen jobs", ""))
print("FAILS", FAILS); sys.exit(1 if FAILS else 0)
