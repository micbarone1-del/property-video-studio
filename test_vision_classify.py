"""6 (2026-10-12): photos classified from the image by Claude vision. No network, no API key."""
import os, sys, types, io
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls
from PIL import Image

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def jpeg(w=2000, h=1500):
    b = io.BytesIO(); Image.new("RGB", (w, h), (120, 130, 140)).save(b, "JPEG"); return b.getvalue()

ANSWERS = {}; SENT = []; DOWNLOAD_FAIL = set()
def fake_fetch(url, fallback_url=None, timeout=20, attempts=1):
    if url in DOWNLOAD_FAIL:
        return {"ok": False, "content": None, "url_used": None, "used_fallback": False, "error": "download failed: 404"}
    return {"ok": True, "content": jpeg(), "url_used": url, "used_fallback": False, "error": None}
ls.fetch_photo_bytes = fake_fetch
ls._track_claude = lambda r: r
class Msgs:
    def create(self, **kw):
        content = kw["messages"][0]["content"]
        img = [c for c in content if c.get("type") == "image"][0]["source"]["data"]
        SENT.append(img)
        # the answer is keyed by the photo currently being asked about (set through CURRENT by the url order)
        raise_ = ANSWERS.get("__raise__")
        if raise_: raise RuntimeError("api down")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=ANSWERS["__text__"])])
class FakeClient:
    def __init__(self, api_key=None): self.messages = Msgs()
ls.anthropic.Anthropic = FakeClient

# per-URL answers: replace the low-level call with a deterministic map but keep the real parsing
real = ls._classify_photo_vision
def with_answer(url_map):
    def f(url, fallback=None):
        ANSWERS["__text__"] = url_map[url]
        return real(url, fallback)
    return f

# 1. parsing of the model reply through the real function
for txt, exp in (("kitchen", "kitchen"), ("Kitchen.", "kitchen"), ("bedrooms\n", "bedrooms"), ("other", "uncategorized"), ("a bathroom", "uncategorized"), ("", "uncategorized")):
    ANSWERS.clear(); ANSWERS["__text__"] = txt
    check(f"P1 reply {txt!r} -> {exp}", real("u", None) == (exp, True), real("u", None))
ANSWERS.clear(); ANSWERS["__raise__"] = True
check("P2 API error -> ('uncategorized', False)", real("u", None) == ("uncategorized", False))
ANSWERS.clear(); DOWNLOAD_FAIL.add("bad")
check("P3 download error -> ('uncategorized', False), no raise", real("bad", None) == ("uncategorized", False))
DOWNLOAD_FAIL.clear()

# 2. image is downscaled before being sent
ANSWERS.clear(); ANSWERS["__text__"] = "living"; SENT.clear()
real("u", None)
import base64
im = Image.open(io.BytesIO(base64.b64decode(SENT[0])))
check("P4 image sent is downscaled to <= 768 px", max(im.size) <= 768, im.size)
check("P5 prompt asks about PRIVATE outdoor spaces and 'other' for entrance/corridor/shared areas",
      "PRIVATE outdoor" in ls._VISION_CLASSIFY_PROMPT and "entrance hall" in ls._VISION_CLASSIFY_PROMPT and "portico" in ls._VISION_CLASSIFY_PROMPT)

# 3. reclassify in place
urls = {"u1": "exterior", "u2": "other", "u3": "kitchen", "u4": "kitchen", "u5": "outdoor", "u6": "other"}
photos = [{"url": "u1", "category": "exterior"},          # unchanged
          {"url": "u2", "category": "exterior"},          # entrance hall wrongly read as exterior -> excluded
          {"url": "u3", "category": "living"},            # wrong page label -> kitchen
          {"url": "u4", "category": "kitchen"},
          {"url": "u5", "category": "outdoor"},
          {"url": "u6", "category": "outdoor"}]           # communal portico read as balcony -> excluded
ls._classify_photo_vision = lambda url, fb=None: ("uncategorized" if urls[url] == "other" else urls[url], True)
s = ls.reclassify_photos_with_vision(photos)
cats = [p["category"] for p in photos]
check("R1 categories replaced in order", cats == ["exterior", "uncategorized", "kitchen", "kitchen", "outdoor", "uncategorized"], cats)
check("R2 page label kept in category_page, source vision", photos[1]["category_page"] == "exterior" and photos[2]["category_page"] == "living" and all(p["category_source"] == "vision" for p in photos))
check("R3 summary counts", s["classified"] == 6 and s["changed_vs_page"] == 3 and s["excluded_as_other"] == 2 and s["kept_page_label_after_failure"] == 0 and s["not_checked_over_cap"] == 0, s)

# 4. failure keeps the page label; cap
fails_map = {"f1": ("uncategorized", False), "f2": ("bathrooms", True)}
ls._classify_photo_vision = lambda url, fb=None: fails_map[url]
ph = [{"url": "f1", "category": "bedrooms"}, {"url": "f2", "category": "kitchen"}]
s = ls.reclassify_photos_with_vision(ph)
check("R4 vision failure keeps the page label and is marked", ph[0]["category"] == "bedrooms" and ph[0]["category_source"] == "page_fallback" and ph[1]["category"] == "bathrooms" and s["kept_page_label_after_failure"] == 1, (ph, s))
ls._classify_photo_vision = lambda url, fb=None: ("living", True)
ph = [{"url": f"c{i}", "category": "kitchen"} for i in range(10)]
s = ls.reclassify_photos_with_vision(ph, max_photos=4)
check("R5 cap: only the first 4 classified, the rest keep the page label", [p["category"] for p in ph] == ["living"] * 4 + ["kitchen"] * 6 and ph[9]["category_source"] == "page_not_checked" and s["not_checked_over_cap"] == 6, s)
check("R6 empty list ok", ls.reclassify_photos_with_vision([])["classified"] == 0)

# 5. old API still works (single implementation)
ls._classify_photo_vision = real
ANSWERS.clear(); ANSWERS["__text__"] = "bathrooms"
check("C1 classify_uncategorized_photo still returns the category", ls.classify_uncategorized_photo("u", None) == "bathrooms")
ph = [{"url": "x", "category": "uncategorized"}, {"url": "y", "category": "living"}]
ls.resolve_uncategorized_photos(ph)
check("C2 resolve_uncategorized_photos only touches uncategorized photos", ph[0]["category"] == "bathrooms" and ph[1]["category"] == "living")

# 6. wiring (static)
api = open("api_server.py", encoding="utf-8").read()
check("W1 URL path uses vision reclassification and no longer the page-only resolve", "scraper.reclassify_photos_with_vision, extraction[\"photos\"]" in api and "scraper.resolve_uncategorized_photos, extraction[\"photos\"]" not in api)
check("W2 Relinx path keeps CRM categories + uncategorized fallback only", "scraper.resolve_uncategorized_photos, photos_for_selection" in api and "reclassify_photos_with_vision" not in api.split("_build_relinx_job_in_background")[1])
check("W3 classification summary saved in selection_report", api.count('selection_report["classification"] = classification_summary') == 1)
check("W4 usage counter is thread safe", hasattr(ls, "_claude_lock"))

print(f"RESULT: {'ALL PASS' if not fails else 'FAIL'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
