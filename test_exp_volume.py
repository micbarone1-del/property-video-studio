"""test_exp_volume.py - pure parts of exp_volume.py (no API, no server, no spend)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["PVS_JOBS_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_volume as ev
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
log = """=== a  https://x
  job 1a2b3c4d partner status in_review after 40s, webhooks for it: 1
=== b
  job deadbeef partner status failed after 12s, webhooks for it: 0
  job 0f0f0f0f partner status in_review after 99s, webhooks for it: 2
"""
check("V1 only drafts that reached in_review are taken from the pilot log", ev.parse_job_ids(log) == ["1a2b3c4d", "0f0f0f0f"])
check("V2 spend counts every started clip and starts at 0", ev.spent() == 0.0)
ev.add_spend(0.06, "t"); ev.add_spend(0.06, "t")
check("V3 spend adds up", abs(ev.spent() - 0.12) < 1e-9)
check("V4 a missing job gives its id as label, a real one its name", ev.listing_label("nojob") == "nojob")
import json, pathlib
d = pathlib.Path(tmp) / "abc12345"; d.mkdir()
(d / "job_meta.json").write_text(json.dumps({"property_name": "appartamento 65mq Albano"}))
check("V5 label from the job's property name", ev.listing_label("abc12345") == "appartamento 65mq Albano")
check("V6 default scratch is inside the jobs dir and the cap default is 6", str(ev.SCRATCH).startswith(tmp) and ev.DEFAULT_CAP == 6.0)
sys.exit(1 if fails else 0)
