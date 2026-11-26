import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules: sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as ls
F = 0
def check(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)
ls.fetch_photo_bytes = lambda *a, **k: {"ok": True, "content": b"x"}
V = {"u1": ("ok", "portal"), "u2": ("ok", "agency"), "u3": ("ok", "none"), "u4": ("soft", "none"), "u5": ("ok", "portal")}
def assess(content, label=""): return {"verdict": "ok", "overlay": "none", "call_ok": True}
cur = {}
def mk(url, rej):
    p = {"url": url, "category": "living"}
    if rej: p["reject_overlay"] = True
    return p
class A:
    def __call__(self, content, label=""):
        return {"verdict": V[cur["u"]][0], "overlay": V[cur["u"]][1], "call_ok": True}
# fetch returns url-specific so assess knows which
def fetch(url, orig=None, timeout=15):
    cur["u"] = url; return {"ok": True, "content": b"x"}
ls.fetch_photo_bytes = fetch
os.environ["PVS_QUALITY_CHECK"] = "1"
allp = [mk("u1", True), mk("u2", True), mk("u4", True), mk("u3", True), mk("u5", False)]
allp[4]["category"] = "kitchen"
bc = {"living": allp[:4], "kitchen": [allp[4]]}
ls.filter_poor_quality_candidates(bc, assess=A(), enforce=True)
by = {p["url"]: p for p in allp}
# 2026-11-26: the Haiku overlay word is a LABEL only; the exclusion is decided by the one vision answer ("marked")
check("rejected (soft) ones leave the pool, overlay-labelled ones stay", sorted(p["url"] for p in bc["living"]) == ["u1", "u2", "u3"])
check("Haiku portal / agency word is only a label (never an exclusion)", not by["u1"].get("overlay_rejected") and not by["u2"].get("overlay_rejected") and by["u1"]["overlay"] == "portal" and ls.photo_exclusion(by["u1"]) is None)
check("clean photo kept", ls.photo_exclusion(by["u3"]) is None)
check("soft photo keeps the quality reason", ls.photo_exclusion(by["u4"]) == "scarsa qualità")
check("URL job: watermark only labelled", not by["u5"].get("overlay_rejected") and by["u5"]["overlay"] == "portal" and ls.photo_exclusion(by["u5"]) is None)
# the decision: refine_exterior_outdoor_with_vision reads the ONE answer (what, source, ok); source "marked" = overlay laid over the photo
T = {"m1": ("kitchen", "marked", True), "m2": ("living", "marked", True), "c1": ("living", "photo", True), "n1": ("kitchen", "photo", True)}
ls._describe_photo = lambda url, fb=None: T[url]
ls._describe_cache.clear()
mk2 = lambda url, cat, rej: {"url": url, "category": cat, "reject_overlay": True} if rej else {"url": url, "category": cat}
ph = [mk2("m1", "kitchen", True), mk2("m2", "living", False), mk2("c1", "living", True), mk2("n1", "kitchen", True)]
summ = ls.refine_exterior_outdoor_with_vision(ph)
q = {p["url"]: p for p in ph}
check("partner job: a marked photo is excluded with the overlay reason", q["m1"].get("overlay_rejected") and ls.photo_exclusion(q["m1"]) == "watermark o logo sulla foto")
check("partner job: its category is untouched (it only leaves the usable photos)", q["m1"]["category"] == "kitchen")
check("URL job: a marked photo is only labelled", q["m2"].get("overlay_vision") == "marked" and not q["m2"].get("overlay_rejected") and ls.photo_exclusion(q["m2"]) is None)
check("a plain photo (wall notice answered photo) stays usable", ls.photo_exclusion(q["c1"]) is None and ls.photo_exclusion(q["n1"]) is None)
check("summary counts the overlay removals", summ.get("overlay_removed") == 1)
check("the vision prompt defines marked and the notice exception", "marked:" in ls._VISION_DESCRIBE_PROMPT and "NOT marked" in ls._VISION_DESCRIBE_PROMPT)
check("vision side default 768", ls.VISION_MAX_SIDE == 768)
os.environ["PVS_VISION_MAX_SIDE"] = "1280"; check("vision side env 1280", ls._vision_side_from_env() == 1280)
os.environ["PVS_VISION_MAX_SIDE"] = "abc"; check("bad env falls back", ls._vision_side_from_env() == 768)
print("RESULT", "ALL PASS" if not F else f"{F} FAIL"); sys.exit(1 if F else 0)
