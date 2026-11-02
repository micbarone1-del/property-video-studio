"""gial_start.py -- starts the generation of GIAL draft jobs ONE AFTER THE OTHER on the production app and waits for each to park (2026-11-02, Michele:
"falli tutti e 3 i video se il set up ha successo. Io approvo solo i rework").

  python3 gial_start.py JOB1,JOB2,JOB3        (production, venv active, from /var/www/property-video-studio; run it inside `screen` so it survives the terminal)

For every job: it must be in status 'draft' (otherwise it is skipped, never started twice); POST /jobs/<id>/start-generation with the app's own access key (read
from .env, never printed); then it polls the job every 60 s until the job leaves queued/running. 'done' and 'awaiting_approval' (the QC gate: only Michele approves
reworks) both let the NEXT job start. 'failed' / 'stopped' / any other state STOPS the whole batch: no further money is spent until a person looks.
It never deletes or edits anything: it only calls the same endpoint the app's button calls.
"""
import os
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.environ.get("PVS_BASE", "http://127.0.0.1:8000")
POLL_SECS = 60
MAX_WAIT_SECS = 3 * 3600
PARKED_OK = ("done", "awaiting_approval")
BUSY = ("queued", "running")


def session():
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    s = requests.Session()
    key = os.getenv("UI_ACCESS_KEY", "").strip()
    if key:
        s.headers["X-Access-Key"] = key
    return s


def _say(*a):
    print(*a, flush=True)      # unbuffered: the log read through `tee` shows lines at once


def run(job_ids, s=None, sleep=time.sleep, out=_say, poll=POLL_SECS, max_wait=MAX_WAIT_SECS):
    """Returns a dict job_id -> final status ('skipped:<status>' for jobs that were not drafts, 'not started' after a stop)."""
    s = s or session()
    result = {}
    stop = False
    for jid in job_ids:
        if stop:
            result[jid] = "not started"
            continue
        r = s.get(f"{BASE}/jobs/{jid}", timeout=30)
        if r.status_code != 200:
            out(f"{jid}: cannot read the job ({r.status_code}): batch stopped")
            result[jid] = f"unreadable:{r.status_code}"; stop = True; continue
        st = r.json().get("status")
        if st != "draft":
            out(f"{jid}: status is '{st}', not 'draft': skipped (never started twice)")
            result[jid] = f"skipped:{st}"; continue
        r = s.post(f"{BASE}/jobs/{jid}/start-generation", timeout=60)
        if r.status_code != 200:
            out(f"{jid}: start refused ({r.status_code}) {r.text[:200]}: batch stopped")
            result[jid] = f"refused:{r.status_code}"; stop = True; continue
        out(f"{jid}: generation started")
        waited = 0
        while True:
            sleep(poll); waited += poll
            try:
                j = s.get(f"{BASE}/jobs/{jid}", timeout=30).json()
            except Exception as e:
                out(f"{jid}: status read failed ({e}), will retry"); j = {"status": "running"}
            st = j.get("status")
            out(f"{jid}: {st} {j.get('progress')}% {str(j.get('message') or '')[:90]}")
            if st not in BUSY:
                break
            if waited >= max_wait:
                out(f"{jid}: still {st} after {max_wait // 60} min: batch stopped for a person to look")
                st = f"timeout:{st}"; break
        result[jid] = st
        if st not in PARKED_OK:
            out(f"{jid}: ended as '{st}': batch stopped, no more spending")
            stop = True
    out("RESULT:", result)
    return result


if __name__ == "__main__":
    ids = [x.strip() for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if x.strip()]
    if not ids:
        raise SystemExit(__doc__)
    run(ids)
