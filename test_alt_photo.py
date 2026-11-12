"""pick_alternative_photo (point 3): the best other photo of the same room, through the SHARED selection step; otherwise nothing (the operator decides)."""
import os, sys, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls
res = []
def check(name, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(info)))

REPORT = {"selected": {"bathrooms": [{"url": "B1", "url_used": "B1u", "original_url": None}], "kitchen": [{"url": "K1"}]},
          "candidate_urls": {"bathrooms": ["B1", "B2", "B3", "B4"], "kitchen": ["K1"], "bedrooms": ["D1", "D2"]}}
seen = {}
def fake_shared(photos, categories):
    seen["urls"] = [p["url"] for p in photos]; seen["cats"] = list(categories)
    return {categories[0]: [dict(p, **seen.get("tags", {}).get(p["url"], {})) for p in photos]}
ls._categorize_and_rank_photos = fake_shared

seen["tags"] = {}
r = ls.pick_alternative_photo(REPORT, "bathrooms")
check("A1 the photo already used is never an alternative; the pool goes through the shared step", seen["urls"] == ["B2", "B3", "B4"] and seen["cats"] == ["bathrooms"], seen)
check("A2 first of the ranked pool is returned", r["photo"]["url"] == "B2" and r["reason"] == "ok" and r["considered"] == 3, r)
seen["tags"] = {"B2": {"feature_visible": False}}
r = ls.pick_alternative_photo(REPORT, "bathrooms")
check("A3 a photo whose room feature is NOT visible is skipped", r["photo"]["url"] == "B3", r)
seen["tags"] = {"B2": {"feature_visible": False}, "B3": {"feature_visible": False}, "B4": {"feature_visible": False}}
r = ls.pick_alternative_photo(REPORT, "bathrooms")
check("A4 none passes -> no photo, reason says why", r["photo"] is None and "pass" in r["reason"], r)
r = ls.pick_alternative_photo(REPORT, "kitchen")
check("A5 a room with a single photo (already used) -> nothing to try", r["photo"] is None and r["reason"] == "no other photo of this room", r)
seen["tags"] = {}
r = ls.pick_alternative_photo(REPORT, "bathrooms", exclude_urls=["B2"])
check("A6 a photo already tried as alternative is excluded", r["photo"]["url"] == "B3", r)
seen["tags"] = {"B2": {"feature_visible": None}}
r = ls.pick_alternative_photo(REPORT, "bathrooms")
check("A7 feature check unknown (None) keeps the photo", r["photo"]["url"] == "B2", r)
def boom(photos, categories): raise RuntimeError("down")
ls._categorize_and_rank_photos = boom
r = ls.pick_alternative_photo(REPORT, "bathrooms")
check("A8 any error -> no photo (the operator decides), never raises", r["photo"] is None and r["reason"].startswith("error"), r)
check("A9 empty / missing report -> no photo, never raises", ls.pick_alternative_photo({}, "bathrooms")["photo"] is None and ls.pick_alternative_photo(None, "bathrooms")["photo"] is None)
print("%d/%d PASS" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
