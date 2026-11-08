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
def fake(url, fb, prompt):
    if prompt == ls._VISION_OTHER_PROMPT:
        if ANS.get(url, "?") is None:
            return ("", False)
        return (ANS.get(url, "other"), True)
    return ("x", True)
ls._vision_one_word = fake

def aerial(url):
    return {"url": url, "category": "uncategorized", "category_source": "vision_aerial", "category_page": "outdoor"}
ph = [aerial("park"), aerial("sky"), aerial("bad"), aerial("boom"), {"url": "ok", "category": "living"}]
n = ls.relabel_aerial_excluded(ph)
chk("K1 only the aerial-flagged photos with a known answer get a kind", n == 2 and ph[0].get("other_kind") == "parking" and ph[1].get("other_kind") == "aerial" and "other_kind" not in ph[2] and "other_kind" not in ph[3] and "other_kind" not in ph[4], ph)
chk("K2 a parking lot flagged aerial is reported as parking", ls.photo_exclusion(ph[0]) == "parcheggio", ls.photo_exclusion(ph[0]))
chk("K3 a really aerial photo keeps the aerial reason", ls.photo_exclusion(ph[1]) == "viste aeree o dall'alto", ls.photo_exclusion(ph[1]))
chk("K4 unknown word and failed call keep the aerial reason", ls.photo_exclusion(ph[2]) == ls.photo_exclusion(ph[3]) == "viste aeree o dall'alto")
chk("K5 relabelled photos are STILL excluded (audit only, nothing selected changes)", ph[0].get("category") == "uncategorized" and ls.photo_exclusion(ph[0]) is not None)
chk("K6 a usable photo is untouched", ls.photo_exclusion(ph[4]) is None)
CALLS = []
ls._vision_one_word = lambda url, fb, prompt: (CALLS.append(url) or ("other", True))
ls.relabel_aerial_excluded(ph)
chk("K7 a second run asks only about photos that still have no kind", sorted(CALLS) == ["bad", "boom"], CALLS)
ls._vision_one_word = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
chk("K8 never raises", ls.relabel_aerial_excluded([aerial("z")]) == 0)
ex = ls.exclusion_counts([{"url": "a", "category": "uncategorized", "category_source": "vision", "other_kind": "emptyroom"},
                          {"url": "b", "category": "uncategorized", "category_source": "vision", "other_kind": "storage"},
                          {"url": "c", "category": "uncategorized", "category_source": "vision", "other_kind": "cellar"}])
chk("K9 empty room, storage room and cellar have their own labels", ex == {"stanza vuota senza etichetta": 1, "ripostiglio": 1, "cantina o seminterrato": 1}, ex)
chk("K10 every kind the prompt can return has an Italian label", all(k in ls.OTHER_KINDS_IT for k in ("hall","stairs","floorplan","shared","parking","emptyroom","storage","closet","cellar","aerial","detail")))
chk("K11 the prompt lists every kind", all(k + ":" in ls._VISION_OTHER_PROMPT for k in ls.OTHER_KINDS_IT))
print("FAILS", F); sys.exit(1 if F else 0)
