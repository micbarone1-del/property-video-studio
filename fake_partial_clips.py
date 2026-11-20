"""fake_partial_clips.py - SOME clips are generated and some fail (FAKE instance, port 8001, zero cost). 2026-11-20.

Run (venv active, repo folder; the fake instance started with the production switches):   python3 -u fake_partial_clips.py      (about 5-8 minutes)

  P1  the first 3 Luma calls work, every later one fails (direct 400, fal failed) -> some scenes have a clip, some do not
      expected: job held "awaiting_approval" with the missing scenes listed as failed, the partner told NOTHING (no webhook, not "completed"),
      the operator told exactly once, the good clips kept on disk, no runaway retry loop
  P2  the operator redoes ONLY the missing scenes (the approve endpoint, faults cleared)
      expected: the job gets finished (done), the good clips are NOT paid for again (new Luma calls only for the missing scenes, attempts included),
      still no webhook before release (manual release mode)
Fake instance only (refuses unless /health says fake_providers true); production is never touched; nothing is deleted.
"""
import os, sys, json, time, uuid, random, threading, http.server, tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_failure_paths as ff
from fake_failure_paths import JOBS, BASE, KEYFILE, OPH, check, info, now, outbox, set_faults


def main():
    import requests
    from PIL import Image, ImageDraw
    import clip_provenance
    hz = requests.get(BASE + "/health", timeout=5).json()
    if hz.get("fake_providers") is not True:
        print("ABORT: port 8001 is not a fake instance:", hz)
        return 2
    auth = {"Authorization": "Bearer " + KEYFILE.read_text().strip()}
    tmp = Path(tempfile.mkdtemp(prefix="fakepart_"))
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
            print("  [%s] WEBHOOK: %s" % (now(), json.dumps(hooks[-1], ensure_ascii=False)[:200]), flush=True)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local = "http://127.0.0.1:%d" % srv.server_port
    (tmp / "p").mkdir()
    ph = []
    for i in range(8):
        r = random.Random("part-%d-%s" % (i, uuid.uuid4().hex))
        im = Image.new("RGB", (1600, 1200), tuple(r.randint(90, 220) for _ in range(3)))
        d = ImageDraw.Draw(im)
        for _ in range(40):
            x, y = r.randint(0, 1400), r.randint(0, 1000)
            d.rectangle([x, y, x + r.randint(40, 300), y + r.randint(40, 250)], fill=tuple(r.randint(0, 255) for _ in range(3)))
        im.save(tmp / "p" / ("%d.jpg" % i), quality=92)
        ph.append({"url": "%s/p/%d.jpg?u=%s" % (local, i, uuid.uuid4().hex[:6]), "order": i, "category": ("living", "kitchen")[i % 2]})
    name = "Prova P %s" % uuid.uuid4().hex[:5]
    body = {"external_ref": "F-P-" + uuid.uuid4().hex[:6], "agency_name": "PVS FAKE PART", "agency_external_id": "pvs-fake-part", "property_name": name,
            "description": "Trilocale luminoso di prova, con cucina abitabile, due camere e balcone. " * 2, "features": [], "photos": ph, "voice_id": "",
            "callback_url": local + "/hook"}

    def meta(jid):
        return json.loads((JOBS / jid / "job_meta.json").read_text())

    def mails(word=""):
        return [o for o in outbox() if o.get("kind") == "email" and name in str(o.get("subject")) and word in str(o.get("subject"))]

    def creates():
        return len([o for o in outbox() if o.get("kind") == "luma_create"])

    def wait(jid, stops, timeout=1500):
        t0, last = time.time(), None
        while time.time() - t0 < timeout:
            try:
                m = meta(jid)
            except Exception:
                time.sleep(3)
                continue
            cur = (m.get("status"), str(m.get("message"))[:80])
            if cur != last:
                print("  [%s +%ds] %s | %s" % (now(), time.time() - t0, cur[0], cur[1]), flush=True)
                last = cur
            if m.get("status") in stops:
                time.sleep(10)
                return meta(jid)
            time.sleep(4)
        info("timeout")
        return meta(jid)

    def clip_scenes(jid):
        m = meta(jid)
        return [i for i, sc in enumerate(m.get("scenes_config") or []) if clip_provenance.clip_file_for_scene(JOBS / jid, i, (sc or {}).get("scene_id")) is not None]

    print("\n== P1 first 3 Luma calls work, the rest fail", flush=True)
    set_faults({"luma_direct": ["ok"] * 3 + ["http_400"] * 100, "luma_fal": ["failed"] * 100})
    c0 = creates()
    r = requests.post(BASE + "/v1/videos", headers=auth, json=body, timeout=60)
    info("POST -> HTTP %s %s" % (r.status_code, r.text[:100]))
    if r.status_code != 200:
        return 1
    jid = r.json()["id"]
    for _ in range(60):
        if meta(jid).get("status") == "draft":
            break
        time.sleep(2)
    rr = requests.post(BASE + "/jobs/%s/start-generation" % jid, headers=OPH, timeout=60)
    info("start-generation -> HTTP %s" % rr.status_code)
    m = wait(jid, ("done", "failed", "awaiting_approval"))
    n_sc = len(m.get("scenes_config") or [])
    have = clip_scenes(jid)
    aw = m.get("awaiting_scenes") if isinstance(m.get("awaiting_scenes"), dict) else {}
    failed = [int(x) for x in (aw.get("failed") or [])]
    info("scenes: %d | with a clip: %s | listed as failed: %s | status %s | Luma create calls: %d" % (n_sc, have, failed, m.get("status"), creates() - c0))
    check("P1a some scenes have a clip and some do not (a real partial case)", 0 < len(have) < n_sc, (len(have), n_sc))
    check("P1b the job is held awaiting_approval (not done, not failed)", m.get("status") == "awaiting_approval", m.get("status"))
    check("P1c the scenes without a clip are exactly the ones listed as failed", sorted(set(range(n_sc)) - set(have)) == sorted(failed), (have, failed))
    g = requests.get(BASE + "/v1/videos/" + jid, headers=auth, timeout=30).json()
    check("P1d the partner is not told anything yet (no webhook, status not completed/failed)", not [x for x in hooks if x.get("id") == jid] and g.get("status") not in ("completed", "failed"), (len(hooks), g.get("status")))
    time.sleep(20)
    check("P1e the operator was told exactly once about this job's failed clips", len(mails("")) >= 1 and len([x for x in mails("") if "Nuovo job" not in str(x.get("subject"))]) == 1, [str(x.get("subject"))[:50] for x in mails("")])
    n_calls = creates() - c0
    check("P1f no runaway retry loop (Luma create calls <= 5 per scene)", n_calls <= 5 * n_sc, n_calls)
    good_before = {i: str(clip_provenance.clip_file_for_scene(JOBS / jid, i, (m["scenes_config"][i] or {}).get("scene_id"))) for i in have}
    mt_before = {i: os.path.getmtime(p) for i, p in good_before.items()}

    print("\n== P2 the operator redoes only the missing scenes", flush=True)
    set_faults({})
    c1 = creates()
    appr = {"approved_scenes": have, "redo_scenes": failed}
    r2 = requests.post(BASE + "/jobs/%s/approve" % jid, data={"approval": json.dumps(appr)}, headers=OPH, timeout=60)
    info("approve -> HTTP %s %s" % (r2.status_code, r2.text[:120]))
    check("P2a the approve call is accepted", r2.status_code == 200, (r2.status_code, r2.text[:120]))
    m = wait(jid, ("done", "failed", "awaiting_approval"))
    info("after the redo: status %s | %s" % (m.get("status"), str(m.get("message"))[:100]))
    check("P2b the job is finished (done)", m.get("status") == "done", m.get("status"))
    check("P2c every scene now has a clip", len(clip_scenes(jid)) == n_sc, clip_scenes(jid))
    new_calls = creates() - c1
    check("P2d only the missing scenes were generated again (new Luma calls <= number of missing scenes)", new_calls <= len(failed), (new_calls, len(failed)))
    same = all(os.path.exists(p) and os.path.getmtime(p) == mt_before[i] for i, p in good_before.items())
    check("P2e the good clips were not touched", same, "")
    time.sleep(10)
    check("P2f still no webhook before release (manual release mode)", not [x for x in hooks if x.get("id") == jid], len(hooks))
    info("cost fields: total=%s" % (m.get("total_cost_eur") or m.get("cost_eur")))
    bad = [n for n, ok in ff.RES if not ok]
    print("\nRESULT: %d PASS / %d FAIL%s" % (len(ff.RES) - len(bad), len(bad), (" -> " + ", ".join(bad)) if bad else ""), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
