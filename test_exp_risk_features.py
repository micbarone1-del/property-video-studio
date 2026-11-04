"""test_exp_risk_features.py - offline checks of exp_risk_features (no network, no spend)."""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_risk_features as rf
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}"))
    fails += 0 if c else 1
c = rf.clean({"view_out_window": True, "sky_visible": "true", "people_or_pets": "false", "dominant_subject": "x" * 100, "camera_height": "eye"})
check("F1 clean: real bools, missing = False, long text cut", c["view_out_window"] is True and c["sky_visible"] is True and c["people_or_pets"] is False and c["mirror_or_glass"] is False and len(c["dominant_subject"]) == 60 and set(rf.FLAGS) <= set(c))
check("F2 the prompt names every flag", all(f in rf.PROMPT for f in rf.FLAGS))
rows = {f"j:{i}": r for i, r in enumerate([0.6, 0.5, 0.5, 0.4, 0.1, 0.0, 0.1, 0.2])}
feats = {k: rf.clean({"view_out_window": i < 4, "sky_visible": i == 0}) for i, k in enumerate(rows)}
cmp = {t[0]: t for t in rf.compare(rows, feats)}
check("F3 window group 4 scenes at 0.5 vs 4 at 0.1, not weak", cmp["view_out_window"] == ("view_out_window", 4, 0.5, 4, 0.1, False), cmp["view_out_window"])
check("F4 a feature on 1 scene is weak", cmp["sky_visible"][5] is True and cmp["sky_visible"][1] == 1)
check("F5 a feature nobody has gives no rate, weak", cmp["mirror_or_glass"][2] is None and cmp["mirror_or_glass"][5] is True)
check("F6 sorted by the gap, the biggest first", rf.compare(rows, feats)[0][0] == "view_out_window")
d = Path(tempfile.mkdtemp()); rf.OUT = d
(d / "key_a.json").write_text(json.dumps([{"case": "j:1", "ok": True}, {"case": "j:1", "ok": True}, {"case": "j:2", "ok": False}, {"case": "k:0", "ok": True}]))
check("F7 scene_cases: unique, only clips that exist", rf.scene_cases() == ["j:1", "k:0"], rf.scene_cases())
print("FAILS:", fails)
sys.exit(1 if fails else 0)
