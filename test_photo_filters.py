"""2026-10-29: photo filters. Size check at download, Claude-vision quality check (measure-only by default, optional drop),
watermark flag per origin. No network, no API key. Run: python3 test_photo_filters.py"""
import base64, io, os, re, sys, tempfile, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls
from pathlib import Path
from PIL import Image

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def jpeg(w=1200, h=675, colour=(120, 130, 140)):
    b = io.BytesIO(); Image.new("RGB", (w, h), colour).save(b, "JPEG"); return b.getvalue()

# ── size check ──────────────────────────────────────────────────────────────
check("U1 a 4x2 file (job bd3f0f77) is not usable", not ls.photo_usability(jpeg(4, 2))["ok"])
check("U2 a 486x273 thumbnail is not usable and the reason names the size", not ls.photo_usability(jpeg(486, 273))["ok"] and "486x273" in ls.photo_usability(jpeg(486, 273))["reason"])
check("U3 1024x576 (the smallest real photo seen) is usable", ls.photo_usability(jpeg(1024, 576))["ok"])
check("U4 a portrait photo is judged on its long side: 600x900 usable", ls.photo_usability(jpeg(600, 900))["ok"])
check("U5 bytes that are not an image are not usable, no exception", not ls.photo_usability(b"<html>404</html>")["ok"])
check("U6 the smallest accepted long side is the constant", ls.photo_usability(jpeg(ls.MIN_PHOTO_LONG_SIDE, 400))["ok"] and not ls.photo_usability(jpeg(ls.MIN_PHOTO_LONG_SIDE - 1, 400))["ok"])

FETCHES = {}
CONTENT = {}
def fake_fetch(url, fallback_url=None, timeout=20, attempts=1):
    FETCHES[url] = FETCHES.get(url, 0) + 1
    if CONTENT.get(url) == "fail":
        return {"ok": False, "content": None, "url_used": None, "used_fallback": False, "error": "download failed: 503"}
    return {"ok": True, "content": CONTENT.get(url, jpeg()), "url_used": url, "used_fallback": False, "error": None}
ls.fetch_photo_bytes = fake_fetch

with tempfile.TemporaryDirectory() as d:
    CONTENT["tiny"] = jpeg(4, 2)
    r = ls.download_photo("tiny", Path(d), "x_00")
    check("D1 a tiny photo: not ok, flagged unusable, no file written", (not r["ok"]) and r.get("unusable") and not (Path(d) / "x_00.jpg").exists(), r)
    r = ls.download_photo("good", Path(d), "y_00")
    check("D2 a good photo is written", r["ok"] and (Path(d) / "y_00.jpg").exists() and not r.get("unusable"), r)

sleeps = []
ls.time.sleep = lambda s: sleeps.append(s)
with tempfile.TemporaryDirectory() as d:
    FETCHES.clear(); CONTENT.clear(); CONTENT["tiny"] = jpeg(486, 273)
    sel = {"selected": {"living": [{"url": "a"}, {"url": "tiny"}], "kitchen": [{"url": "k"}]}, "gaps": []}
    out = ls.download_selected_photos(sel, Path(d))
    check("D3 the unusable photo is dropped, the others kept in order", [p["url"] for p in out["selected"]["living"]] == ["a"] and len(out["selected"]["kitchen"]) == 1, out["selected"])
    check("D4 it is reported in download_failures with the reason and the unusable mark",
          len(out["download_failures"]) == 1 and out["download_failures"][0].get("unusable") and "486x273" in out["download_failures"][0]["error"], out["download_failures"])
    check("D5 it is fetched ONCE and no retry wait happens (the file itself is the problem)", FETCHES["tiny"] == 1 and sleeps == [], (FETCHES, sleeps))
with tempfile.TemporaryDirectory() as d:
    FETCHES.clear(); CONTENT.clear(); CONTENT["bad"] = "fail"; sleeps.clear()
    sel = {"selected": {"living": [{"url": "bad"}]}, "gaps": []}
    out = ls.download_selected_photos(sel, Path(d))
    check("D6 a real download failure is still retried in rounds (old behaviour unchanged)", FETCHES["bad"] == len(ls.DOWNLOAD_RETRY_WAITS) + 1 and len(sleeps) == len(ls.DOWNLOAD_RETRY_WAITS) and not out["download_failures"][0].get("unusable"), (FETCHES, sleeps))

# ── quality prompt in the existing ranking ──────────────────────────────────
check("P1 the ranking prompt now also penalises blur, blocks and a watermark over the subject",
      "Technical quality" in ls.QUALITY_RANKING_PROMPT and "watermark" in ls.QUALITY_RANKING_PROMPT and "blocky" in ls.QUALITY_RANKING_PROMPT)

# ── vision quality verdict through the real sender ──────────────────────────
SENT = []; ANSWER = {"text": "ok", "raise": False}
ls._track_claude = lambda r: r
class Msgs:
    def create(self, **kw):
        content = kw["messages"][0]["content"]
        SENT.append([c for c in content if c.get("type") == "image"])
        SENT_PROMPT.append(content[0]["text"])
        if ANSWER["raise"]: raise RuntimeError("api down")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=ANSWER["text"])])
SENT_PROMPT = []
class FakeClient:
    def __init__(self, api_key=None): self.messages = Msgs()
ls.anthropic.Anthropic = FakeClient

ANSWER.update(text="Blocky."); SENT.clear()
v = ls.assess_photo_quality(jpeg(2000, 1500), "t")
check("Q1 reply 'Blocky.' -> verdict blocky, call ok", v == {"verdict": "blocky", "call_ok": True}, v)
check("Q2 two images are sent: the whole photo and a crop", len(SENT[0]) == 2, len(SENT))
crop = Image.open(io.BytesIO(base64.b64decode(SENT[0][1]["source"]["data"])))
whole = Image.open(io.BytesIO(base64.b64decode(SENT[0][0]["source"]["data"])))
check("Q3 the second image is a 768x768 crop at the REAL pixels (not scaled); the first is the scaled whole photo", crop.size == (768, 768) and max(whole.size) == 768, (crop.size, whole.size))
ANSWER.update(text="great")
check("Q4 an answer outside the four words is 'unknown', never a problem", ls.assess_photo_quality(jpeg())["verdict"] == "unknown")
ANSWER.update(raise_=True); ANSWER["raise"] = True
check("Q5 API error -> unknown, call_ok False, no exception", ls.assess_photo_quality(jpeg()) == {"verdict": "unknown", "call_ok": False})
ANSWER["raise"] = False
check("Q6 the prompt asks for ONE of ok/soft/blocky/watermark", "ok, soft, blocky or watermark" in SENT_PROMPT[0])

def selection_of(d, verdicts):
    sel = {"selected": {}, "gaps": []}
    for i, v in enumerate(verdicts):
        cat = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor", "living"][i % 7]
        f = Path(d) / f"p{i}.jpg"; f.write_bytes(jpeg())
        sel["selected"].setdefault(cat, []).append({"url": f"u{i}", "local_path": str(f), "verdict": v})
    return sel
def assessor(content, label=""):
    return {"verdict": CUR[0].pop(0), "call_ok": True}
CUR = [[]]
os.environ.pop("PVS_QUALITY_CHECK", None); os.environ.pop("PVS_QUALITY_ENFORCE", None)
with tempfile.TemporaryDirectory() as d:
    sel = selection_of(d, ["ok"] * 6)
    verdicts = ["ok", "blocky", "ok", "watermark", "ok", "unknown"]
    CUR[0] = list(verdicts)
    # serial order of ex.map follows item order: items are built category by category, so map them back through the order
    order = [(c, i) for c, ps in sel["selected"].items() for i, _ in enumerate(ps)]
    by_item = {k: v for k, v in zip(order, verdicts)}
    def assess_by_item(content, label=""):
        cat, i = re.match(r"(\w+)\[(\d+)\]", label).groups()
        return {"verdict": by_item[(cat, int(i))], "call_ok": True}
    s = ls.check_selected_photo_quality(sel, assess=assess_by_item)
    n_left = sum(len(v) for v in sel["selected"].values())
    check("Q7 default is measure-only: every photo stays", n_left == 6 and not s["enforced"] and s["dropped"] == 0, s)
    check("Q8 summary counts: 6 checked, 3 ok, 1 unknown, 2 poor with their verdicts",
          s["checked"] == 6 and s["ok"] == 3 and s["unknown"] == 1 and sorted(x["verdict"] for x in s["poor"]) == ["blocky", "watermark"], s)
    check("Q9 every photo is tagged with its verdict", all("quality" in p for ps in sel["selected"].values() for p in ps))
with tempfile.TemporaryDirectory() as d:
    sel = selection_of(d, ["ok"] * 6)
    order = [(c, i) for c, ps in sel["selected"].items() for i, _ in enumerate(ps)]
    by_item = {k: v for k, v in zip(order, ["ok", "blocky", "ok", "watermark", "ok", "ok"])}
    s = ls.check_selected_photo_quality(sel, assess=assess_by_item, enforce=True)
    n_left = sum(len(v) for v in sel["selected"].values())
    check("Q10 enforcing: one poor photo is dropped, the second is kept because 5 is the minimum", n_left == 5 and s["dropped"] == 1 and s["kept_for_count"] == 1 and len(sel["quality_rejected"]) == 1, s)
with tempfile.TemporaryDirectory() as d:
    sel = selection_of(d, ["ok"] * 7)
    order = [(c, i) for c, ps in sel["selected"].items() for i, _ in enumerate(ps)]
    by_item = {k: v for k, v in zip(order, ["blocky", "ok", "ok", "ok", "ok", "ok", "ok"])}
    s = ls.check_selected_photo_quality(sel, assess=assess_by_item, enforce=True)
    check("Q11 with 7 photos a poor one is dropped and 6 remain", sum(len(v) for v in sel["selected"].values()) == 6 and s["dropped"] == 1, s)
os.environ["PVS_QUALITY_CHECK"] = "0"
check("Q12 PVS_QUALITY_CHECK=0 switches the check off, nothing is called", ls.check_selected_photo_quality({"selected": {}}, assess=lambda *a, **k: 1 / 0) == {"enabled": False})
os.environ.pop("PVS_QUALITY_CHECK")
with tempfile.TemporaryDirectory() as d:
    sel = selection_of(d, ["ok"] * 3)
    s = ls.check_selected_photo_quality(sel, assess=lambda c, label="": 1 / 0)
    check("Q13 an assessor that crashes gives 'unknown' for every photo, never an exception", s["unknown"] == 3 and s["poor"] == [], s)
check("Q14 enforcing is off unless PVS_QUALITY_ENFORCE is set", not ls.photo_quality_enforce_enabled())
os.environ["PVS_QUALITY_ENFORCE"] = "1"
check("Q15 PVS_QUALITY_ENFORCE=1 turns it on", ls.photo_quality_enforce_enabled())
os.environ.pop("PVS_QUALITY_ENFORCE")

# the shared sender is still the only place that calls the API: the old one-photo function goes through it
ANSWER.update(text="hall"); SENT.clear()
check("Q16 _vision_one_word (room questions) still works through the same sender", ls._vision_one_word("u", None, "q") == ("hall", True) and len(SENT[0]) == 1)

# ── watermark flag per origin ───────────────────────────────────────────────
sel = {"selected": {"exterior": [{"local_path": "a"}], "living": [{"local_path": "b"}]}}
check("R1 standard builder: watermark removal True by default (a scraped listing)", all(s["remove_watermark"] is True for s in ls.build_standard_video_scenes_config(sel, {}, 5)))
check("R2 standard builder: remove_watermark=False gives False on every scene (partner API)", all(s["remove_watermark"] is False for s in ls.build_standard_video_scenes_config(sel, {}, 5, remove_watermark=False)))
psel = {"selected": {"exterior": [{"local_path": "a"}], "living": [{"local_path": "b"}]}}
check("R3 premium builder follows the same parameter", all(s["remove_watermark"] is False for s in ls.build_premium_video_scenes_config(psel, {}, 5, remove_watermark=False))
      and all(s["remove_watermark"] is True for s in ls.build_premium_video_scenes_config(psel, {}, 5)))
api = open("api_server.py").read()
calls = re.findall(r"scraper\.build_standard_video_scenes_config\((.*?)\)\s*\n", api, re.S)
check("R4 api_server: exactly one call passes remove_watermark=False (the partner path) and it is the one under the Relinx job",
      sum("remove_watermark=False" in c for c in calls) == 1, calls)
partner_pos = api.index("remove_watermark=False")
check("R5 that call sits after the partner download and before the partner webhook failure text (inside the partner job preparation)",
      api.rfind("async def ", 0, partner_pos) != -1 and "partner" in api[api.rfind("async def ", 0, partner_pos):partner_pos].lower())
check("R6 both workflows call the shared quality check once, right after the download",
      api.count("scraper.check_selected_photo_quality") == 2 and api.count("selection_report[\"photo_quality\"]") == 2)

print()
print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
