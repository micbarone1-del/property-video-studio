"""test_learning_loop.py - the learning loop's method (offline). L1-L12. Synthetic data with a PLANTED signal and a PLANTED false pattern."""
import json, os, random, sys, tempfile
from pathlib import Path
import learning_loop as ll

fails = 0
def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    if not ok: fails += 1

def make_rows(n_jobs, signal, seed):
    """3 scenes per job. bad rate 60% for (cat=living, anchor_kind=generic) when `signal`, else 20% everywhere."""
    rnd = random.Random(seed); rows = []
    for j in range(n_jobs):
        jid = f"job{seed}_{j:04d}"
        for s in range(3):
            cat = rnd.choice(["living", "kitchen", "bedroom", "bathroom"]); ak = rnd.choice(["generic", "specific"]); mv = rnd.choice(["push", "rotate"])
            p = 0.6 if (signal and cat == "living" and ak == "generic") else 0.2
            rows.append({"job": jid, "scene": f"scene_{s:03d}", "split": ll.split_of(jid), "cat": cat, "move": mv, "tier": "t", "plan_kind": "forward",
                         "anchor_kind": ak, "depth": "?", "reflective": "none", "l_qc": rnd.random() < p, "l_persistent": None, "l_detector": None})
    return rows

# L1 the split is by JOB and deterministic
rows = make_rows(200, True, 1)
by_job = {}
for r in rows: by_job.setdefault(r["job"], set()).add(r["split"])
check("L1 every scene of one job is in ONE part, and the split is deterministic", all(len(v) == 1 for v in by_job.values()) and ll.split_of("abc") == ll.split_of("abc"))
share = sum(1 for r in rows if r["split"] == "holdout") / len(rows)
check("L1b about 30% of the jobs are kept aside", 0.2 < share < 0.4)

# L2 a planted signal is FOUND on train and HOLDS on the hold-out
big = make_rows(900, True, 2)
res = ll.analyse(big, ("l_qc",), ll.FEATURES)["labels"]["l_qc"]
holding = [r for r in res["holding"] if ["cat", "living"] in r["cond"] and ["anchor_kind", "generic"] in r["cond"]]
check("L2 the planted rule (living + generic anchor) is found and holds on the hold-out", len(holding) >= 1)

# L3 no signal: nothing should hold (fixed seeds, several runs)
holds_noise = 0
for sd in range(10, 16):
    r = ll.analyse(make_rows(500, False, sd), ("l_qc",), ll.FEATURES)["labels"]["l_qc"]
    holds_noise += len(r["holding"])
check("L3 with NO real pattern the hold-out keeps (almost) nothing: false rules over 6 runs <= 1", holds_noise <= 1)

# L4 an explicit false pattern: strong on train, absent on hold-out -> DOES NOT HOLD
rules = [{"cond": [["cat", "kitchen"]], "n": 10, "bad": 8, "rate": 0.8, "lift": 3.0, "wilson_low": 0.5}]
hold = [{"job": f"h{i}", "split": "holdout", "cat": "kitchen", "l_qc": i < 2} for i in range(10)] + [{"job": f"o{i}", "split": "holdout", "cat": "bath", "l_qc": i < 6} for i in range(30)]
c = ll.check_holdout(rules, hold, "l_qc")["rules"][0]
check("L4 a rule strong on train but not on the hold-out is marked DOES NOT HOLD", c["status"] == "DOES NOT HOLD")

# L5 too little data -> an honest answer, no rule
few = make_rows(5, True, 3)
r5 = ll.analyse(few, ("l_qc",), ll.FEATURES)["labels"]["l_qc"]
check("L5 with too little data there is no rule and a note", r5["found"] == 0)

# L6 hold-out smaller than MIN_HOLD_N -> 'not enough hold-out data', never HOLDS
tiny_hold = [{"job": f"h{i}", "split": "holdout", "cat": "kitchen", "l_qc": True} for i in range(4)]
check("L6 fewer hold-out scenes than the minimum cannot HOLD", ll.check_holdout(rules, tiny_hold, "l_qc")["rules"][0]["status"] == "not enough hold-out data")

# L7 the join: risk events + shadow events + job scene fields; labels kept separate
risk = [{"job": "j1", "scene": "scene_000", "cat": "living", "move": "walk_in_explore", "tier": "luma", "stage": "first", "verdict": "flag"},
        {"job": "j1", "scene": "scene_000", "cat": "living", "move": "walk_in_explore", "tier": "luma", "stage": "rework", "verdict": "pass"},
        {"job": "j1", "scene": "scene_001", "cat": "kitchen", "move": "subtle_rotate", "tier": "luma", "stage": "first", "verdict": "pass"},
        {"job": "j1", "scene": "scene_002", "cat": "bedroom", "move": "walk_in_explore", "tier": "luma", "stage": "first", "verdict": "reject"},
        {"job": "j1", "scene": "scene_002", "cat": "bedroom", "move": "walk_in_explore", "tier": "luma", "stage": "rework", "verdict": "reject"}]
shadow = [{"job": "j1", "scene": "scene_000", "new_max": 0.12, "revealed_no": 2, "extended_scene": False},
          {"job": "j1", "scene": "scene_001", "new_max": 0.01, "revealed_no": 0, "extended_scene": False}]
jobs = {"j1": {"scenes_config": [{"anchor": "the window", "depth": "deep"}, {"anchor": "the centre of the frame"}, {"anchor": ""}]}}
rows = {r["scene"]: r for r in ll.build_scene_rows(risk, shadow, jobs)}
check("L7 join: QC non-pass, resolved after rework, detector true; anchor specific", rows["scene_000"]["l_qc"] is True and rows["scene_000"]["l_persistent"] is False and rows["scene_000"]["l_detector"] is True and rows["scene_000"]["anchor_kind"] == "specific")
check("L7b join: a passing scene with a generic anchor, never reworked, detector false", rows["scene_001"]["l_qc"] is False and rows["scene_001"]["l_persistent"] is None and rows["scene_001"]["l_detector"] is False and rows["scene_001"]["anchor_kind"] == "generic" and rows["scene_001"]["plan_kind"] == "static")
check("L7c join: persistent after rework, no shadow event -> detector None (not guessed)", rows["scene_002"]["l_persistent"] is True and rows["scene_002"]["l_detector"] is None and rows["scene_002"]["anchor_kind"] == "none")

# L8 bad input never raises
check("L8 broken lines, missing files and empty jobs do not raise", ll.report([{"x": 1}, {"job": None}], [{}], {"a": None or {}}) is not None and ll.load_jsonl("/nonexistent") == [] and ll.load_jobs("/nonexistent") == {})

# L9 narration rows: fallback and the honest 'reasons not stored' note
nj = {f"n{i}": {"narration_mode": "anchored" if i % 3 else "per_scene", "script_attempts": 1 if i % 3 else 6, "source_description": "x" * (100 if i % 2 else 2000), "scenes_config": [{}] * 6, "source": "relinx"} for i in range(60)}
rep = ll.report([], [], nj)
check("L9 narration: rows built, fallback labelled, missing reasons reported (not invented)", rep["narration"]["rows"] == 60 and "not stored" in rep["narration"]["missing_data"])

# L10 read-only: main writes ONLY learning_report.json, nothing under jobs/
d = tempfile.mkdtemp(); jd = Path(d) / "jobs"; (jd / "j1").mkdir(parents=True)
(jd / "j1" / "job_meta.json").write_text(json.dumps(jobs["j1"]))
before = sorted(str(p) for p in Path(d).rglob("*"))
os.environ["PVS_DATA_DIR"] = d
ll.main([str(jd)])
after = sorted(str(p) for p in Path(d).rglob("*"))
check("L10 running it creates only learning_report.json; the jobs folder is untouched", [a for a in after if a not in before] == [str(Path(d) / "learning_report.json")])

# L11 not imported by the production code
src = "".join((Path(__file__).parent / f).read_text(encoding="utf-8", errors="ignore") for f in ("api_server.py", "video_generation.py", "listing_scraper.py", "vision_analysis.py"))
check("L11 no production module imports learning_loop (phase 1 cannot change a job)", "learning_loop" not in src)

# L12 scratch folders are skipped
(jd / "_test_scratch").mkdir(); (jd / "_test_scratch" / "job_meta.json").write_text("{}")
check("L12 jobs/_test_scratch is not read as a job", "_test_scratch" not in ll.load_jobs(jd))
print("test_learning_loop FAILS", fails)
sys.exit(1 if fails else 0)
