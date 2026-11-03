"""Feasibility gate + per-photo audit (2026-11-03, Michele). No network: vision is faked. Run: python3 test_feasibility.py"""
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
def ph(i, cat, src=None, label=None, **kw):
    d = {"url": f"u{i}", "category": cat}
    if src: d["category_source"] = src
    if label: d["label_it"] = label
    d.update(kw); return d
EMPTY = lambda url, fb, prompt: ("empty", True)
FURN = lambda url, fb, prompt: ("furnished", True)

# F1-F3 audit and counts
photos = [ph(1, "uncategorized", "vision_illustration"), ph(2, "uncategorized", "vision_illustration"), ph(3, "uncategorized", "vision_aerial"),
          ph(4, "living"), ph(5, "kitchen", quality_rejected=True), ph(6, "uncategorized", "vision_hall"), ph(7, "uncategorized")]
ex = ls.exclusion_counts(photos)
check("F1 exclusion counts by reason", ex == {"illustrazioni o render": 2, "viste aeree o dall'alto": 1, "scarsa qualità": 1, "ingressi o corridoi": 1, "ambiente non riconosciuto": 1}, ex)
au = ls.build_photo_audit(photos)
check("F2 audit has one row per photo with source and reason", len(au) == 7 and au[0]["excluded"] == "illustrazioni o render" and au[3]["excluded"] is None and au[3]["source"] == "partner_or_page", au[:4])
r = ls.check_listing_acceptance([ph(1, "uncategorized", "vision_illustration")] * 1 + [ph(i, "uncategorized", "vision_illustration") for i in range(2, 10)] + [ph(20, "living"), ph(21, "kitchen")])
check("F3 a listing of renders is rejected and the message says how many renders", (not r["ok"]) and "9 illustrazioni o render" in r["message"] and r["code"] == "insufficient_photos", r["message"])
# F4-F7 unlabeled empty rooms
unl = [ph(1, "living", "vision"), ph(2, "bedrooms", "vision"), ph(3, "kitchen", "vision"), ph(4, "bathrooms", "vision"), ph(5, "outdoor", "vision")]
rr = ls.check_listing_scope(unl, ask=EMPTY)
check("F4 empty rooms whose category came from the classifier (no label) are stopped, even with enforcement off", (not rr["ok"]) and rr["code"] == "unlabeled_empty_rooms", rr)
lab = [ph(1, "living"), ph(2, "bedrooms"), ph(3, "kitchen"), ph(4, "bathrooms"), ph(5, "outdoor")]
rr = ls.check_listing_scope(lab, ask=EMPTY)
check("F5 empty rooms WITH labels from the page/partner stay feasible", rr["ok"] and rr["furnished_status"] == "unfurnished", rr)
rr = ls.check_listing_scope(unl, ask=FURN)
check("F6 furnished rooms without labels are fine", rr["ok"])
lab2 = [ph(1, "living", "vision", label="Soggiorno"), ph(2, "bedrooms", "vision", label="Camera"), ph(3, "kitchen"), ph(4, "bathrooms"), ph(5, "outdoor")]
rr = ls.check_listing_scope(lab2, ask=EMPTY)
check("F7 a page caption counts as a label even if the category passed through the classifier", rr["ok"], rr)
check("F8 short reason for notifications", ls.acceptance_short_reason({"code": "unlabeled_empty_rooms"}) == "stanze vuote senza etichette")
rep = ls.build_selection_report(photos, {"selected": {}, "total_selected": 0}, 6)
check("F9 selection report carries photo_audit and excluded_counts", len(rep["photo_audit"]) == 7 and rep["excluded_counts"] == ex)
check("F10 the illustration check covers up to 60 photos", ls.MAX_SOURCE_CHECK == 60)
ex2 = ls.exclusion_counts([ph(1, "uncategorized", "vision", other_kind="floorplan"), ph(2, "uncategorized", "vision", other_kind="hall"), ph(3, "uncategorized", "vision")])
check("F11 'other' photos are counted by what they are (piantina / ingresso) when known", ex2 == {"piantina": 1, "ingresso o corridoio": 1, "ambiente non riconosciuto": 1}, ex2)
def fake_word(url, fb, prompt):
    if prompt == ls._VISION_CLASSIFY_PROMPT:
        return ("other", True)
    if prompt == ls._VISION_OTHER_PROMPT:
        return (("floorplan" if url == "p1" else "banana"), True)
    return ("x", True)
ls._vision_one_word = fake_word
res = ls.resolve_uncategorized_photos([{"url": "p1", "category": "uncategorized"}, {"url": "p2", "category": "uncategorized"}, {"url": "k", "category": "living"}])
check("F12 resolve_uncategorized_photos records the kind of an 'other' photo and ignores an unknown word", res[0].get("other_kind") == "floorplan" and "other_kind" not in res[1] and res[2]["category"] == "living", res)
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
