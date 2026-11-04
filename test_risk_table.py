"""test_risk_table.py - offline checks of risk_table (no network, no spend)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import risk_table as rt
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}"))
    fails += 0 if c else 1
check("R1 plan type", rt.plan_type("static -> centre") == "static" and rt.plan_type("forward -> table") == "forward" and rt.plan_type(None) == "other")
check("R2 label wins over detector", rt.flag_of("bad", False) and not rt.flag_of("ok", True) and rt.flag_of("part", True) and not rt.flag_of(None, False))
rows = [{"case": "a:1", "variant": "C0", "flag": True, "cat": "kitchen", "ptype": "forward"}, {"case": "a:1", "variant": "C1", "flag": True, "cat": "kitchen", "ptype": "forward"},
        {"case": "a:1", "variant": "C1", "flag": False, "cat": "kitchen", "ptype": "forward"}, {"case": "b:0", "variant": "C0", "flag": False, "cat": "living", "ptype": "static"}]
a = rt.aggregate(rows)
check("R3 aggregate counts clips, flags and distinct configurations", a["a:1"]["n"] == 3 and a["a:1"]["flagged"] == 2 and a["a:1"]["variants"] == {"C0", "C1"} and a["b:0"]["flagged"] == 0, a)
g = rt.group_rate(rows, "cat")
check("R4 group rate per category", g["kitchen"] == (3, 2, 0.67) and g["living"] == (1, 0, 0.0), g)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
