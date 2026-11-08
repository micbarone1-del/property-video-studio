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
# F4-F8 (2026-11-08): there is no separate "furnished" check any more; an empty room is a photo like any other
ls._describe_cache.clear()
def fw(url, fb, prompt, words=1):
    return ({"e1": "emptyroom photo", "e2": "emptyroom photo", "e3": "emptyroom photo", "e4": "emptyroom photo"}.get(url, "living photo"), True)
ls._vision_one_word = fw
unl = [ph(i, "uncategorized") for i in (1, 2)]
res = ls.resolve_uncategorized_photos([{"url": "e1", "category": "uncategorized"}, {"url": "u9", "category": "uncategorized"}])
check("F4 an unlabeled empty room is excluded as 'stanza vuota senza etichetta' (one answer, no second check)", res[0]["category"] == "uncategorized" and res[0].get("other_kind") == "emptyroom" and ls.photo_exclusion(res[0]) == "stanza vuota senza etichetta" and res[1]["category"] == "living", res)
lab = [ph(1, "living"), ph(2, "bedrooms"), ph(3, "kitchen"), ph(4, "bathrooms"), ph(5, "outdoor")]
rr = ls.check_listing_scope(lab)
check("F5 empty rooms WITH labels stay usable and the gate is the photo rule only", rr["ok"] and "furnished_status" not in rr, rr)
check("F6 the furnished functions are gone (no second description of the same photos)", not hasattr(ls, "check_listing_furnished") and not hasattr(ls, "_VISION_FURNISHED_PROMPT") and not hasattr(ls, "furnished_enforced"))
rr2 = ls.check_listing_scope([ph(1, "living")])
check("F7 the scope gate is the acceptance rule (same result)", (not rr2["ok"]) and rr2["code"] == "insufficient_photos")
check("F8 short reason for notifications", ls.acceptance_short_reason({"code": "insufficient_photos"}) == "foto insufficienti" and ls.acceptance_short_reason({"code": "x"}) == "non idoneo")
rep = ls.build_selection_report(photos, {"selected": {}, "total_selected": 0}, 6)
check("F9 selection report carries photo_audit and excluded_counts", len(rep["photo_audit"]) == 7 and rep["excluded_counts"] == ex)
check("F10 the illustration check covers up to 60 photos", ls.MAX_SOURCE_CHECK == 60)
ex2 = ls.exclusion_counts([ph(1, "uncategorized", "vision", other_kind="floorplan"), ph(2, "uncategorized", "vision", other_kind="hall"), ph(3, "uncategorized", "vision")])
check("F11 'other' photos are counted by what they are (piantina / ingresso) when known", ex2 == {"piantina": 1, "ingresso o corridoio": 1, "ambiente non riconosciuto": 1}, ex2)
def fake_word(url, fb, prompt, words=1):
    return ({"p1": "floorplan photo", "p2": "banana photo"}.get(url, "living photo"), True)
ls._vision_one_word = fake_word
ls._describe_cache.clear()
res = ls.resolve_uncategorized_photos([{"url": "p1", "category": "uncategorized"}, {"url": "p2", "category": "uncategorized"}, {"url": "k", "category": "living"}])
check("F12 resolve_uncategorized_photos records the kind of an 'other' photo and ignores an unknown word", res[0].get("other_kind") == "floorplan" and "other_kind" not in res[1] and res[2]["category"] == "living", res)
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
