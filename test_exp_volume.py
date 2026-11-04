"""test_exp_volume.py - pure parts of exp_volume.py (no API, no server, no spend)."""
import os, sys, tempfile, types
tmp = tempfile.mkdtemp()
os.environ["PVS_JOBS_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_volume as ev
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
check("V1 listing number from a relinx url", ev.listing_number("https://relinx.it/it/immobili/albano-laziale-centro/appartamento-vendita-65-mq-3-locali-1286/") == "1286")
check("V2 spend counts every started clip and starts at 0", ev.spent() == 0.0)
ev.add_spend(0.06, "t"); ev.add_spend(0.06, "t")
check("V3 spend adds up", abs(ev.spent() - 0.12) < 1e-9)
class R:
    def __init__(s, c, j=None): s.status_code, s._j, s.text = c, j or {}, ""
    def json(s): return s._j
class S:
    def __init__(s, seq): s.seq, s.n = seq, 0
    def post(s, *a, **k): s.n += 1; return s.seq.pop(0)
ev.RATE_WAIT_SECS = 0
s = S([R(429), R(200, {"job_id": "abc"})])
check("V4 429 waits and retries, then returns the job id", ev.create_draft(s, "x", "u", "ag") == ("abc", "created") and s.n == 2)
s = S([R(500)])
jid, why = ev.create_draft(s, "x", "u", "ag")
check("V5 a refusal is reported, not retried", jid is None and "500" in why and s.n == 1)
class G:
    def __init__(s, seq): s.seq = seq
    def get(s, *a, **k): return R(200, s.seq.pop(0))
ev.time.sleep = lambda *_: None
check("V6 wait_draft returns ok at 'draft'", ev.wait_draft(G([{"status": "preparing"}, {"status": "draft"}]), "x", "j")[0] is True)
ok, st, msg = ev.wait_draft(G([{"status": "rejected", "message": "listing out of scope"}]), "x", "j")
check("V7 a rejected listing is reported with the app's reason", (not ok) and st == "rejected" and "scope" in msg)
sys.exit(1 if fails else 0)
