"""6 (2026-10-12, A+): vision classifier + exterior/outdoor check. No network, no API key."""
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

# 3. A+ : only exterior/outdoor candidates are checked, interiors untouched
urls = {"e1": "exterior", "e2": "other", "o1": "outdoor", "o2": "other", "o3": "living", "e3": "outdoor"}
ls_calls = []
def stub(url, fb=None):
    ls_calls.append(url)
    return ("uncategorized" if urls[url] == "other" else urls[url], True)
ls._classify_photo_vision = stub
photos = [{"url": "e1", "category": "exterior"},          # confirmed
          {"url": "e2", "category": "exterior"},          # entrance hall read as facade -> excluded
          {"url": "k1", "category": "kitchen"},           # interior: never sent to vision
          {"url": "l1", "category": "living"},            # interior: never sent to vision
          {"url": "o1", "category": "outdoor"},           # confirmed
          {"url": "o2", "category": "outdoor"},           # communal portico read as balcony -> excluded
          {"url": "o3", "category": "outdoor"},           # a room labelled balcony -> excluded, NOT turned into living
          {"url": "e3", "category": "exterior"}]          # courtyard-side balcony labelled facade -> swapped to outdoor
s = ls.refine_exterior_outdoor_with_vision(photos)
cats = [p["category"] for p in photos]
check("R1 only exterior/outdoor candidates are sent to vision", sorted(ls_calls) == ["e1", "e2", "e3", "o1", "o2", "o3"], ls_calls)
check("R2 interior labels untouched", cats[2] == "kitchen" and cats[3] == "living" and "category_source" not in photos[2])
check("R3 confirmed / excluded / swapped", cats[0] == "exterior" and cats[1] == "uncategorized" and cats[4] == "outdoor" and cats[5] == "uncategorized" and cats[6] == "uncategorized" and cats[7] == "outdoor", cats)
check("R4 page label kept in category_page", photos[1]["category_page"] == "exterior" and photos[7]["category_page"] == "exterior" and photos[1]["category_source"] == "vision_refine")
check("R5 summary counts", s["checked"] == 6 and s["confirmed"] == 2 and s["swapped_exterior_outdoor"] == 1 and s["excluded_as_other"] == 3 and s["kept_page_label_after_failure"] == 0 and s["not_checked_over_cap"] == 0, s)

# 4. failure keeps the label; cap; skip photos already classified by vision
fails_map = {"f1": ("uncategorized", False), "f2": ("outdoor", True)}
ls._classify_photo_vision = lambda url, fb=None: fails_map[url]
ph = [{"url": "f1", "category": "exterior"}, {"url": "f2", "category": "exterior"}]
s = ls.refine_exterior_outdoor_with_vision(ph)
check("R6 vision failure keeps the label and is marked", ph[0]["category"] == "exterior" and ph[0]["category_source"] == "page_fallback" and ph[1]["category"] == "outdoor" and s["kept_page_label_after_failure"] == 1, (ph, s))
ls._classify_photo_vision = lambda url, fb=None: ("exterior", True)
ph = [{"url": f"c{i}", "category": "exterior"} for i in range(10)]
s = ls.refine_exterior_outdoor_with_vision(ph, max_photos=4)
check("R7 cap: only the first 4 checked, the rest keep the label", s["checked"] == 4 and s["not_checked_over_cap"] == 6 and ph[9]["category_source"] == "page_not_checked" and ph[9]["category"] == "exterior", s)
ph = [{"url": "v1", "category": "outdoor", "category_source": "vision"}]
calls = []
ls._classify_photo_vision = lambda url, fb=None: calls.append(url) or ("exterior", True)
s = ls.refine_exterior_outdoor_with_vision(ph)
check("R8 photo already classified by vision is not checked twice", calls == [] and s["checked"] == 0 and ph[0]["category"] == "outdoor")
check("R9 empty list ok", ls.refine_exterior_outdoor_with_vision([])["checked"] == 0)

# 5. old API still works (single implementation)
ls._classify_photo_vision = real
ANSWERS.clear(); ANSWERS["__text__"] = "bathrooms"
check("C1 classify_uncategorized_photo still returns the category", ls.classify_uncategorized_photo("u", None) == "bathrooms")
ph = [{"url": "x", "category": "uncategorized"}, {"url": "y", "category": "living"}]
ls.resolve_uncategorized_photos(ph)
check("C2 resolve_uncategorized_photos only touches uncategorized photos", ph[0]["category"] == "bathrooms" and ph[1]["category"] == "living")
check("C3 resolved photo is marked as vision", ph[0].get("category_source") == "vision" and "category_source" not in ph[1])

# 5b. 2026-10-27: a "living" photo that is really the entrance hall / corridor leaves the selection; empty living rooms stay
real_hall = ls._is_hall_photo
HALLS = {"h1": (True, True), "l_ok": (False, True), "l_fail": (False, False)}
ls._is_hall_photo = lambda url, fb=None: HALLS[url]
ls._classify_photo_vision = lambda url, fb=None: ("exterior", True)
ph = [{"url": "h1", "category": "living"}, {"url": "l_ok", "category": "living"}, {"url": "l_fail", "category": "living"}, {"url": "k", "category": "kitchen"}]
s = ls.refine_exterior_outdoor_with_vision(ph)
check("H1 a living-labelled hall / corridor becomes uncategorized (leaves the selection), others keep the label", [p["category"] for p in ph] == ["uncategorized", "living", "living", "kitchen"] and ph[0]["category_page"] == "living" and ph[0]["category_source"] == "vision_hall", ph)
check("H2 failed call keeps the label and is marked; kitchen is not checked", ph[2]["category_source"] == "page_fallback" and "category_source" not in ph[3] and s["living_checked"] == 3 and s["halls_removed_from_living"] == 1, s)
ph = [{"url": f"l_ok", "category": "living"} for _ in range(12)]
s = ls.refine_exterior_outdoor_with_vision(ph)
check("H3 at most MAX_LIVING_TO_CHECK living photos are checked", s["living_checked"] == ls.MAX_LIVING_TO_CHECK == 8)
ls._is_hall_photo = real_hall
HP = ls._VISION_HALL_PROMPT
check("H4 hall question: an empty / unfurnished living room is NOT a hall", "unfurnished living room" in HP and "hall or room" in HP)
sent = {}
ls._vision_one_word = lambda u, fb, prompt: (sent.update(p=prompt) or ("hall", True))
check("H5 _is_hall_photo uses the shared one-word helper", ls._is_hall_photo("u")[0] is True and sent["p"] == HP)

# 6. wiring (static): one shared function, both paths, before the acceptance rule
api = open("api_server.py", encoding="utf-8").read()
url_part = api.split("async def _prepare_url_draft_work")[1].split("async def ")[0]   # Patch M: the URL path now runs in this background worker
rel_part = api.split("async def _build_relinx_job_in_background")[1].split("\ndef ")[0]
check("W1 URL path: resolve unlabeled, then refine exterior/outdoor, then acceptance", url_part.index("resolve_uncategorized_photos") < url_part.index("refine_exterior_outdoor_with_vision") < url_part.index("check_listing_scope"))
check("W2 Relinx path: same two shared functions, before acceptance", rel_part.index("resolve_uncategorized_photos") < rel_part.index("refine_exterior_outdoor_with_vision") < rel_part.index("check_listing_scope"))
check("W3 summary saved in selection_report in both paths", api.count('selection_report["classification"] = classification_summary') == 2)
check("W5 old whole-listing reclassification is gone (no duplicate implementation)", not hasattr(ls, "reclassify_photos_with_vision") and "reclassify_photos_with_vision" not in api)
check("W4 usage counter is thread safe", hasattr(ls, "_claude_lock"))

P = ls._VISION_CLASSIFY_PROMPT
check("P6 prompt v2: kitchen wins when cabinets/hob/sink are the main subject (open-plan)", "choose kitchen whenever cabinets" in P)
check("P7 prompt v2: living only with sofa/lounge/dining table; facade also from inner courtyard", "only when a sofa" in P and "inner courtyard" in P)
check("P8 prompt v3: shared/condominium spaces and a single tree close up are 'other', not outdoor", "condominium space" in P and "a single tree or plant close up" in P)
check("P9 prompt v3 (2026-10-27): the view FROM A WINDOW of the home is outdoor (usable as the closing view), no longer 'other'", "view FROM A WINDOW" in P and "view from a window, a tree" not in P)
print(f"RESULT: {'ALL PASS' if not fails else 'FAIL'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
