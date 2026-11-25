"""test_learning_cycle.py - the automatic loop (2026-11-25). Run: python3 test_learning_cycle.py"""
import json, os, random, sys, tempfile, time, types, importlib
D = tempfile.mkdtemp(); J = tempfile.mkdtemp()
os.environ.update(PVS_DATA_DIR=D, PVS_FAKE_PROVIDERS="0", PVS_SCENE_RISK="1", PVS_SCENE_RISK_FILE=os.path.join(D, "scene_risk_events.jsonl"), PVS_JOBS_DIR=J)
for k in ("PVS_LEARN_APPLY", "PVS_LEARN_APPLY_UNTIL", "PVS_LEARNING_RULES_FILE"): os.environ.pop(k, None)
F = 0
def chk(n, ok, info=""):
    global F
    print(("PASS " if ok else "FAIL ") + n + (" " + str(info)[:300] if info and not ok else ""))
    F += 0 if ok else 1
import learning_cycle as lc, learning_apply as la
EV = os.environ["PVS_SCENE_RISK_FILE"]
sent = []
note = lambda subj, body: sent.append(subj)
def write_events(evs):
    with open(EV, "w") as f:
        for e in evs: f.write(json.dumps(e) + "\n")
def mk(n, seed=3, shadow_ids=None, t0="2026-06-01T00:00:00", stage="first", signal=True):
    rnd = random.Random(seed); out = []
    for i in range(n):
        cat = rnd.choice(["living", "kitchen", "bedroom", "bath"]); mv = rnd.choice(["outward_view", "walk_a", "walk_b"])
        hit = cat == "kitchen" and mv == "outward_view"
        bad = rnd.random() < (0.75 if (signal and hit) else 0.12)
        e = {"ts": f"2026-06-{1 + i // 40:02d}T{i % 24:02d}:{i % 60:02d}:00", "job": f"job{i // 3}", "scene": f"s{i}", "cat": cat, "move": mv, "tier": "luma", "stage": stage, "verdict": "flag" if bad else "pass"}
        if shadow_ids and hit: e["learn_shadow"] = shadow_ids
        out.append(e)
    return out
# C1 empty
write_events([])
r = lc.run(today="2026-11-25", notify=note)
chk("C1 no data: ok, 0 rules, nothing sent, files written, apply off", r["ok"] and r["rules_holding"] == 0 and not sent and not r["apply_on"] and os.path.exists(os.path.join(D, "learning_rules.json")) and os.path.exists(lc.status_file()), r)
# C2 planted signal, no shadow evidence yet
write_events(mk(900))
r = lc.run(today="2026-11-25", notify=note)
rid = [i for i in r["evidence"] if "move=outward_view" in i and "cat=kitchen" in i]
chk("C2 planted signal: a held rule with a movement is found, NOT applied (no shadow evidence, 0 days)", r["rules_holding"] >= 1 and rid and not r["apply_on"] and not sent, r)
rid = rid[0]
# C3 backdate the clock, add shadow evidence on later scenes
st = lc.load_state(); st["first_seen"][rid] = {"date": "2026-11-01", "ts": "2026-11-01T00:00:00"}; lc._write(lc.state_file(), st)
late = mk(800, seed=9, shadow_ids=[rid], stage="first")   # >= 40 scenes fire in shadow (the phase-3 target)
for e in late: e["ts"] = "2026-11-10T" + e["ts"][11:]
write_events(mk(900) + late)
r = lc.run(today="2026-11-25", notify=note)
chk("C3 fully proven: apply ON with expiry, ONE notification", r["apply_on"] and r["apply_until"] == "2026-12-09" and sent == ["Ciclo di apprendimento: regola provata e applicata"], (r, sent))
chk("C3b learning_apply sees the automatic switch and only the proven rule", la.apply_enabled("2026-11-26") and la.allowed_rule_ids("2026-11-26") == [rid], la.allowed_rule_ids("2026-11-26"))
sc = {"pov_movement": "outward_view", "category": "kitchen"}
chk("C3c on_plan changes the movement of a matching scene, via the automatic switch", la.on_plan(sc, "kitchen", "luma") is True and sc["pov_movement"] != "outward_view" and sc["learn_applied"] == [rid], sc)
sc2 = {"pov_movement": "outward_view", "category": "bath"}
chk("C3d a scene the rule does not match is untouched", la.on_plan(sc2, "bath", "luma") is False and sc2["pov_movement"] == "outward_view")
# C4 second run same day: no second notification
r = lc.run(today="2026-11-25", notify=note)
chk("C4 second run: still ON, no new notification", r["apply_on"] and len(sent) == 1, sent)
# C5 expiry
chk("C5 after the expiry date apply is OFF", la.apply_enabled("2026-12-10") is False)
# C6 not enough days
st = lc.load_state(); st["first_seen"][rid] = {"date": "2026-11-22", "ts": "2026-11-22T00:00:00"}; st["apply"] = {"on": False}; lc._write(lc.state_file(), st)
for e in late: e["ts"] = "2026-11-23T" + e["ts"][11:]
write_events(mk(900) + late); sent.clear()
r = lc.run(today="2026-11-25", notify=note)
chk("C6 held for 3 days only: not proven", not r["apply_on"] and not sent, r)
# C7 shadow evidence too weak (rule fires but is not worse than the rest)
st = lc.load_state(); st["first_seen"][rid] = {"date": "2026-11-01", "ts": "2026-11-01T00:00:00"}; lc._write(lc.state_file(), st)
weak = mk(800, seed=9, shadow_ids=[rid], signal=False)
for e in weak: e["ts"] = "2026-11-10T" + e["ts"][11:]
write_events(mk(900) + weak)
r = lc.run(today="2026-11-25", notify=note)
chk("C7 shadow shows no excess in production scenes: not proven even if it held on the hold-out", not r["apply_on"] and not sent, r["evidence"].get(rid))
# C8 revert
write_events(mk(900) + late); st = lc.load_state(); st["first_seen"][rid] = {"date": "2026-11-01", "ts": "2026-11-01T00:00:00"}; lc._write(lc.state_file(), st)
r = lc.run(today="2026-11-25", notify=note); sent.clear()
worse = []
for i in range(30):
    worse.append({"ts": f"2026-11-24T10:{i:02d}:00", "job": f"w{i}", "scene": "s", "cat": "kitchen", "move": "walk_a", "tier": "luma", "stage": "first", "verdict": "flag" if i < 24 else "pass", "learn_applied": [rid]})
write_events(mk(900) + late + worse)
r = lc.run(today="2026-11-26", notify=note)
chk("C8 applied scenes worse -> switched OFF, revert file written, ONE notification", (not r["apply_on"]) and la.revert_file().exists() and sent == ["Ciclo di apprendimento: regola spenta"], (r, sent))
chk("C8b the revert file blocks the manual switch too", (os.environ.update(PVS_LEARN_APPLY="1", PVS_LEARN_APPLY_UNTIL="2027-01-01") or la.apply_enabled("2026-11-27")) is False)
os.environ.pop("PVS_LEARN_APPLY"); os.environ.pop("PVS_LEARN_APPLY_UNTIL")
sent.clear(); lc.run(today="2026-11-27", notify=note)
chk("C8c after a revert nothing is applied or notified again", not la.apply_enabled("2026-11-27") and not sent, sent)
if la.revert_file().exists(): os.remove(la.revert_file())
# C9 never raises
def boom(*a): raise RuntimeError("mail down")
st = lc.load_state(); st["first_seen"][rid] = {"date": "2026-11-01", "ts": "2026-11-01T00:00:00"}; st["apply"] = {"on": False}; lc._write(lc.state_file(), st)
write_events(mk(900) + late)
chk("C9 a failing notifier never raises out of run()", isinstance(lc.run(today="2026-11-25", notify=boom), dict))
# C10 maintenance_scheduler wiring
src = lambda f: open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), encoding="utf-8").read()
ms = src("maintenance_scheduler.py")
chk("C10 registered once, every 1440 minutes, lazy import", '"learning_cycle":        1440' in ms and '"learning_cycle":       check_learning_cycle' in ms and "import learning_cycle\n" in ms and ms.count("import learning_cycle") == 1)
lcs = src("learning_cycle.py")
chk("C11 exactly two notification texts, nothing under jobs/ written", lcs.count("notify(\"") == 2 and "jobs_dir /" not in lcs.replace("jobs_dir or", "") and ".write_text" in lcs)
chk("C12 production modules do not import learning_cycle / learning_loop", all(("learning_cycle" not in src(f) and "learning_loop" not in src(f)) for f in ("api_server.py", "video_generation.py", "listing_scraper.py", "vision_analysis.py", "scene_risk.py")))
print("FAILS", F); sys.exit(1 if F else 0)
