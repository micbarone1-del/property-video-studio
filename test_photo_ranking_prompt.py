"""2026-10-27: the photo ranking (shared by standard and premium selection) judges reflections, empty rooms (page description) and a safe far point. No network."""
import os, sys, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls

fails = []; total = 0
def check(name, cond):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

P = ls.QUALITY_RANKING_PROMPT
check("R1 prompt: bed only in a mirror does not count; empty rooms use the page description", "DIRECTLY visible" in P and "only as a reflection" in P and "page description" in P)
check("R2 prompt: big mirrors / glass are a penalty", "mirrored wardrobes" in P.lower() or "Mirrors, mirrored wardrobes" in P)
check("R3 prompt: a far central point of interest is a plus, a door / near object is weaker", "FAR from the camera" in P and "door is weaker" in P)
check("R4 prompt still formats", "bedroom" in P.format(category="bedroom", n=3))

sent = {}
class Msg:
    def __init__(self, t): self.content = [types.SimpleNamespace(type="text", text=t)]
class Client:
    def __init__(self, **k): self.messages = self
    def create(self, **k):
        sent["content"] = k["messages"][0]["content"]
        return Msg("[2, 1]")
ls.anthropic = types.SimpleNamespace(Anthropic=Client)
ls.fetch_photo_bytes = lambda url, orig=None, timeout=15: {"ok": True, "content": b"x"}
ls._track_claude = lambda r: r
cands = [{"url": "u1", "label_it": "Camera da letto con armadio"}, {"url": "u2", "label_it": ""}]
out = ls.rank_photos_by_quality("bedrooms", cands)
texts = [c["text"] for c in sent["content"] if c["type"] == "text"]
check("R5 the page description of each photo is sent with it", any("Photo 1: (page description: Camera da letto con armadio)" == t for t in texts) and "Photo 2:" in texts)
check("R6 ranking order applied, fail-open untouched", [p["url"] for p in out] == ["u2", "u1"])
ls.anthropic = types.SimpleNamespace(Anthropic=lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
out2 = ls.rank_photos_by_quality("bedrooms", cands)
check("R7 API failure -> original order, not an error", [p["url"] for p in out2] == ["u1", "u2"])

print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
