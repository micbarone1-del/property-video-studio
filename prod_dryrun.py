"""prod_dryrun.py - full dry run of the automatic workflow ON PRODUCTION (2026-11-13), playing Relinx with our own test partner.

Usage (venv active, in the repo folder):   python3 prod_dryrun.py <relinx.it listing URL>
Run it inside screen (it must stay alive for the whole run: it serves the photos and receives the webhooks on 127.0.0.1).

What it does, in order:
  A1  wrong key            -> expect HTTP 401, nothing created
  A2  unsuitable request   -> 1 photo only: expect the job to FAIL at intake with failure_code + failure_message (no video, no cost)
  B   the real listing     -> POST /v1/videos exactly like Relinx; prints every status change; the auto start, QC, rework and alternative photo
                              are the production ones. The job stops at "done" (release mode = manual). Then it waits 10 minutes for you
                              to press release on the dashboard and prints the webhook received.
Safety: own partner "TEST prod-dryrun" and own agency "PVS DRYRUN" (never GIAL / Relinx), callback goes to 127.0.0.1 only, nothing is
deleted anywhere, the partner key is kept in /root/pvs_prod_dryrun_key.txt (outside the repo). Cost of B: about 9-12 EUR.
"""
import os, sys, io, json, time, uuid, threading, http.server, tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8000"
AGENCY_NAME = os.environ.get("DRYRUN_AGENCY_NAME", "PVS DRYRUN")        # 2026-11-13: the voice reads this name aloud: use a real one (GIAL IMMOBILIARE)
AGENCY_EXT = os.environ.get("DRYRUN_AGENCY_EXT", "pvs-dryrun")          # own external id = own agency record (same id would RENAME the existing one)
SKIP_A = os.environ.get("DRYRUN_SKIP_A") == "1"
KEYFILE = Path("/root/pvs_prod_dryrun_key.txt")
JOBS = Path("/var/www/property-video-studio/jobs")


def now():
    return time.strftime("%H:%M:%S", time.gmtime())


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    import requests
    import partner_api
    import relinx_pilot_check as rp
    import listing_scraper
    from PIL import Image
    if not str(partner_api.PARTNERS_FILE).startswith("/var/www/property-video-studio"):
        print("ABORT: the partner file is not in the production data folder:", partner_api.PARTNERS_FILE)
        return 2
    hz = requests.get(BASE + "/health", timeout=5).json()
    if hz.get("fake_providers") is not False:
        print("ABORT: production reports fake providers")
        return 2
    key = KEYFILE.read_text().strip() if KEYFILE.exists() else ""
    if not partner_api.verify_partner_key(key):
        key = partner_api.create_partner("TEST prod-dryrun")["api_key"]
        KEYFILE.write_text(key)
    auth = {"Authorization": "Bearer " + key}

    tmp = Path(tempfile.mkdtemp(prefix="prod_dryrun_"))
    hooks = []

    class Local(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp), **k)

        def log_message(self, *a):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                hooks.append(json.loads(raw))
            except Exception:
                hooks.append({"raw": True})
            print("  [%s] WEBHOOK received: %s" % (now(), json.dumps(hooks[-1], ensure_ascii=False)[:300]), flush=True)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
    local = "http://127.0.0.1:" + str(srv.server_port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hook = local + "/hook"

    if not SKIP_A:
        # ---- A1 wrong key
        r = requests.post(BASE + "/v1/videos", headers={"Authorization": "Bearer wrong-key"}, json={}, timeout=30)
        print("A1 wrong key -> HTTP %s (expected 401): %s" % (r.status_code, "PASS" if r.status_code == 401 else "FAIL"), flush=True)

        # ---- A2 unsuitable request: one photo only
        Image.new("RGB", (800, 600), (120, 120, 120)).save(tmp / "one.jpg", quality=90)
        bad = {"external_ref": "T-bad-" + uuid.uuid4().hex[:6], "agency_name": "PVS DRYRUN", "agency_external_id": "pvs-dryrun",
               "property_name": "Prova non idonea", "description": "Appartamento di prova con una sola foto.", "features": [],
               "photos": [{"url": local + "/one.jpg", "order": 0}], "voice_id": "", "callback_url": hook}
        r = requests.post(BASE + "/v1/videos", headers=auth, json=bad, timeout=60)
        print("A2 POST -> HTTP", r.status_code, r.text[:160], flush=True)
        if r.status_code == 200:
            jid = r.json()["id"]
            for _ in range(60):
                g = requests.get(BASE + "/v1/videos/" + jid, headers=auth, timeout=30).json()
                if g.get("status") in ("failed", "in_review", "completed"):
                    break
                time.sleep(3)
            time.sleep(3)
            print("A2 job %s status=%s failure_code=%s failure_message=%s" % (jid, g.get("status"), g.get("failure_code"), g.get("failure_message")), flush=True)
            print("A2 expected: status failed + failure_code + message: %s; webhooks for it: %d" % (
                "PASS" if g.get("status") == "failed" and g.get("failure_code") and g.get("failure_message") else "FAIL",
                len([h for h in hooks if h.get("id") == jid])), flush=True)

    # ---- B the real listing
    url = argv[1]
    page = requests.get(url, headers=rp.UA, timeout=40).text
    L = rp.parse_listing(page, url)
    d = tmp / L["id"]
    d.mkdir(exist_ok=True)
    imgs = [Image.open(io.BytesIO(requests.get("https://relinx.it" + rel, headers=rp.UA, timeout=60).content)).convert("RGB") for rel in L["photos"]]
    kept, binfo = rp.choose_clean_photos(imgs, listing_scraper.MIN_USABLE_PHOTOS)
    photos = []
    for n_out, (pos, im) in enumerate(kept):
        im.save(d / ("%03d.jpg" % n_out), quality=95)
        photos.append({"url": local + "/" + L["id"] + "/%03d.jpg?u=%s" % (n_out, uuid.uuid4().hex[:6]), "order": n_out})
    print("B listing %s: %d photos kept of %d (%s)" % (L["id"], len(photos), len(imgs), binfo["mode"]), flush=True)
    payload = {"external_ref": "T-%s-%s" % (L["id"], uuid.uuid4().hex[:6]), "agency_name": AGENCY_NAME, "agency_external_id": AGENCY_EXT,
               "property_name": L["name"], "description": L["description"], "features": [], "photos": photos, "voice_id": "",
               "callback_url": hook, "listing_url": url}
    t0 = time.time()
    r = requests.post(BASE + "/v1/videos", headers=auth, json=payload, timeout=60)
    print("B POST -> HTTP", r.status_code, r.text[:160], flush=True)
    if r.status_code != 200:
        return 1
    jid = r.json()["id"]
    print("B job id:", jid, flush=True)
    last = None
    while time.time() - t0 < 3600:
        try:
            g = requests.get(BASE + "/v1/videos/" + jid, headers=auth, timeout=30).json()
            m = json.loads((JOBS / jid / "job_meta.json").read_text())
        except Exception as e:
            time.sleep(10)
            continue
        cur = (g.get("status"), m.get("status"), str(m.get("message"))[:70])
        if cur != last:
            print("  [%s +%dmin] partner=%s internal=%s | %s | reworks=%s alt=%s" % (now(), (time.time() - t0) / 60, cur[0], cur[1], cur[2],
                  m.get("rework_counts"), list((m.get("alt_photo") or {}).keys())), flush=True)
            last = cur
        if m.get("status") in ("done", "failed"):
            break
        time.sleep(20)
    m = json.loads((JOBS / jid / "job_meta.json").read_text())
    print("B END internal=%s partner=%s released=%s" % (m.get("status"), g.get("status"), m.get("released")), flush=True)
    print("   cost: claude=%s total=%s | rework_rounds=%s auto_reworked=%s" % (
        (m.get("claude_usage") or {}).get("cost_eur"), m.get("total_cost_eur") or m.get("cost_eur"), m.get("rework_rounds"), m.get("auto_reworked")), flush=True)
    print("   qc:", [(q.get("scene"), q.get("verdict")) for q in m.get("qc_results", [])], flush=True)
    print("   webhooks so far: %d (expected 0 before the release: manual mode)" % len([h for h in hooks if h.get("id") == jid]), flush=True)
    if m.get("status") == "done":
        print(">>> READY. Release it on the dashboard now (operator-page, job %s). Waiting 10 minutes for the webhook." % jid, flush=True)
        t1 = time.time()
        while time.time() - t1 < 600 and not [h for h in hooks if h.get("id") == jid]:
            time.sleep(5)
        print("B webhook after release: %s" % ("PASS received" if [h for h in hooks if h.get("id") == jid] else "NOT received in 10 minutes"), flush=True)
    print("DRYRUN FINISHED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
