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
check("rejected ones leave the pool", [p["url"] for p in bc["living"]] == ["u3"])
check("portal watermark out in a partner job", by["u1"].get("overlay_rejected") and ls.photo_exclusion(by["u1"]) == "watermark o logo sulla foto")
check("agency logo out in a partner job", by["u2"].get("overlay_rejected"))
check("clean photo kept", ls.photo_exclusion(by["u3"]) is None)
check("soft photo keeps the quality reason", ls.photo_exclusion(by["u4"]) == "scarsa qualità")
check("URL job (no reject_overlay): watermark only labelled", not by["u5"].get("overlay_rejected") and by["u5"]["overlay"] == "portal" and ls.photo_exclusion(by["u5"]) is None)
check("vision side default 768", ls.VISION_MAX_SIDE == 768)
os.environ["PVS_VISION_MAX_SIDE"] = "1280"; check("vision side env 1280", ls._vision_side_from_env() == 1280)
os.environ["PVS_VISION_MAX_SIDE"] = "abc"; check("bad env falls back", ls._vision_side_from_env() == 768)
print("RESULT", "ALL PASS" if not F else f"{F} FAIL"); sys.exit(1 if F else 0)
