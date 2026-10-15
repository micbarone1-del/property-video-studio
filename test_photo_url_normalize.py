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

# ── 2026-10-15: annunci.getrix.it support (relative photo paths, _th -> _hd) ─────────────────────────
check("G1 getrix listing domain is supported", ls.is_supported_domain("https://annunci.getrix.it/annuncio.asp?id=6CD4AA7D-3CAD-4855-9A5F-A97FCEA10910"))
check("G2 other unknown sites are still refused", not ls.is_supported_domain("https://www.example-portal.it/annuncio/1"))
check("G3 upgrade table has _th -> _hd", (r"_th\.jpg$", "_hd.jpg") in ls._RESOLUTION_UPGRADE_PATTERNS)
import importlib
ls = importlib.reload(ls)
ls.anthropic.Anthropic = FakeClient
ls._track_claude = lambda r: r
data["photos"] = [{"url": "/foto/7039/2592173963_th.jpg", "label_it": "", "category": "uncategorized"},
                  {"url": "//annunci.getrix.it/foto/7039/2592173962.jpg", "label_it": "", "category": "uncategorized"},
                  {"url": "https://pwm.im-cdn.it/image/2025963124/m-c.jpg", "label_it": "Cucina", "category": "kitchen"}]
heads = []
class R200:
    status_code = 200
def fake_head(u, timeout=5):
    heads.append(u); return R200()
ls.requests.head = fake_head
ex = ls.extract_listing("https://annunci.getrix.it/annuncio.asp?id=6CD4AA7D")
q = ex["photos"]
check("G4 relative path becomes absolute and is upgraded to _hd", ex["ok"] and q[0]["url"] == "https://annunci.getrix.it/foto/7039/2592173963_hd.jpg" and q[0]["original_url"] == "https://annunci.getrix.it/foto/7039/2592173963_th.jpg", q[0])
check("G5 protocol-relative path becomes https", q[1]["url"] == "https://annunci.getrix.it/foto/7039/2592173962.jpg", q[1])
check("G6 immobiliare absolute URL unaffected by the join", q[2]["original_url"] == "https://pwm.im-cdn.it/image/2025963124/m-c.jpg", q[2])
check("G7 the _hd candidate was verified with a HEAD request", "https://annunci.getrix.it/foto/7039/2592173963_hd.jpg" in heads, heads)

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
