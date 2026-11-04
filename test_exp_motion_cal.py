"""test_exp_motion_cal.py - offline checks of exp_motion_cal (no network, no spend)."""
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_motion_cal as mc
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}"))
    fails += 0 if c else 1
lab = mc.load_labels(Path(__file__).resolve().parent / "motion_labels.json")
runs = {r for r, c, k in lab}
check("M1 labels: three runs, three classes, codes are 3 letters", runs == {"1104_144423", "1104_175835", "1104_190922"} and {k for r, c, k in lab} == {"bad", "part", "ok"} and all(len(c) == 3 for r, c, k in lab))
check("M2 labelled bad clips of round 4 are there", ("1104_190922", "ley", "bad") in lab and ("1104_190922", "uvp", "ok") in lab)
t = mc.best_threshold([5, 6, 9], [1, 2, 3, 4, 7])
check("M3 best threshold separates as well as it can", t == (5, 1.0, 0.2), t)
check("M4 a perfect separation gives caught 1 and flagged 0", mc.best_threshold([10, 11], [1, 2]) == (10, 1.0, 0.0))
check("M5 an empty class gives None", mc.best_threshold([], [1]) is None and mc.best_threshold([1], []) is None)
rows = [{"cls": "bad", "judge": "pass", "drift_x_std_px_s": 9.0, "rel_e": 1.0}, {"cls": "bad", "judge": "fail"}, {"cls": "ok", "judge": "pass", "drift_x_std_px_s": 1.0, "rel_e": 0.9},
        {"cls": "ok", "judge": "review"}, {"cls": "bad", "judge": None, "drift_x_std_px_s": 9.0}]
ev = mc.evaluate(rows, [("judge",), ("judge", "motion_broad")])
check("M6 the ensemble catches what the judge misses; rows without a judge verdict are left out", ev["judge"] == {"bad": 2, "caught": 1, "ok": 2, "flagged": 1} and ev["judge+motion_broad"] == {"bad": 2, "caught": 2, "ok": 2, "flagged": 1}, ev)
import tempfile
mc.OUT = Path(tempfile.mkdtemp())
(mc.OUT / "judge_run_r.json").write_text('[{"code": "abc", "verdict": "fail"}]')
check("M7 judge answers are read from the saved files, missing run gives {}", mc.judge_by_code("r") == {"abc": "fail"} and mc.judge_by_code("zzz") == {})
check("M8 flagged = judge review/fail or motion extremes", mc.is_flagged("fail", {}) and mc.is_flagged("pass", {"accel_last_over_first": 12}) and not mc.is_flagged("pass", {"accel_last_over_first": 3, "drift_y_std_px_s": 1}))
w, why = mc.pick_winner({"C0": 0.25, "C1": 0.30, "C2": 0.20, "C3": 0.40})
check("M9 tie rule: within 8 points of the best the configuration closest to Luma wins (C2 here, not C0)", w == "C2", (w, why))
w, _ = mc.pick_winner({"C0": 0.10, "C1": 0.30, "C2": 0.30, "C3": 0.40})
check("M10 a clear winner is kept even if it is the least Luma-like", w == "C0")
w, _ = mc.pick_winner({"C0": 0.20, "C3": 0.25})
check("M11 C3 is within the margin of C0 and closer to Luma, so C3 wins", w == "C3")
rk = mc.rank_worst([{"flag": True, "judge": "review", "code": "a"}, {"flag": True, "judge": "fail", "code": "b"}, {"flag": False, "judge": "pass", "code": "c"}, {"flag": True, "judge": "pass", "code": "d", "accel_last_over_first": 20}])
check("M12 worst first: fail, then review, then extremes only; unflagged left out", [r["code"] for r in rk] == ["b", "a", "d"], [r["code"] for r in rk])
sys.exit(1 if fails else 0)
