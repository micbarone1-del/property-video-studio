"""test_photo_sheet.py - pure parts of photo_sheet.py (no network)."""
import json, os, sys, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp()); os.environ["PVS_TEST_JOBS"] = str(tmp)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photo_sheet as ps
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n); fails += 0 if c else 1
check("S1 photo number from an audit url", ps.index_of("http://127.0.0.1:37697/1201/020.jpg?u=32f283") == 20 and ps.index_of("x") is None)
(tmp / "j").mkdir()
(tmp / "j" / "job_meta.json").write_text(json.dumps({"selection_report": {
    "selected": {"living": [{"url": "http://h/1/003.jpg?u=1"}]},
    "photo_audit": [{"url": "http://h/1/003.jpg?u=1", "category": "living", "excluded": None},
                    {"url": "http://h/1/004.jpg?u=2", "category": "living", "excluded": None},
                    {"url": "http://h/1/005.jpg?u=3", "category": "bathrooms", "excluded": "scarsa qualità"}]}}))
v = ps.verdicts("j")
check("S2 verdicts: used, ok-not-chosen, excluded with reason", v[3].endswith("USATA") and "non scelta" in v[4] and "scarsa" in v[5])
sys.exit(1 if fails else 0)
