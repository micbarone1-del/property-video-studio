"""prod_post_payload.py - posts ONE partner request (a saved JSON payload) to PRODUCTION as our own test partner, like Relinx would (2026-11-17).

Usage (venv active, in the repo folder, inside screen: it must stay alive to receive the webhooks):   python3 prod_post_payload.py /tmp/marino_site_payload.json
Safety: uses the partner "TEST prod-dryrun" (key in /root/pvs_prod_dryrun_key.txt, same as prod_dryrun.py); fresh external_ref (T-...);
callback goes to 127.0.0.1 only (no real partner is ever called); release mode stays manual (nothing is delivered); nothing is deleted anywhere.
The production auto-start then generates the video (about 8 EUR for 6 clips)."""
import os, sys, json, time, uuid, threading, http.server
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("PVS_POST_BASE", "http://127.0.0.1:8000")
KEYFILE = Path("/root/pvs_prod_dryrun_key.txt")


def now():
    return time.strftime("%H:%M:%S", time.gmtime())


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    import requests
    key = os.environ.get("PVS_POST_KEY", "").strip()
    if not key:
        import partner_api
        if not str(partner_api.PARTNERS_FILE).startswith("/var/www/property-video-studio"):
            print("ABORT: the partner file is not in the production data folder:", partner_api.PARTNERS_FILE); return 2
        key = KEYFILE.read_text().strip() if KEYFILE.exists() else ""
        if not partner_api.verify_partner_key(key):
            key = partner_api.create_partner("TEST prod-dryrun")["api_key"]
            KEYFILE.write_text(key)
    hz = requests.get(BASE + "/health", timeout=5).json()
    if hz.get("fake_providers") is not False:
        print("ABORT: the target reports fake providers"); return 2
    hooks = []

    class Local(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                hooks.append(json.loads(raw))
            except Exception:
                hooks.append({"raw": True})
            print("  [%s] WEBHOOK received: %s" % (now(), json.dumps(hooks[-1], ensure_ascii=False)[:300]), flush=True)
            self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p = json.loads(Path(argv[1]).read_text())
    for k in ("external_ref", "agency_name", "description", "photos"):
        if not p.get(k):
            print("ABORT: the payload lacks", k); return 2
    p["external_ref"] = "T-%s-%s" % (str(p["external_ref"])[:30], uuid.uuid4().hex[:6])
    p["callback_url"] = "http://127.0.0.1:%d/hook" % srv.server_port
    auth = {"Authorization": "Bearer " + key}
    r = requests.post(BASE + "/v1/videos", headers=auth, json=p, timeout=90)
    print("POST -> HTTP", r.status_code, r.text[:200], flush=True)
    if r.status_code != 200:
        return 1
    jid = r.json()["id"]
    print("job id:", jid, "| external_ref:", p["external_ref"], flush=True)
    last, t0 = None, time.time()
    while time.time() - t0 < 3000:
        try:
            g = requests.get(BASE + "/v1/videos/" + jid, headers=auth, timeout=30).json()
        except Exception:
            time.sleep(10); continue
        cur = (g.get("status"), str(g.get("message") or g.get("progress") or "")[:80])
        if cur != last:
            print("[%s] %s" % (now(), cur), flush=True); last = cur
        if g.get("status") in ("completed", "failed", "in_review"):
            break
        time.sleep(15)
    time.sleep(3)
    print("FINAL status=%s | webhooks received: %d | job %s" % (last and last[0], len(hooks), jid), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
