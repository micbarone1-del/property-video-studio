"""Aerial / drone photos and illustrations leave the selection (2026-11-02). No network: vision is faked. Run: python3 test_aerial_filter.py"""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as ls
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); fails += 0 if c else 1

AERIAL_URLS = {"u_aerial", "u_aerial_cap"}
ILLUS_URLS = {"u_render", "u_render_living"}
def fake_word(url, fb, prompt, words=1):
    # the ONE question: "<what> <photo|render>"
    assert prompt == ls._VISION_DESCRIBE_PROMPT and words == 2
    if url == "u_fail": return ("", False)
    if url == "u_render_living": return ("living render", True)
    if url in ILLUS_URLS: return ("exterior render", True)
    if url == "u_living": return ("living photo", True)
    return (("aerial photo" if url in AERIAL_URLS else "exterior photo"), True)
ls._vision_one_word = fake_word
def photos():
    ls._describe_cache.clear()
    return [{"url": "u_aerial", "category": "exterior"}, {"url": "u_ground", "category": "exterior"},
            {"url": "u_aerial_cap", "category": "exterior", "label_it": "Facciata dell'immobile"}, {"url": "u_fail", "category": "outdoor"},
            {"url": "u_living", "category": "living"},
            {"url": "u_render", "category": "exterior"}, {"url": "u_render_living", "category": "living"}]
ps = photos(); r = ls.refine_exterior_outdoor_with_vision(ps)
by = {p["url"]: p for p in ps}
check("AF1 an aerial exterior photo without a property caption is removed from the selection", by["u_aerial"]["category"] == "uncategorized" and by["u_aerial"]["category_source"] == "vision_aerial" and r["aerial_removed"] == 1, (by["u_aerial"], r))
check("AF2 a ground photo stays", by["u_ground"]["category"] == "exterior")
check("AF3 an aerial photo whose agency caption ties it to the property stays", by["u_aerial_cap"]["category"] == "exterior")
check("AF4 a failed aerial call keeps the photo (never blocks)", by["u_fail"]["category"] in ("outdoor", "exterior") and by["u_fail"]["category_source"] != "vision_aerial")
check("AF5 interiors are untouched", by["u_living"]["category"] == "living")
os.environ["PVS_AERIAL_FILTER"] = "0"
ps = photos(); r = ls.refine_exterior_outdoor_with_vision(ps)
check("AF6 PVS_AERIAL_FILTER=0 turns it off", r["aerial_removed"] == 0 and {p["url"]: p for p in ps}["u_aerial"]["category"] == "exterior")
check("AF7 caption helper", ls.caption_ties_to_property("Vista della facciata") and not ls.caption_ties_to_property("Vista aerea"))
os.environ.pop("PVS_AERIAL_FILTER", None)
ps = photos(); r = ls.refine_exterior_outdoor_with_vision(ps); by = {p["url"]: p for p in ps}
check("AF8 an illustration / render labelled exterior is removed", by["u_render"]["category"] == "uncategorized" and by["u_render"]["category_source"] == "vision_illustration" and r["illustrations_removed"] == 2, (by["u_render"], r))
check("AF9 an illustration labelled as an interior room is removed too", by["u_render_living"]["category"] == "uncategorized")
check("AF10 the one prompt asks for aerial and photo | render", all(w in ls._VISION_DESCRIBE_PROMPT for w in ("- aerial:", "photo", "render")))
os.environ["PVS_AERIAL_FILTER"] = "0"
ps = photos(); r = ls.refine_exterior_outdoor_with_vision(ps)
check("AF11 switch off also keeps illustrations", r["illustrations_removed"] == 0 and {p["url"]: p for p in ps}["u_render"]["category"] == "exterior")
check("AF12 the question also covers high viewpoints looking down (Michele 2026-11-03, job 3fcff5a9 scene 5)", "looks clearly DOWNWARDS" in ls._VISION_DESCRIBE_PROMPT and "NOT aerial" in ls._VISION_DESCRIBE_PROMPT)
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
