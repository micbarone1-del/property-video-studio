"""gial_drafts.py -- creates GIAL DRAFT jobs from listing URLs ONE AFTER THE OTHER on the production app and waits for each draft (2026-11-05, 5-video automation test).

  python3 gial_drafts.py LIST.txt [--agency ag_abea5414]     LIST.txt lines: URL | label   (the format of gial_test_candidates.txt; '#' lines ignored)

For every URL: POST /jobs/from-url (the same endpoint the app's "from URL" button calls, with the app's own access key read from .env and never printed), then it polls the job
every 15 s until the ticket becomes 'draft' (ready to start) or fails. It starts NOTHING: no Luma money is spent here (only a few cents of Claude for the narration/photo checks).
A listing the intake refuses is reported with its reason and leaves no job behind. Prints the job ids as a comma list for gial_start.py.
"""
import os
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.environ.get("PVS_BASE", "http://127.0.0.1:8000")
AGENCY = "ag_abea5414"
POLL_SECS = 15
MAX_WAIT_SECS = 20 * 60
READY = ("draft",)
BUSY = ("preparing",)


def session():
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    s = requests.Session()
    key = os.getenv("UI_ACCESS_KEY", "").strip()
    if key:
        s.headers["X-Access-Key"] = key
    return s


def _say(*a):
    print(*a, flush=True)


def read_list(path) -> list:
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        url, _, label = ln.partition("|")
        out.append((url.strip(), label.strip()))
    return out


def run(items, agency=AGENCY, s=None, sleep=time.sleep, out=_say, poll=POLL_SECS, max_wait=MAX_WAIT_SECS, again=False) -> dict:
    """Returns {url: job_id or 'refused:<why>'}. Never starts a generation."""
    s = s or session()
    res = {}
    import listing_registry as _lr
    for url, label in items:
        why = None if again else _lr.create_skip_reason(url)
        if why:
            out(f"{label or url}: {why}"); res[url] = "skipped:duplicate"; continue
        r = s.post(f"{BASE}/jobs/from-url", data={"url": url, "agency_id": agency, "property_name": "", "model_tier": "luma"}, timeout=60)
        if r.status_code != 200:
            out(f"{label or url}: request refused ({r.status_code}) {r.text[:160]}: stopped")
            res[url] = f"refused:{r.status_code}"
            break
        jid = r.json().get("job_id")
        out(f"{label or url}: ticket {jid}")
        waited = 0
        while True:
            sleep(poll); waited += poll
            try:
                j = s.get(f"{BASE}/jobs/{jid}", timeout=30).json()
            except Exception as e:
                out(f"{jid}: read failed ({e}), will retry"); j = {"status": "preparing"}
            st = j.get("status")
            if st in READY:
                out(f"{jid}: DRAFT ready ({j.get('property_name') or '?'})"); res[url] = jid; break
            if st not in BUSY or waited >= max_wait:
                why = (j.get("reason") or {}).get("code") if isinstance(j.get("reason"), dict) else j.get("message")
                out(f"{label or url}: not ready ({st}) {str(why)[:140]}"); res[url] = f"refused:{st}"; break
    ok = [v for v in res.values() if not str(v).startswith(("refused", "skipped"))]
    out("RESULT:", res)
    out("JOB IDS for gial_start.py:", ",".join(ok))
    return res


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ag = sys.argv[sys.argv.index("--agency") + 1] if "--agency" in sys.argv else AGENCY
    run(read_list(sys.argv[1]), agency=ag, again="--again" in sys.argv)
