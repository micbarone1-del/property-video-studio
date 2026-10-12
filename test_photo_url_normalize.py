"""3A-bis (2026-10-12): truncated photo URLs are normalised. No network, no API key."""
import os, sys, types, json
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

n = ls.normalize_photo_url
check("N1 truncated URL with trailing slash -> m-c.jpg", n("https://pwm.im-cdn.it/image/1963262752/") == "https://pwm.im-cdn.it/image/1963262752/m-c.jpg")
check("N2 truncated URL without trailing slash -> m-c.jpg", n("https://pwm.im-cdn.it/image/1963262752") == "https://pwm.im-cdn.it/image/1963262752/m-c.jpg")
for good in ("https://pwm.im-cdn.it/image/2025963124/xl-c.jpg", "https://pwm.im-cdn.it/image/2025963124/m-c.jpg", "https://pwm.im-cdn.it/image/2025963124/xl.jpg"):
    check("N3 complete URL unchanged: " + good[-12:], n(good) == good)
check("N4 other site unchanged", n("https://example.com/photos/abc.jpg") == "https://example.com/photos/abc.jpg")
check("N5 URL with query string unchanged", n("https://pwm.im-cdn.it/image/123/?x=1") == "https://pwm.im-cdn.it/image/123/?x=1")
check("N6 empty/None safe", n("") == "" and n(None) is None)

data = {"photos": [{"url": "https://pwm.im-cdn.it/image/1963262752/", "label_it": "Camera", "category": "bedrooms"},
                   {"url": "https://pwm.im-cdn.it/image/2025963124/m-c.jpg", "label_it": "Cucina", "category": "kitchen"}],
        "description": "d", "price": "1", "address": "a"}
class Msgs:
    def create(self, **kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(data))], stop_reason="end_turn")
class FakeClient:
    def __init__(self, api_key=None): self.messages = Msgs()
ls.anthropic.Anthropic = FakeClient
ls._track_claude = lambda r: r
ls.try_upgrade_resolution = lambda u: {"url": u.replace("/m-c.jpg", "/xl-c.jpg"), "upgraded": u.endswith("/m-c.jpg")}
ex = ls.extract_listing("https://www.immobiliare.it/annunci/1/")
p0, p1 = ex["photos"]
check("N7 extract_listing: truncated URL becomes upgraded xl-c.jpg, original_url is the canonical m-c.jpg",
      ex["ok"] and p0["url"].endswith("/image/1963262752/xl-c.jpg") and p0["original_url"].endswith("/image/1963262752/m-c.jpg"), p0)
check("N8 extract_listing: complete URL still upgraded as before", p1["url"].endswith("/xl-c.jpg") and p1["original_url"].endswith("/m-c.jpg"), p1)
ex2 = ls.extract_listing("https://www.immobiliare.it/annunci/1/", attempt_resolution_upgrade=False)
check("N9 normalisation also runs when the upgrade is switched off", ex2["photos"][0]["url"].endswith("/m-c.jpg"), ex2["photos"][0])

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
