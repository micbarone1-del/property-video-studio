"""2026-11-12: the photo that is JUDGED is the photo that is USED (listing 105, scene 5). No network, no API key."""
import base64, io, os, sys, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
from PIL import Image
import listing_scraper as ls
import photo_format as pf

res = []
def check(name, ok, extra=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  [%s]" % extra))

def jpg(w, h, grad=False):
    im = Image.new("RGB", (w, h), (90, 120, 150))
    if grad:
        for y in range(h):
            for x in range(0, w, 50):
                im.putpixel((x, y), (y % 256, 0, 0))
    b = io.BytesIO(); im.save(b, "JPEG", quality=95); return b.getvalue()

PORTRAIT, LANDSCAPE = jpg(600, 1000, True), jpg(1600, 900)
size = lambda b: Image.open(io.BytesIO(b)).size

# P1-P3 the shared cut itself (same numbers the video has always used)
cut = pf.normalize_photo_to_format(PORTRAIT, "landscape")
check("P1 portrait photo -> 16:9 band, top-biased (600x337)", size(cut) == (600, 337), size(cut))
check("P2 landscape photo is left as it is", pf.normalize_photo_to_format(LANDSCAPE, "landscape") == LANDSCAPE)
check("P3 api_server uses the shared function (alias, no second copy)",
      "from photo_format import normalize_photo_to_format as _normalize_photo_to_format" in open("api_server.py").read()
      and "def _normalize_photo_to_format" not in open("api_server.py").read())

# T1-T4 the ONE download function returns the photo as the video will use it
class _Resp:
    def __init__(self, c): self.content, self.status_code = c, 200
    def raise_for_status(self): pass
store = {"https://x/portrait.jpg": PORTRAIT, "https://x/land.jpg": LANDSCAPE, "https://x/bad.jpg": b"not an image"}
real_get = ls.requests.get
ls.requests.get = lambda u, timeout=0: _Resp(store[u])
r = ls.fetch_photo_bytes("https://x/portrait.jpg")
check("T1 a portrait photo comes back already cut to 16:9 (600x337)", r["ok"] and size(r["content"]) == (600, 337), size(r["content"]))
check("T2 a landscape photo comes back unchanged", ls.fetch_photo_bytes("https://x/land.jpg")["content"] == LANDSCAPE)
check("T3 as_used=False gives the original bytes", ls.fetch_photo_bytes("https://x/portrait.jpg", as_used=False)["content"] == PORTRAIT)
check("T4 bytes that are not an image come back as they are (never an error)", ls.fetch_photo_bytes("https://x/bad.jpg")["content"] == b"not an image")
# T5 the stages read photos only through it: no other requests.get in the module (the HEAD of the resolution upgrade is not a download)
src = open("listing_scraper.py").read()
check("T5 exactly one real photo download (= requests.get) in listing_scraper: fetch_photo_bytes", src.count("= requests.get(") == 1, src.count("= requests.get("))
ls.requests.get = real_get

# R1-R3 the comparison reads the photos through it, on the stronger model
photos = {"u_portrait": PORTRAIT, "u_land": LANDSCAPE}
ls.fetch_photo_bytes = lambda url, fb=None, timeout=20, attempts=1, as_used=True: {"ok": True, "content": ls._photo_as_used(photos[url]), "url_used": url, "used_fallback": False, "error": None}
sent = {"sizes": [], "model": None}
class _Msgs:
    def create(self, model=None, max_tokens=0, messages=None):
        sent["model"] = model
        for part in messages[0]["content"]:
            if part.get("type") == "image":
                sent["sizes"].append(size(base64.b64decode(part["source"]["data"])))
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="[2, 1]")], usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))
class _Client:
    def __init__(self, *a, **k): self.messages = _Msgs()
ls.anthropic = types.SimpleNamespace(Anthropic=_Client)
out = ls.rank_photos_by_quality("bathrooms", [{"url": "u_portrait"}, {"url": "u_land"}])
check("R1 the comparison receives the portrait photo as cut for the video (600x337)", sent["sizes"][0] == (600, 337), sent["sizes"])
check("R2 the landscape photo reaches the comparison unchanged (1600x900)", sent["sizes"][1] == (1600, 900), sent["sizes"])
check("R3 the comparison runs on RANK_MODEL (Sonnet)", sent["model"] == ls.RANK_MODEL == "claude-sonnet-5-5", sent["model"])
check("R4 the order returned follows the model's answer [2, 1], no second ordering rule", [p["url"] for p in out] == ["u_land", "u_portrait"])
check("R5 no cut-share / demotion workflow left in the selection", "cut_share" not in src and "LOW_CUT" not in src)

# F1-F6 the room-feature gate
def mk(*names): return [{"url": n} for n in names]
def run(answers, cat="bathrooms", names=("a", "b", "c", "d")):
    seen = []
    def check_fn(c, p, q):
        seen.append(p["url"]); return answers[p["url"]]
    by = {cat: mk(*names)}
    summ = ls.filter_missing_feature_candidates(by, check=check_fn)
    return [p["url"] for p in by[cat]], seen, summ, by
order, seen, summ, by = run({"a": False, "b": True, "c": True, "d": True})
check("F1 first ranked has no fixtures -> the next one that shows them goes first", order == ["b", "c", "d", "a"], order)
check("F2 the check stops at the first yes (c and d are not asked)", seen == ["a", "b"], seen)
check("F3 the failed photo is tagged feature_visible False, the good one True", by["bathrooms"][3]["feature_visible"] is False and by["bathrooms"][0]["feature_visible"] is True)
order, seen, summ, by = run({"a": False, "b": False, "c": False, "d": True})
check("F4 nothing passes in the first 3 -> only 3 asked, nothing deleted, 4 photos stay", len(seen) == 3 and len(order) == 4 and summ["bathrooms"]["passed"] is False, (seen, summ))
order, seen, summ, by = run({"a": None, "b": True, "c": True, "d": True})
check("F5 a failed call (None) keeps the photo in front", order[0] == "a", order)
by = {"living": mk("a", "b")}
check("F6 categories without a defining-feature question are untouched", ls.filter_missing_feature_candidates(by, check=lambda *x: False) == {} and [p["url"] for p in by["living"]] == ["a", "b"])
print("%d/%d PASS" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
