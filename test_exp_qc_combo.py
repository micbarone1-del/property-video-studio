"""test_exp_qc_combo.py - offline checks of exp_qc_combo (no files, no spend)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_qc_combo as q
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
motion = [{"run": "r", "code": "a", "cls": "bad", "accel_last_over_first": 1, "drift_y_std_px_s": 1},
          {"run": "r", "code": "b", "cls": "bad", "accel_last_over_first": 20, "drift_y_std_px_s": 1},
          {"run": "r", "code": "c", "cls": "ok", "accel_last_over_first": 1, "drift_y_std_px_s": 1},
          {"run": "r", "code": "d", "cls": "bad", "accel_last_over_first": 1, "drift_y_std_px_s": 1},
          {"run": "r", "code": "x", "cls": "ok"}]
rot = [{"run": "r", "code": c, "new_frac": v} for c, v in (("a", 0.5), ("b", 0.0), ("c", 0.12), ("d", 0.0), ("x", 0.0))]
judge = {"r": {"a": "pass", "b": "pass", "c": "pass", "d": "pass"}}
rows = q.merge(motion, rot, judge)
check("Q1 only clips with all three sources are kept (x has no judge)", [r["code"] for r in rows] == ["a", "b", "c", "d"])
R = q.rules(0.3)
e = q.evaluate(rows, [R["judge"], R["extremes"], R["new_frac>=0.3"]])
check("Q2 a (rotation) caught by new_frac, b by extremes, d missed, c not flagged at 0.3", e["caught"] == 2 and e["flagged"] == 0 and e["missed"] == ["r/d"])
R = q.rules(0.1)
e = q.evaluate(rows, [R["judge"], R["extremes"], R["new_frac>=0.1"]])
check("Q3 a lower threshold flags the ok clip c", e["flagged"] == 1)
check("Q4 judge alone catches nothing here", q.evaluate(rows, [q.rules(0.3)["judge"]])["caught"] == 0)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
