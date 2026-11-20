"""fake_webhook_fail.py - the partner webhook when the partner is NOT reachable, with a server restart in the middle (FAKE instance, port 8001). 2026-11-20.

Run (venv active, repo folder):   python3 -u fake_webhook_fail.py        (about 20 minutes: the retries wait 1, 5 and 15 minutes)

  1. A job that fails at intake (one photo) sends the "failed" webhook to a closed local port: the first attempt is recorded at once.
  2. After the 2nd attempt the script restarts the fake instance itself (./start_fake.sh) - retries live in memory, so a restart must resume them.
  3. Expected: attempt 3 right after the restart (30 s), attempt 4 about 15 minutes later, then status failed and ONE mail to the operator.
Checks: no job state change, no callback URL anywhere in the stored state, nothing more after the last attempt, operator told once (and not before).
Safety: fake instance only (refuses unless /health says fake_providers true); production is never touched; nothing is deleted.
"""
import os, sys, json, time, uuid, subprocess, threading, http.server, tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_failure_paths as ff
from fake_failure_paths import STATE, JOBS, BASE, KEYFILE, check, info, now, outbox

ENV = {"PVS_MIN_ENVIRONMENT_TYPES": "1", "PVS_AUTO_START": "1", "PVS_AUTO_START_CAP_EUR": "100", "PVS_AUTO_START_MAX_ACTIVE": "2",
       "PVS_AUTO_REWORK": "1", "PVS_AUTO_ALT_PHOTO": "1", "PVS_PACE_FIX": "1", "PVS_PACE_MIN": "6", "PVS_PACE_LIMIT": "26", "PVS_ACCEPT_RENDERS": "0",
       "PVS_FACT_MASK_AGENCY": "1", "PVS_NARRATION_MODEL": "claude-sonnet-5-5", "PVS_LUMA_RESOLUTION": "1080p", "PVS_DEFAULT_VOICE": "it-IT-Chirp3-HD-Aoede"}
DEAD_URL = "http://127.0.0.1:9/hook"        # nothing listens on port 9: connection refused


def main():
    import requests
    from PIL import Image
    hz = requests.get(BASE + "/health", timeout=5).json()
    if hz.get("fake_providers") is not True:
        print("ABORT: port 8001 is not a fake instance:", hz)
        return 2
    key = KEYFILE.read_text().strip()
    auth = {"Authorization": "Bearer " + key}
    tmp = Path(tempfile.mkdtemp(prefix="fakewh_"))
    Image.new("RGB", (1600, 1200), (130, 150, 170)).save(tmp / "a.jpg", quality=92)

    class Local(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp), **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    name = "Prova WH %s" % uuid.uuid4().hex[:5]
    body = {"external_ref": "F-WH-" + uuid.uuid4().hex[:6], "agency_name": "PVS FAKE FAIL", "agency_external_id": "pvs-fake-fail", "property_name": name,
            "description": "Annuncio di prova con una sola foto per il test del webhook.", "features": [],
            "photos": [{"url": "http://127.0.0.1:%d/a.jpg?u=%s" % (srv.server_port, uuid.uuid4().hex[:6]), "order": 0, "category": "living"}],
            "voice_id": "", "callback_url": DEAD_URL}
    r = requests.post(BASE + "/v1/videos", headers=auth, json=body, timeout=60)
    info("POST -> HTTP %s %s" % (r.status_code, r.text[:100]))
    if r.status_code != 200:
        return 1
    jid = r.json()["id"]
    t0 = time.time()

    def meta():
        return json.loads((JOBS / jid / "job_meta.json").read_text())

    def wd():
        return meta().get("webhook_delivery") or {}

    def mails(word):
        return [o for o in outbox() if o.get("kind") == "email" and name in str(o.get("subject")) and word in str(o.get("subject"))]

    ENV["PVS_AUTO_START_NOT_BEFORE"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())   # old fake drafts must never start after the restart
    last, restarted, t_restart, t_att3, seen1 = None, False, None, None, False
    while time.time() - t0 < 2400:
        try:
            st = wd()
        except Exception:
            time.sleep(3)
            continue
        cur = (st.get("status"), st.get("attempts"))
        if cur != last:
            print("  [%s +%ds] webhook %s attempts=%s last_error=%s next_at=%s" % (now(), time.time() - t0, cur[0], cur[1], st.get("last_error"), st.get("next_at")), flush=True)
            last = cur
        if cur[1] == 1 and not restarted and not seen1:
            seen1 = True
            check("W1 first attempt recorded at once, error is a name (no URL)", st.get("last_error") and "127.0.0.1" not in str(st.get("last_error")), st)
            check("W1b no operator mail yet (not all attempts failed)", not mails("non consegnato"), len(mails("non consegnato")))
        if cur[1] == 2 and not restarted:
            check("W2 two attempts before the restart", True)
            info("restarting the fake instance now (the retries live in memory)")
            subprocess.run(["./start_fake.sh"], cwd=os.path.dirname(os.path.abspath(__file__)), env={**os.environ, **ENV}, capture_output=True, text=True, timeout=120)
            restarted, t_restart = True, time.time()
            info("fake instance restarted, waiting for attempt 3")
        if restarted and cur[1] == 3 and t_att3 is None:
            t_att3 = time.time()
            check("W3 attempt 3 happened after the restart, within 150 s (the retries were resumed)", t_att3 - t_restart < 150, round(t_att3 - t_restart))
        if st.get("status") in ("failed", "delivered"):
            break
        time.sleep(5)
    st = wd()
    check("W4 final status failed after exactly 4 attempts", st.get("status") == "failed" and st.get("attempts") == 4, st)
    time.sleep(20)
    check("W5 operator told exactly once (Webhook non consegnato)", len(mails("non consegnato")) == 1, len(mails("non consegnato")))
    m = meta()
    check("W6 the video's own state is untouched (still failed, message kept)", m.get("status") == "failed" and bool(m.get("failure_message") or m.get("message")), (m.get("status"), m.get("failure_code")))
    check("W7 the callback URL is not in the stored delivery state", "127.0.0.1" not in json.dumps(m.get("webhook_delivery")), "")
    time.sleep(90)
    check("W8 nothing more after the last attempt (still 4, status failed)", wd().get("attempts") == 4 and wd().get("status") == "failed", wd())
    check("W9 partner API still shows failed (it can read the result itself)", requests.get(BASE + "/v1/videos/" + jid, headers=auth, timeout=30).json().get("status") == "failed", "")
    bad = [n for n, ok in ff.RES if not ok]
    print("\nRESULT: %d PASS / %d FAIL%s" % (len(ff.RES) - len(bad), len(bad), (" -> " + ", ".join(bad)) if bad else ""), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
