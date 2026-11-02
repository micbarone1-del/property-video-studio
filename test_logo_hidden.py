"""Agency logo_hidden (2026-11-02). Temp data folder. Run: python3 test_logo_hidden.py"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PVS_DATA_DIR"] = tempfile.mkdtemp()
import cost_model as cm
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); fails += 0 if c else 1
a = cm.create_agency("GIAL TEST") if hasattr(cm, "create_agency") else None
aid = a["agency_id"]
cm.set_agency_logo(aid, "/x/logo.png")
check("LH1 a new agency is not hidden", not cm.get_agency(aid).get("logo_hidden"))
r = cm.set_agency_logo_hidden(aid, True)
check("LH2 hiding sets the flag and keeps the logo path (reversible)", r["logo_hidden"] is True and r["logo_path"] == "/x/logo.png")
check("LH3 restoring clears it", cm.set_agency_logo_hidden(aid, False)["logo_hidden"] is False)
src = Path("api_server.py").read_text()
i = src.index("_logo_path = None")
check("LH4 the ONE assembly honours the flag", 'not _agency.get("logo_hidden")' in src[i:i + 900] and src.count("_logo_path = _agency[") == 1)
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
