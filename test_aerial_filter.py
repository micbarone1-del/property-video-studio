"""Aerial / drone photos leave the selection (2026-11-02). No network: vision is faked. Run: python3 test_aerial_filter.py"""
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
def fake_word(url, fb, prompt):
    if prompt == ls._VISION_AERIAL_PROMPT:
        return ("failed", False) if url == "u_fail" else (("aerial" if url in AERIAL_URLS else "ground"), True)
    return ("exterior", True)          # room question: every exterior/outdoor photo confirmed as exterior
ls._vision_one_word = fake_word
def photos():
    return [{"url": "u_aerial", "category": "exterior"}, {"url": "u_ground", "category": "exterior"},
            {"url": "u_aerial_cap", "category": "exterior", "label_it": "Facciata dell'immobile"}, {"url": "u_fail", "category": "outdoor"},
            {"url": "u_living", "category": "living"}]
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
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
