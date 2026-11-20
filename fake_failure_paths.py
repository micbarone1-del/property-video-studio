"""fake_failure_paths.py - partner failure paths on the FAKE instance (port 8001, zero cost, nothing leaves the machine). 2026-11-20.

Start the fake instance first with the production switches and PVS_MIN_ENVIRONMENT_TYPES=1 (the fake vision calls every photo "living"),
then:   python3 fake_failure_paths.py [T1|T2|T3 ...]     (no argument = T3, T1, T2)

  T3 input_not_suitable   one photo only                                  -> failed at intake, code input_not_suitable
  T1 generation_failed    every Luma call fails (direct 400 + fal fails)  -> failed, code generation_failed, no technical text to the partner
  T2 rejected_by_operator a normal job reaches "done", is held, then POST /jobs/{id}/reject -> failed, code rejected_by_operator
Checks follow the four invariants: job not lost, no double cost, final state correct and visible (API + exactly one webhook), operator told once.
Safety: refuses to run unless /health says fake_providers true; own partner and agency; callback only on 127.0.0.1; deletes nothing.
"""
import os, sys, json, time, uuid, random, threading, http.server, tempfile
from pathlib import Path

STATE = Path("/var/www/pvs_fake_state")
JOBS = Path("/var/www/pvs_fake_jobs")
os.environ["PVS_DATA_DIR"] = str(STATE / "data")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8001"
KEYFILE = STATE / "failure_key.txt"
RES = []
_k = [l.split('=', 1)[1].strip().strip(chr(34) + chr(39) + ' ') for l in open('/var/www/property-video-studio/.env') if l.startswith('UI_ACCESS_KEY=')]
OPH = {'X-Access-Key': _k[0]} if _k else {}


def now():
    return time.strftime("%H:%M:%S")


def check(name, ok, info=""):
    RES.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -- " + str(info)), flush=True)


def info(msg):
    print("INFO " + msg, flush=True)


def outbox():
    p = STATE / "outbox.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def set_faults(d):
    p = STATE / "faults.json"
    p.write_text(json.dumps(d))
    t = time.time() + set_faults.n
    os.utime(p, (t, t))
    set_faults.n += 1


set_faults.n = 1


def main(argv):
    import requests
    from PIL import Image, ImageDraw
    import partner_api
    if not str(partner_api.PARTNERS_FILE).startswith(str(STATE)):
        print("ABORT: partner file is not in the fake data folder:", partner_api.PARTNERS_FILE)
        return 2
    hz = requests.get(BASE + "/health", timeout=5).json()
    if hz.get("fake_providers") is not True:
        print("ABORT: port 8001 is not a fake instance:", hz)
        return 2
    key = KEYFILE.read_text().strip() if KEYFILE.exists() else ""
    if not partner_api.verify_partner_key(key):
        key = partner_api.create_partner("TEST fake-failures")["api_key"]
        KEYFILE.write_text(key)
    auth = {"Authorization": "Bearer " + key}
    tmp = Path(tempfile.mkdtemp(prefix="fakefail_"))
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
            print("  [%s] WEBHOOK: %s" % (now(), json.dumps(hooks[-1], ensure_ascii=False)[:260]), flush=True)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
    local = "http://127.0.0.1:" + str(srv.server_port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def make_photos(tag, n):
        d = tmp / tag
        d.mkdir()
        out = []
        for i in range(n):
            r = random.Random("%s-%d-%s" % (tag, i, uuid.uuid4().hex))
            im = Image.new("RGB", (1600, 1200), tuple(r.randint(90, 220) for _ in range(3)))
            dr = ImageDraw.Draw(im)
            for _ in range(40):
                x, y = r.randint(0, 1400), r.randint(0, 1000)
                dr.rectangle([x, y, x + r.randint(40, 300), y + r.randint(40, 250)], fill=tuple(r.randint(0, 255) for _ in range(3)))
            im.save(d / ("%d.jpg" % i), quality=92)
            out.append({"url": "%s/%s/%d.jpg?u=%s" % (local, tag, i, uuid.uuid4().hex[:6]), "order": i, "category": ("living", "kitchen")[i % 2]})
        return out

    def post_job(tag, n_photos):
        name = "Prova %s %s" % (tag, uuid.uuid4().hex[:5])
        body = {"external_ref": "F-%s-%s" % (tag, uuid.uuid4().hex[:6]), "agency_name": "PVS FAKE FAIL", "agency_external_id": "pvs-fake-fail",
                "property_name": name, "description": "Trilocale luminoso di prova, con cucina abitabile, due camere e balcone. " * 2,
                "features": [], "photos": make_photos(tag, n_photos), "voice_id": "", "callback_url": local + "/hook"}
        r = requests.post(BASE + "/v1/videos", headers=auth, json=body, timeout=60)
        info("%s POST -> HTTP %s %s" % (tag, r.status_code, r.text[:120]))
        return (r.json()["id"], name, body["external_ref"]) if r.status_code == 200 else (None, name, None)

    def wait_final(jid, stop=("done", "failed", "awaiting_approval"), timeout=1500):
        t0, last, draft_since = time.time(), None, time.time()
        while time.time() - t0 < timeout:
            try:
                m = json.loads((JOBS / jid / "job_meta.json").read_text())
            except Exception:
                time.sleep(3)
                continue
            cur = (m.get("status"), str(m.get("message"))[:80])
            if cur != last:
                print("  [%s +%ds] %s | %s" % (now(), time.time() - t0, cur[0], cur[1]), flush=True)
                last = cur
            if m.get("status") != "draft":
                draft_since = time.time()
            elif time.time() - draft_since > 150:
                info("job stays draft for 150 s: the auto start did not start it (is the fake instance started with the production switches?)")
                return m
            if m.get("status") in stop:
                time.sleep(8)
                return json.loads((JOBS / jid / "job_meta.json").read_text())
            time.sleep(4)
        info("timeout waiting for a final state")
        return json.loads((JOBS / jid / "job_meta.json").read_text())

    def partner_view(jid):
        return requests.get(BASE + "/v1/videos/" + jid, headers=auth, timeout=30).json()

    def mails(name, word=""):
        return [o for o in outbox() if o.get("kind") == "email" and name in str(o.get("subject")) and word in str(o.get("subject"))]

    def start_when_draft(jid):
        """The operator pressing Genera Video: the SAME endpoint the auto start calls (the fake Claude text cannot pass the fact check, so the auto start refuses)."""
        for _ in range(60):
            if json.loads((JOBS / jid / "job_meta.json").read_text()).get("status") == "draft":
                break
            time.sleep(2)
        r = requests.post(BASE + "/jobs/%s/start-generation" % jid, headers=OPH, timeout=60)
        info("start-generation -> HTTP %s %s" % (r.status_code, r.text[:100]))

    def common(tag, jid, name, m, code, expect_hooks=1, min_files=2):
        h = [x for x in hooks if x.get("id") == jid]
        g = partner_view(jid)
        check(tag + "a job not lost: job_meta.json present, final status failed", m.get("status") == "failed", m.get("status"))
        check(tag + "b partner API shows failed + code %s + Italian message" % code,
              g.get("status") == "failed" and g.get("failure_code") == code and bool(g.get("failure_message")), g)
        check(tag + "c exactly %d webhook(s) for this job" % expect_hooks, len(h) == expect_hooks, len(h))
        if h:
            check(tag + "d webhook failed + same code + no video_url", h[0].get("status") == "failed" and h[0].get("failure_code") == code and "video_url" not in h[0], h[0])
        check(tag + "e job folder kept with its files", len(list((JOBS / jid).glob("*"))) >= min_files, len(list((JOBS / jid).glob("*"))))
        info("%s cost fields: total=%s claude=%s | operator mails with this name: %d" % (
            tag, m.get("total_cost_eur") or m.get("cost_eur"), (m.get("claude_usage") or {}).get("cost_eur"), len(mails(name))))
        return g, h

    todo = [a.upper() for a in argv[1:]] or ["T3", "T1", "T2"]

    if "T3" in todo:
        print("\n== T3 input_not_suitable (1 photo)", flush=True)
        set_faults({})
        jid, name, _ = post_job("T3", 1)
        if jid:
            m = wait_final(jid, timeout=240)
            common("T3", jid, name, m, "input_not_suitable", min_files=1)

    if "T1" in todo:
        print("\n== T1 generation_failed (every Luma call fails)", flush=True)
        set_faults({"luma_direct": ["http_400"] * 80, "luma_fal": ["failed"] * 80})
        n0 = len([o for o in outbox() if o.get("kind") == "luma_create"])
        jid, name, _ = post_job("T1", 8)
        if jid:
            start_when_draft(jid)
            m = wait_final(jid)
            g, h = common("T1", jid, name, m, "generation_failed")
            msg = str(g.get("failure_message", "")).lower()
            check("T1f partner message has no technical text (http, luma, error, 400)", not any(w in msg for w in ("http", "luma", "error", "400")), msg)
            check("T1g operator told exactly once", len(mails(name, "fallito")) == 1, len(mails(name, "fallito")))
            info("T1 Luma create calls made: %d (a runaway retry loop would show here)" % (len([o for o in outbox() if o.get("kind") == "luma_create"]) - n0))
        set_faults({})

    if "T2" in todo:
        print("\n== T2 rejected_by_operator (normal job, then Rifiuta)", flush=True)
        set_faults({})
        jid, name, _ = post_job("T2", 8)
        if jid:
            start_when_draft(jid)
            m = wait_final(jid)
            info("T2 reached %s" % m.get("status"))
            if m.get("status") in ("done", "awaiting_approval"):
                check("T2a held: no webhook before release/reject", not [x for x in hooks if x.get("id") == jid], len(hooks))
                g0 = partner_view(jid)
                check("T2b partner does NOT see completed while held", g0.get("status") != "completed", g0.get("status"))
                note = "NOTA-INTERNA-" + uuid.uuid4().hex[:6]
                r = requests.post(BASE + "/jobs/%s/reject" % jid, data={"note": note}, headers=OPH, timeout=60)
                check("T2c reject HTTP 200 + code rejected_by_operator", r.status_code == 200 and r.json().get("failure_code") == "rejected_by_operator", (r.status_code, r.text[:150]))
                time.sleep(8)
                m = json.loads((JOBS / jid / "job_meta.json").read_text())
                g, h = common("T2", jid, name, m, "rejected_by_operator")
                check("T2f internal note never reaches the partner", note not in json.dumps(h) and note not in json.dumps(g), "")
                r2 = requests.post(BASE + "/jobs/%s/reject" % jid, data={"note": "again"}, headers=OPH, timeout=60)
                check("T2g second reject refused (400) and no second webhook", r2.status_code == 400 and len([x for x in hooks if x.get("id") == jid]) == 1, (r2.status_code, len(hooks)))
            else:
                check("T2 job reached done (needed to test Rifiuta)", False, m.get("status") + " | " + str(m.get("message"))[:120])

    bad = [n for n, ok in RES if not ok]
    print("\nRESULT: %d PASS / %d FAIL%s" % (len(RES) - len(bad), len(bad), (" -> " + ", ".join(bad)) if bad else ""), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
