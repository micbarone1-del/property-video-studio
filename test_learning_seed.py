"""test_learning_seed.py - phase 1b seed (2026-11-25). Run: python3 test_learning_seed.py"""
import json, os, sys, tempfile
from pathlib import Path
import learning_seed as ls, learning_loop as ll
F = 0
def chk(n, ok, info=""):
    global F
    print(("PASS " if ok else "FAIL ") + n + (" " + str(info) if info and not ok else ""))
    F += 0 if ok else 1
T = Path(tempfile.mkdtemp()); (T / "scratch" / "facade").mkdir(parents=True)
key = [{"code": "aaa", "case": "jobA:0", "plan": "forward walk", "ok": True}, {"code": "bbb", "case": "jobA:0", "plan": "forward x", "ok": True},
       {"code": "ccc", "case": "jobA:0", "plan": "static y", "ok": True}, {"code": "ddd", "case": "jobA:1", "plan": "forward", "ok": True},
       {"code": "eee", "case": "jobB:0", "plan": "static", "ok": True}, {"code": "fff", "case": "jobB:0", "plan": "static", "ok": True},
       {"code": "ggg", "case": "jobC:5", "plan": "forward", "ok": True}, {"code": "hhh", "case": "jobC:5", "plan": "forward", "ok": True},
       {"code": "iii", "case": "jobD:0", "plan": "forward", "ok": True}, {"code": "jjj", "case": "jobD:0", "plan": "forward", "ok": True}]
(T / "scratch" / "facade" / "key_run1.json").write_text(json.dumps(key))
labels = {"note": "x", "run1": {"bad": ["aaa", "bbb", "eee", "ggg", "iii"], "part": ["ccc"], "ok": ["ddd", "fff", "hhh", "jjj"]}, "run2": {"bad": ["zzz"], "part": [], "ok": []}}
(T / "labels.json").write_text(json.dumps(labels))
jobs = {"jobA": {"scenes_config": [{"scene_id": "sc_a0", "category": "living", "anchor": "the sofa", "depth": "deep"}, {"scene_id": "sc_a1", "category": "kitchen"}]},
        "jobB": {"scenes_config": [{"scene_id": "sc_b0", "category": "bedroom", "anchor": "the centre of the frame", "depth": "shallow"}]},
        "jobC": {"scenes_config": [{"scene_id": "sc_c0"}]},
        "jobD": {"scenes_config": [{"scene_id": "sc_d0", "category": "bath"}]}}
rows, st = ls.seed_rows(T / "scratch", jobs, T / "labels.json", skip={("jobD", "sc_d0")})
by = {r["scene"]: r for r in rows}
chk("S1 one row per scene, not per clip", set(by) == {"sc_a0", "sc_b0"}, list(by))
chk("S2 'part' left out: jobA scene 0 has 2 labelled clips (bad, bad), bad share 1.0", by["sc_a0"]["l_qc"] is True and by["sc_a0"]["n_clips"] == 2 and st["part_left_out"] == 1, st)
chk("S3 scene with a single labelled clip is skipped (jobA:1)", "sc_a1" not in by)
chk("S4 half bad = bad (jobB: bad+ok)", by["sc_b0"]["l_qc"] is True and by["sc_b0"]["n_clips"] == 2)
chk("S5 move and tier unknown, plan_kind from the clips, src seed", by["sc_a0"]["move"] == "?" and by["sc_a0"]["tier"] == "?" and by["sc_a0"]["plan_kind"] == "forward" and by["sc_b0"]["plan_kind"] == "static" and by["sc_a0"]["src"] == "seed")
chk("S6 cat / anchor_kind / depth come from job_meta", by["sc_a0"]["cat"] == "living" and by["sc_a0"]["anchor_kind"] == "specific" and by["sc_b0"]["anchor_kind"] == "generic" and by["sc_b0"]["depth"] == "shallow")
chk("S7 scene beyond job_meta counted, not used (jobC:5); production scene skipped (jobD)", st["scenes_without_job_meta"] == 1 and st["scenes_already_in_production"] == 1, st)
chk("S8 label without a key file counted as unmapped (run2: 1 clip)", st["clips_unmapped"] == 1 and st["runs"] == 2, st)
chk("S9 split uses the job id like production", by["sc_a0"]["split"] == ll.split_of("jobA"))
chk("S10 broken or missing files give no rows and no error", ls.seed_rows(T / "nope", jobs, T / "nolabels.json")[0] == [])
# main --seed writes nothing
D = T / "data"; D.mkdir(); (T / "jobs").mkdir()
os.environ["PVS_DATA_DIR"] = str(D)
os.environ["PVS_VOLUME_SCRATCH"] = str(T / "scratch")
before = sorted(os.listdir(D)); rc = ll.main([str(T / "jobs"), "--seed"]); after = sorted(os.listdir(D))
chk("S11 run with --seed writes nothing", rc == 0 and before == after, after)
rc = ll.main([str(T / "jobs")]); chk("S12 run without --seed still writes the two files", sorted(os.listdir(D)) == ["learning_report.json", "learning_rules.json"])
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "learning_seed.py")).read()
chk("S13 read-only module, not imported by production", "write_text" not in src and ".write(" not in src and all("learning_seed" not in open(f, encoding="utf-8", errors="ignore").read() for f in ("api_server.py", "scene_risk.py", "learning_apply.py", "listing_scraper.py")))
print("FAILS", F); sys.exit(1 if F else 0)
