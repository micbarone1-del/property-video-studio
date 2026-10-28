"""relinx_pilot_check.py - draft-level check of GIAL listings as Relinx will send them (2026-10-28).

We play Relinx: read a public relinx.it listing page, take its ORIGINAL photos (no category: the site shows none), remove the white
square padding that the site's own copies carry (the API photos Relinx really sent were clean - checked on job cc2aead8), serve them from a
tiny local server and POST them to /v1/videos on the TEST instance (start_test.sh, port 8002: real Claude, own jobs and data folders).
POST /v1/videos stops in draft, so no video is generated: cost = a few cents of Claude per listing. Then the same checks as draft_check.py.

Usage (venv active, test instance running):   python3 relinx_pilot_check.py relinx_listings.txt        # lines:  URL | label
Nothing here touches production: it refuses port 8000, and the partner key lives in the test instance's own data folder.
"""
import os, sys, io, re, json, html, time, uuid, threading, http.server, tempfile
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}
WHITE = 245          # a channel value above this counts as white padding


def parse_listing(page: str, url: str) -> dict:
    """Pure: {id, name, description, photos:[relative media paths in gallery order]} from a relinx.it listing page."""
    m = re.search(r"-(\d+)/?$", url.split("?")[0].rstrip("/") + "/")
    if not m:
        raise ValueError("no listing id at the end of the URL: " + url)
    lid = m.group(1)
    nodes = []
    for raw in re.findall(r"<script[^>]*ld\+json[^>]*>(.*?)</script>", page, re.S):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict):
                nodes.extend(x.get("@graph") if isinstance(x.get("@graph"), list) else [x])
    best = None
    for n in nodes:
        if isinstance(n, dict) and n.get("description") and (n.get("identifier") == lid or str(n.get("identifier")) == lid):
            best = n
            break
    if best is None:
        og = re.search(r'og:description" content="([^"]+)', page)
        if not og:
            raise ValueError("listing description not found in the page")
        best = {"description": html.unescape(og.group(1)), "name": ""}
    found = {}
    # the gallery images of THIS listing are the thumb/?variant=full ones (related listings only appear as variant=card);
    # media file names differ from listing to listing, so they cannot be used to find the photos
    for pm in re.finditer(r"/it/immobili/foto/(\d+)/thumb/\?variant=full(?:&amp;|&)v=\d+", page):
        found.setdefault(pm.group(1), html.unescape(pm.group(0)))
    return {"id": lid, "name": str(best.get("name") or ("Annuncio " + lid)), "description": str(best["description"]),
            "photos": list(found.values())}


def trim_bands(img):
    """Pure: removes pure-white padding rows/columns at the edges. Returns img unchanged if there is nothing to remove or the result looks wrong."""
    import numpy as np
    a = np.asarray(img.convert("RGB"))
    h, w, _ = a.shape
    content = a.min(axis=2) < WHITE
    rows = np.where(content.mean(axis=1) > 0.01)[0]
    cols = np.where(content.mean(axis=0) > 0.01)[0]
    if len(rows) == 0 or len(cols) == 0:
        return img
    y0, y1, x0, x1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    if (y1 - y0) * (x1 - x0) < 0.5 * h * w or ((y0 + (h - y1)) < 0.03 * h and (x0 + (w - x1)) < 0.03 * w):
        return img
    return img.crop((int(x0), int(y0), int(x1), int(y1)))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    base = os.environ.get("PVS_TEST_BASE", "http://127.0.0.1:8002")
    state = os.environ.get("PVS_TEST_STATE", "/var/www/pvs_test_state")
    jobs = Path(os.environ.get("PVS_TEST_JOBS", "/var/www/pvs_test_jobs"))
    if base.rstrip("/").endswith(":8000"):
        print("ABORT: port 8000 is production.")
        return 2
    os.environ["PVS_DATA_DIR"] = state + "/data"
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import requests
    import partner_api
    import draft_check
    from PIL import Image
    if not str(partner_api.PARTNERS_FILE).startswith(state):
        print("ABORT: the partner file is not inside the test state folder.")
        return 2
    try:
        hz = requests.get(base + "/health", timeout=5).json()
    except Exception as e:
        print("ABORT: test instance not reachable at " + base + " (./start_test.sh): " + str(e))
        return 2
    if hz.get("fake_providers") is not False:
        print("ABORT: " + base + " is not the real-providers test instance.")
        return 2
    Path(state + "/data").mkdir(parents=True, exist_ok=True)
    kf = Path(state + "/data/test_partner_key.txt")
    key = kf.read_text().strip() if kf.exists() else ""
    if not partner_api.verify_partner_key(key):
        key = partner_api.create_partner("TEST relinx-sim")["api_key"]
        kf.write_text(key)
    auth = {"Authorization": "Bearer " + key}

    tmp = Path(tempfile.mkdtemp(prefix="relinx_check_"))
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
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
    local = "http://127.0.0.1:" + str(srv.server_port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    listings = []
    for line in Path(argv[1]).read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            u, _, label = line.partition("|")
            listings.append((u.strip(), label.strip() or u.strip()))
    checks = []
    for url, label in listings:
        print("\n=== " + label + "  " + url, flush=True)
        try:
            if url.endswith(".json"):
                payload = payload_from_file(url, local)
                print("  request taken as sent by the partner: %d photos" % len(payload["photos"]), flush=True)
            else:
                page = requests.get(url, headers=UA, timeout=40).text
                L = parse_listing(page, url)
                if not L["photos"]:
                    raise ValueError("no photos found in the page")
                d = tmp / L["id"]
                d.mkdir(exist_ok=True)
                photos = []
                for i, rel in enumerate(L["photos"]):
                    im = Image.open(io.BytesIO(requests.get("https://relinx.it" + rel, headers=UA, timeout=60).content)).convert("RGB")
                    im = trim_bands(im)
                    im.save(d / ("%03d.jpg" % i), quality=95)
                    photos.append({"url": local + "/" + L["id"] + "/%03d.jpg?u=%s" % (i, uuid.uuid4().hex[:6]), "order": i})
                print("  photos: %d (first %s after trimming)" % (len(photos), Image.open(d / "000.jpg").size if photos else None), flush=True)
                payload = {"external_ref": "T-%s-%s" % (L["id"], uuid.uuid4().hex[:6]), "agency_name": "GIAL IMMOBILIARE",
                           "agency_external_id": "gial-test-" + L["id"], "property_name": L["name"], "description": L["description"],
                           "features": [], "photos": photos, "voice_id": "", "callback_url": local + "/hook"}
            r = requests.post(base + "/v1/videos", headers=auth, json=payload, timeout=60)
            if r.status_code != 200:
                print("  POST failed:", r.status_code, r.text[:200])
                checks.append({"job": "-", "name": label, "mode": None, "results": [("FAIL", "P1", "POST %s: %s" % (r.status_code, r.text[:120]))], "claude_eur": None})
                continue
            jid = r.json()["id"]
            t0, st = time.time(), None
            while time.time() - t0 < 900:
                st = requests.get(base + "/v1/videos/" + jid, headers=auth, timeout=30).json().get("status")
                if st in ("in_review", "failed", "completed"):
                    break
                time.sleep(5)
            time.sleep(3)
            print("  job %s partner status %s after %ds, webhooks for it: %d" % (jid, st, time.time() - t0, len([h for h in hooks if h.get("id") == jid])), flush=True)
            try:
                meta = json.loads((jobs / jid / "job_meta.json").read_text())
            except Exception:
                meta = {"status": "failed", "message": "no job_meta.json; partner status " + str(st)}
            n = len(meta.get("scenes_config") or [])
            res = draft_check.evaluate(meta, draft_check._silences(jobs / jid / "narration.mp3"), draft_check._hashes(jobs / jid, n))
            checks.append({"job": jid, "name": label, "mode": meta.get("narration_mode"), "results": res, "claude_eur": (meta.get("claude_usage") or {}).get("cost_eur")})
            print("  voce:", str(meta.get("narration_text") or "")[:600])
            print("  scene:", [c.get("category") for c in (meta.get("scenes_config") or [])])
        except Exception as e:
            print("  ERROR:", repr(e)[:200])
            checks.append({"job": "-", "name": label, "mode": None, "results": [("FAIL", "P0", repr(e)[:120])], "claude_eur": None})
    return draft_check.report(checks)


def payload_from_file(path: str, local: str) -> dict:
    """A request exactly as the partner sent it (JSON file). Only what must differ in a test is changed: a fresh external_ref (idempotency),
    and the callback goes to our local receiver so no real partner is ever called. Photo URLs, categories, texts stay as received."""
    p = json.loads(Path(path).read_text())
    for k in ("external_ref", "agency_name", "description", "photos"):
        if not p.get(k):
            raise ValueError("partner request file lacks " + k)
    p["external_ref"] = "T-%s-%s" % (str(p["external_ref"])[:30], uuid.uuid4().hex[:6])
    p["callback_url"] = local + "/hook"
    return p


if __name__ == "__main__":
    sys.exit(main(sys.argv))
