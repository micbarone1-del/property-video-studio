"""Tests of the render second look and the banner discard (listing_scraper). Fake vision answers: no network, no cost. Prints PASS/FAIL."""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as ls

fails = 0
def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (" " + str(info) if info and not cond else ""))
    if not cond: fails += 1

DESC = {}        # url -> (what, source)
CONFIRM = {}     # url -> (is_render, ok)
CALLS = []
def fake_describe(url, fb=None):
    w, s = DESC[url]; return w, s, True
def fake_confirm(url, fb=None):
    CALLS.append(url); return CONFIRM[url]
ls._describe_photo = fake_describe
ls._confirm_render = fake_confirm

def run(photos):
    CALLS.clear()
    return ls.refine_exterior_outdoor_with_vision(photos)

def P(url, cat):
    return {"url": url, "category": cat, "category_source": None}

# R1 interior called render, second look says photo -> kept
DESC.update({"a": ("kitchen", "render"), "b": ("bedrooms", "render"), "c": ("exterior", "render"), "d": ("kitchen", "banner"),
             "e": ("living", "photo"), "f": ("bathrooms", "render"), "g": ("outdoor", "banner")})
CONFIRM.update({"a": (False, True), "b": (True, True), "c": (True, True), "f": (True, False)})
ph = [P("a", "kitchen"), P("b", "bedrooms"), P("c", "exterior"), P("d", "kitchen"), P("e", "living"), P("f", "bathrooms"), P("g", "outdoor")]
s = run(ph)
by = {p["url"]: p for p in ph}
check("R1 second look says photo: photo kept in its category", by["a"]["category"] == "kitchen" and ls.photo_exclusion(by["a"]) is None, by["a"])
check("R1 recorded in the audit field", by["a"].get("render_second_look") == "photo")
check("R2 second look says render: excluded as render", by["b"]["category"] == "uncategorized" and by["b"]["category_source"] == "vision_illustration")
check("R3 exterior render: excluded, NO second look", by["c"]["category_source"] == "vision_illustration" and "c" not in CALLS, CALLS)
check("R4 banner: excluded with its own reason", by["d"]["category_source"] == "vision_banner" and "banner" in str(ls.photo_exclusion(by["d"])), ls.photo_exclusion(by["d"]))
check("R5 ordinary photo untouched", by["e"]["category"] == "living" and ls.photo_exclusion(by["e"]) is None)
check("R6 second look failed: first verdict stands", by["f"]["category_source"] == "vision_illustration")
check("R7 banner on an outdoor photo is excluded too", by["g"]["category_source"] == "vision_banner")
check("R8 second look only asked for the flagged interior photos", sorted(CALLS) == ["a", "b", "f"], CALLS)
check("R9 summary counts", s.get("banners_removed") == 2 and s.get("renders_saved_by_second_look") == 1 and s.get("illustrations_removed") == 3, s)
# R10 switch off: the first verdict stands for everyone
os.environ["PVS_RENDER_SECOND_LOOK"] = "0"
ph2 = [P("a", "kitchen")]; run(ph2)
check("R10 PVS_RENDER_SECOND_LOOK=0: no second look, photo excluded", ph2[0]["category_source"] == "vision_illustration" and not CALLS, CALLS)
os.environ.pop("PVS_RENDER_SECOND_LOOK")
# R11 audit exposes the second look
audit = ls.build_photo_audit(ph)
check("R11 audit has render_second_look", any(a.get("render_second_look") == "photo" for a in audit))
# R12 the prompt knows the banner value; the parse of a banner answer
check("R12 prompt lists the banner", "- banner:" in ls._VISION_DESCRIBE_PROMPT and "VENDUTO" in ls._VISION_DESCRIBE_PROMPT)
ls._describe_photo = ls.__dict__.get("_orig_describe") or ls._describe_photo
import importlib; importlib.reload(ls)
ls._vision_one_word = lambda *a, **k: ("kitchen banner", True)
ls._describe_cache.clear()
check("R13 two words 'kitchen banner' parse to source banner", ls._describe_photo("zz")[:2] == ("kitchen", "banner"))
ls._vision_one_word = lambda *a, **k: ("kitchen photo", True); ls._describe_cache.clear()
check("R14 'kitchen photo' stays photo", ls._describe_photo("yy")[:2] == ("kitchen", "photo"))
ls._vision_one_word = lambda *a, **k: ("bedrooms render", True); ls._describe_cache.clear()
check("R15 'bedrooms render' stays render", ls._describe_photo("xx")[:2] == ("bedrooms", "render"))
print("RESULT", "ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
