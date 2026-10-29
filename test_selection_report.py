"""3A (2026-10-12): shared photo fetch with fallback to the original URL, selection_report. No network, no API key."""
import os, sys, types, json, tempfile
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import requests
import listing_scraper as ls
from pathlib import Path

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

sleeps = []
ls.time.sleep = lambda s: sleeps.append(s)

import io as _io
from PIL import Image as _Image
def _real_jpeg(w=1200, h=675):
    _b = _io.BytesIO(); _Image.new("RGB", (w, h), (120, 130, 140)).save(_b, "JPEG"); return _b.getvalue()
REAL_JPEG = _real_jpeg()   # 2026-10-29: the download now refuses a file that is not a usable image (long side >= 800 px)

class Resp:
    def __init__(self, code, content=None):
        self.status_code = code; self.content = REAL_JPEG if content is None else content
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

def install_get(by_url):
    """by_url: url -> list of responses/exceptions served in order."""
    calls = []
    def fake_get(url, timeout=0):
        calls.append(url)
        x = by_url[url].pop(0)
        if isinstance(x, Exception): raise x
        return x
    ls.requests.get = fake_get
    sleeps.clear()
    return calls

# --- fetch_photo_bytes ---
calls = install_get({"U": [Resp(200)]})
r = ls.fetch_photo_bytes("U", "O")
check("F1 primary ok: one call, no fallback", r["ok"] and calls == ["U"] and not r["used_fallback"] and r["url_used"] == "U")
calls = install_get({"U": [Resp(403)], "O": [Resp(200)]})
r = ls.fetch_photo_bytes("U", "O")
check("F2 primary 403 -> falls back to original, ok", r["ok"] and calls == ["U", "O"] and r["used_fallback"] and r["url_used"] == "O", r)
calls = install_get({"U": [Resp(403)], "O": [Resp(404)]})
r = ls.fetch_photo_bytes("U", "O")
check("F3 both fail: not ok, error mentions both", (not r["ok"]) and "403" in r["error"] and "404" in r["error"] and "fallback" in r["error"], r)
calls = install_get({"U": [Resp(404)]})
r = ls.fetch_photo_bytes("U")
check("F4 no fallback, 404 permanent: one call", (not r["ok"]) and calls == ["U"] and not sleeps, r)
calls = install_get({"U": [requests.Timeout("a"), requests.Timeout("b"), requests.Timeout("c")], "O": [Resp(200)]})
r = ls.fetch_photo_bytes("U", "O", attempts=3)
check("F5 primary transient x3 then fallback ok (4 calls, 2 sleeps)", r["ok"] and len(calls) == 4 and len(sleeps) == 2 and r["used_fallback"], (r, calls))
calls = install_get({"U": [Resp(200)]})
r = ls.fetch_photo_bytes("U", "U")
check("F6 fallback identical to url is ignored", r["ok"] and calls == ["U"])

# --- download_photo ---
d = Path(tempfile.mkdtemp())
calls = install_get({"U": [Resp(403)], "O": [Resp(200, REAL_JPEG)]})
r = ls.download_photo("U", d, "p", "O")
check("D1 download_photo uses fallback and reports it", r["ok"] and r["used_fallback"] and r["url_used"] == "O" and (d / "p.jpg").read_bytes() == REAL_JPEG, r)
calls = install_get({"U": [Resp(403)], "O": [Resp(403)]})
d2 = Path(tempfile.mkdtemp())
r = ls.download_photo("U", d2, "p", "O")
check("D2 both fail: not ok, no file", (not r["ok"]) and not (d2 / "p.jpg").exists())
calls = install_get({"U": [Resp(200)]})
r = ls.download_photo("U", Path(tempfile.mkdtemp()), "p")
check("D3 old 3-argument call still works", r["ok"] and r["url_used"] == "U")

# --- download_selected_photos propagates original_url ---
sel = {"selected": {"living": [{"url": "U", "original_url": "O", "category": "living"}]}, "gaps": []}
calls = install_get({"U": [Resp(403)], "O": [Resp(200)]})
out = ls.download_selected_photos(sel, Path(tempfile.mkdtemp()))
p0 = out["selected"]["living"][0]
check("D4 download_selected_photos records url_used/used_fallback", p0["used_fallback"] and p0["url_used"] == "O" and not out["download_failures"], out)

# --- rank_photos_by_quality ---
class Msgs:
    def __init__(self, answer): self.answer = answer
    def create(self, **kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=self.answer)])
class FakeClient:
    answer = "[2, 1]"
    def __init__(self, api_key=None): self.messages = Msgs(FakeClient.answer)
ls.anthropic.Anthropic = FakeClient
ls._track_claude = lambda r: r
def photos2():
    return [{"url": "U1", "original_url": "O1", "category": "bedrooms"}, {"url": "U2", "original_url": "O2", "category": "bedrooms"}]
FakeClient.answer = "[2, 1]"
calls = install_get({"U1": [Resp(200)], "U2": [Resp(200)]})
res = ls.rank_photos_by_quality("bedrooms", photos2())
check("R1 ranking order applied and tagged", [p["url"] for p in res] == ["U2", "U1"] and res[0]["rank_status"] == "ranked" and res[0]["rank_position"] == 1, res)
calls = install_get({"U1": [Resp(403)], "O1": [Resp(200)], "U2": [Resp(200)]})
res = ls.rank_photos_by_quality("bedrooms", photos2())
check("R2 upgraded URL 403 but original ok -> ranking still works (the Pinciano case)", res[0]["rank_status"] == "ranked" and [p["url"] for p in res] == ["U2", "U1"], res)
calls = install_get({"U1": [Resp(403)], "O1": [Resp(403)], "U2": [Resp(200)]})
res = ls.rank_photos_by_quality("bedrooms", photos2())
check("R3 both URLs fail -> original order, status says why", [p["url"] for p in res] == ["U1", "U2"] and res[0]["rank_status"].startswith("fallback_original_order"), res)
FakeClient.answer = "no idea"
calls = install_get({"U1": [Resp(200)], "U2": [Resp(200)]})
res = ls.rank_photos_by_quality("bedrooms", photos2())
check("R4 unparseable model reply -> original order, tagged", res[0]["rank_status"].startswith("fallback_original_order"), res)
res = ls.rank_photos_by_quality("bedrooms", [{"url": "U1", "category": "bedrooms"}])
check("R5 single candidate tagged, no fetch", res[0]["rank_status"] == "single_candidate")
FakeClient.answer = "[2, 1]"

# --- classify_uncategorized_photo ---
FakeClient.answer = "kitchen"
calls = install_get({"U": [Resp(403)], "O": [Resp(200)]})
check("C1 classify falls back to original URL", ls.classify_uncategorized_photo("U", "O") == "kitchen" and calls == ["U", "O"])
calls = install_get({"U": [Resp(403)], "O": [Resp(403)]})
check("C2 classify returns uncategorized when both fail", ls.classify_uncategorized_photo("U", "O") == "uncategorized")
calls = install_get({"U": [Resp(200)]})
ph = [{"url": "U", "category": "uncategorized", "original_url": None}]
check("C3 resolve_uncategorized_photos still works without original_url", ls.resolve_uncategorized_photos(ph)[0]["category"] == "kitchen")

# --- extract_listing keeps original_url ---
data = {"photos": [{"url": "http://cdn/x/m-c.jpg", "label_it": "Cucina", "category": "kitchen"}], "description": "d", "price": "1", "address": "a"}
class Msgs2:
    def create(self, **kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(data))], stop_reason="end_turn")
class FakeClient2:
    def __init__(self, api_key=None): self.messages = Msgs2()
ls.anthropic.Anthropic = FakeClient2
ls.try_upgrade_resolution = lambda u: {"url": u.replace("m-c", "xl-c"), "upgraded": True}
ex = ls.extract_listing("https://www.immobiliare.it/annunci/1/")
p = ex["photos"][0]
check("E1 extract_listing stores original_url and the upgraded url", ex["ok"] and p["original_url"].endswith("m-c.jpg") and p["url"].endswith("xl-c.jpg"), ex)

# --- build_selection_report ---
photos = [
    {"url": "a1", "category": "living", "rank_status": "ranked", "rank_position": 1},
    {"url": "a2", "category": "living", "rank_status": "ranked", "rank_position": 2},
    {"url": "b1", "category": "kitchen", "rank_status": "single_candidate", "rank_position": 1, "resolution_upgraded": True},
    {"url": "c1", "category": "outdoor", "rank_status": "single_candidate", "rank_position": 1},
    {"url": "a1", "category": "living"},   # duplicate URL
]
selection = {"selected": {"living": [{"url": "a1", "original_url": "a1o", "url_used": "a1o", "used_fallback": True, "rank_position": 1, "rank_status": "ranked", "local_path": "/x"}],
                          "kitchen": [{"url": "b1", "url_used": "b1", "used_fallback": False, "resolution_upgraded": True}]},
             "gaps": [], "total_selected": 2, "download_failures": [{"category": "outdoor", "url": "c1", "error": "download failed: 403"}]}
rep = ls.build_selection_report(photos, selection, 6)
check("S1 report is JSON-serialisable", bool(json.dumps(rep)))
check("S2 candidates counted without duplicates", rep["photos_total"] == 4 and rep["candidates_by_category"] == {"living": 2, "kitchen": 1, "outdoor": 1}, rep["candidates_by_category"])
check("S3 available-but-not-used category is listed", rep["categories_available_not_used"] == ["outdoor"] and rep["categories_used"] == ["living", "kitchen"], rep)
check("S4 download failure and fallback count recorded", rep["fallback_used_count"] == 1 and rep["download_failures"][0]["error"] == "download failed: 403")
check("S5 ranking status per category and upgrade count", rep["ranking_by_category"].get("living") == "ranked" and rep["resolution_upgraded_count"] == 1, rep["ranking_by_category"])
check("S6 report does not contain local file paths", "local_path" not in json.dumps(rep))
rep2 = ls.build_selection_report([{"url": "e1", "category": "outdoor"}], {"selected": {"outdoor_early": [{"url": "e1"}]}, "gaps": []}, 12, premium=True)
check("S7 premium pseudo-categories map back to outdoor", rep2["categories_used"] == ["outdoor"] and rep2["premium"] is True, rep2)

# --- api_server wiring (static) ---
src = open("api_server.py", encoding="utf-8").read()
check("W1 URL job stores selection_report and source_description", src.count('"selection_report": selection_report') == 2 and src.count('"source_description"') == 2)
check("W2 both workflows call build_selection_report", src.count("scraper.build_selection_report(") == 2)
check("W3 no direct requests.get on photo URLs left in listing_scraper outside the shared fetch",
      __import__("re").findall(r"=\s*requests\.get\(", open("listing_scraper.py", encoding="utf-8").read()).__len__() == 1)

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
