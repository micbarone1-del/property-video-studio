import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as ls
F = 0
def chk(n, c, info=""):
    global F
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); F += (not c)

ANS = {"park": "parking", "sky": "aerial", "bad": "banana", "boom": None}
def fake(url, fb, prompt, words=1):
    assert prompt == ls._VISION_DESCRIBE_PROMPT
    if ANS.get(url, "?") is None:
        return ("", False)
    return (ANS.get(url, "other") + " photo", True)
ls._vision_one_word = fake
ls._describe_cache.clear()

def other(url):
    return {"url": url, "category": "uncategorized"}
ph = [other("park"), other("sky"), other("bad"), other("boom"), {"url": "ok", "category": "living"}]
ls.resolve_uncategorized_photos(ph)
chk("K1 'what is it' comes from the one answer: parking and aerial get a kind, unknown word / failed call / usable photo do not", ph[0].get("other_kind") == "parking" and ph[1].get("other_kind") == "aerial" and "other_kind" not in ph[2] and "other_kind" not in ph[3] and "other_kind" not in ph[4], ph)
chk("K2 a parking lot is reported as parking", ls.photo_exclusion(ph[0]) == "parcheggio", ls.photo_exclusion(ph[0]))
chk("K3 a really aerial photo is reported as aerial", ls.photo_exclusion(ph[1]) == "vista aerea o dall'alto", ls.photo_exclusion(ph[1]))
chk("K4 unknown word and failed call: 'ambiente non riconosciuto'", ls.photo_exclusion(ph[2]) == ls.photo_exclusion(ph[3]) == "ambiente non riconosciuto")
chk("K5 these photos are excluded", all(ls.photo_exclusion(p) for p in ph[:4]))
chk("K6 a usable photo is untouched", ls.photo_exclusion(ph[4]) is None)
CALLS = []
ls._describe_cache.clear()
ls._vision_one_word = lambda url, fb, prompt, words=1: (CALLS.append(url) or ("other photo", True))
a1 = {"url": "x1", "category": "uncategorized"}
ls.resolve_uncategorized_photos([a1])
ls._classify_photo_vision("x1"); ls._other_kind("x1"); ls._photo_source("x1"); ls._is_hall_photo("x1")
chk("K7 ONE question per photo: classify + kind + source + hall are all read from the same answer", CALLS == ["x1"], CALLS)
chk("K8 relabel_aerial_excluded is gone (it was a second question)", not hasattr(ls, "relabel_aerial_excluded"))
ex = ls.exclusion_counts([{"url": "a", "category": "uncategorized", "category_source": "vision", "other_kind": "emptyroom"},
                          {"url": "b", "category": "uncategorized", "category_source": "vision", "other_kind": "storage"},
                          {"url": "c", "category": "uncategorized", "category_source": "vision", "other_kind": "cellar"}])
chk("K9 empty room, storage room and cellar have their own labels", ex == {"stanza vuota senza etichetta": 1, "ripostiglio": 1, "cantina o seminterrato": 1}, ex)
chk("K10 every kind the prompt can return has an Italian label", all(k in ls.OTHER_KINDS_IT for k in ("hall","stairs","floorplan","shared","parking","emptyroom","storage","closet","cellar","aerial","detail")))
chk("K11 the one prompt lists every kind", all(k + ":" in ls._VISION_DESCRIBE_PROMPT for k in ls.OTHER_KINDS_IT) and all(k in ls.DESCRIBE_WHAT for k in ls.OTHER_KINDS_IT))
print("FAILS", F); sys.exit(1 if F else 0)
