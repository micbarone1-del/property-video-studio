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
sys.exit(1 if fails else 0)
