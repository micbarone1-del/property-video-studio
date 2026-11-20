"""fake_idempotency.py - the same request sent more than once to POST /v1/videos (FAKE instance, port 8001, zero cost). 2026-11-20.

Run (venv active, repo folder):   python3 -u fake_idempotency.py        (about 3-5 minutes)

  I1  the same external_ref sent twice in a row            -> the SAME job id, one job on disk, one "new job" mail
  I2  the same external_ref sent 8 times AT THE SAME TIME  -> ONE job (the check and the insert must not be separated by an await)
  I3  the same listing under a DIFFERENT external_ref      -> a second job is created and the operator gets ONE "possible duplicate" mail
  I4  the same external_ref after a FAILED attempt         -> a new job is allowed (designed: Relinx can retry after fixing the listing)
Each case uses its own agency (the per-agency 24 h limit is not what is being tested). Fake instance only; deletes nothing.
"""
import os, sys, json, time, uuid, random, threading, http.server, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_failure_paths as ff
from fake_failure_paths import JOBS, BASE, KEYFILE, check, info, outbox


def main():
    import requests
    from PIL import Image, ImageDraw
    hz = requests.get(BASE + "/health", timeout=5).json()
    if hz.get("fake_providers") is not True:
        print("ABORT: port 8001 is not a fake instance:", hz)
        return 2
    auth = {"Authorization": "Bearer " + KEYFILE.read_text().strip()}
    tmp = Path(tempfile.mkdtemp(prefix="fakeidem_"))

    class Local(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp), **k)

        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length') or 0))
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local = "http://127.0.0.1:%d" % srv.server_port

    def photos(tag, n):
        (tmp / tag).mkdir()
        out = []
        for i in range(n):
            r = random.Random("%s-%d-%s" % (tag, i, uuid.uuid4().hex))
            im = Image.new("RGB", (1600, 1200), tuple(r.randint(90, 220) for _ in range(3)))
            d = ImageDraw.Draw(im)
            for _ in range(40):
                x, y = r.randint(0, 1400), r.randint(0, 1000)
                d.rectangle([x, y, x + r.randint(40, 300), y + r.randint(40, 250)], fill=tuple(r.randint(0, 255) for _ in range(3)))
            im.save(tmp / tag / ("%d.jpg" % i), quality=92)
            out.append({"url": "%s/%s/%d.jpg?u=%s" % (local, tag, i, uuid.uuid4().hex[:6]), "order": i, "category": ("living", "kitchen")[i % 2]})
        return out

    def payload(agency, ref, name, ph):
        return {"external_ref": ref, "agency_name": "PVS FAKE IDEM " + agency, "agency_external_id": "pvs-fake-idem-" + agency, "property_name": name,
                "description": "Trilocale luminoso di prova, con cucina abitabile, due camere e balcone. " * 2, "features": [], "photos": ph, "voice_id": "", "callback_url": local + "/hook"}

    def post(p):
        r = requests.post(BASE + "/v1/videos", headers=auth, json=p, timeout=60)
        return r.status_code, (r.json() if r.status_code == 200 else r.text[:120])

    def on_disk(ref):
        n = []
        for m in JOBS.glob("*/job_meta.json"):
            try:
                j = json.loads(m.read_text())
            except Exception:
                continue
            if j.get("external_ref") == ref:
                n.append((m.parent.name, j))
        return n

    def mails(name, word):
        return [o for o in outbox() if o.get("kind") == "email" and name in str(o.get("subject")) and word in str(o.get("subject"))]

    def settle(jid, secs=120):
        for _ in range(secs // 3):
            try:
                if json.loads((JOBS / jid / "job_meta.json").read_text()).get("status") in ("draft", "failed"):
                    return
            except Exception:
                pass
            time.sleep(3)

    print("\n== I1 same external_ref twice in a row", flush=True)
    name, ref = "Prova I1 %s" % uuid.uuid4().hex[:5], "F-I1-" + uuid.uuid4().hex[:6]
    p = payload("a", ref, name, photos("i1", 8))
    c1, r1 = post(p)
    time.sleep(3)
    c2, r2 = post(p)
    info("HTTP %s / %s -> %s / %s" % (c1, c2, r1, r2))
    check("I1a both answered 200 with the SAME job id", c1 == c2 == 200 and r1["id"] == r2["id"], (r1, r2))
    settle(r1["id"])
    check("I1b exactly one job on disk for this external_ref", len(on_disk(ref)) == 1, len(on_disk(ref)))
    check("I1c operator got exactly one 'Nuovo job' mail", len(mails(name, "Nuovo job")) == 1, len(mails(name, "Nuovo job")))

    print("\n== I2 same external_ref, 8 requests at the same time", flush=True)
    name2, ref2 = "Prova I2 %s" % uuid.uuid4().hex[:5], "F-I2-" + uuid.uuid4().hex[:6]
    p2 = payload("b", ref2, name2, photos("i2", 8))
    bar = threading.Barrier(8)

    def go(_):
        bar.wait()
        return post(p2)

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(go, range(8)))
    time.sleep(6)
    ids = {r[1]["id"] for r in res if r[0] == 200}
    info("answers: %s" % sorted({str(r[0]) for r in res}))
    check("I2a all 8 answered 200", all(r[0] == 200 for r in res), [r[0] for r in res])
    check("I2b ONE job id in the answers", len(ids) == 1, ids)
    check("I2c exactly one job on disk for this external_ref", len(on_disk(ref2)) == 1, len(on_disk(ref2)))

    print("\n== I3 same listing, different external_ref", flush=True)
    name3 = "Prova I3 %s" % uuid.uuid4().hex[:5]
    ph3 = photos("i3", 8)
    ref3a, ref3b = "F-I3a-" + uuid.uuid4().hex[:6], "F-I3b-" + uuid.uuid4().hex[:6]
    c1, r1 = post(payload("c", ref3a, name3, ph3))
    settle(r1["id"])
    c2, r2 = post(payload("c", ref3b, name3, ph3))
    time.sleep(8)
    info("HTTP %s / %s -> %s / %s" % (c1, c2, r1, r2))
    check("I3a a second job is created (different id)", c1 == c2 == 200 and r1["id"] != r2["id"], (r1, r2))
    m2 = json.loads((JOBS / r2["id"] / "job_meta.json").read_text())
    check("I3b the second job points to the first (possible_duplicate_of)", r1["id"] in json.dumps(m2.get("possible_duplicate_of")), m2.get("possible_duplicate_of"))
    check("I3c operator got exactly one 'Possibile doppione' mail", len(mails(name3, "doppione")) == 1, len(mails(name3, "doppione")))

    print("\n== I4 same external_ref after a failed attempt", flush=True)
    name4, ref4 = "Prova I4 %s" % uuid.uuid4().hex[:5], "F-I4-" + uuid.uuid4().hex[:6]
    p4 = payload("d", ref4, name4, photos("i4", 1))
    c1, r1 = post(p4)
    settle(r1["id"], 60)
    c2, r2 = post(p4)
    info("HTTP %s / %s -> %s / %s" % (c1, c2, r1, r2))
    check("I4 after a failed attempt the same external_ref gets a NEW job (designed retry)", c1 == c2 == 200 and r1["id"] != r2["id"], (r1, r2))

    bad = [n for n, ok in ff.RES if not ok]
    print("\nRESULT: %d PASS / %d FAIL%s" % (len(ff.RES) - len(bad), len(bad), (" -> " + ", ".join(bad)) if bad else ""), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
