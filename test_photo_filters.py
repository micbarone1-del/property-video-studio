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
check("U4 a portrait photo is judged on its long side: 700x1100 usable, 600x900 not", ls.photo_usability(jpeg(700, 1100))["ok"] and not ls.photo_usability(jpeg(600, 900))["ok"])
check("U5 bytes that are not an image are not usable, no exception", not ls.photo_usability(b"<html>404</html>")["ok"])
check("U6 the smallest accepted long side is the constant (1000: keeps 1024, the smallest real photo seen)", ls.photo_usability(jpeg(ls.MIN_PHOTO_LONG_SIDE, 400))["ok"] and not ls.photo_usability(jpeg(ls.MIN_PHOTO_LONG_SIDE - 1, 400))["ok"])

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
SENT = []; ANSWER = {"text": "ok", "raise": False, "per_model": {}, "raise_models": set()}
os.environ["PVS_BLOCKINESS_MAX"] = "0"      # pixel check off in the tests of the model judges (it has its own B section)
os.environ["PVS_QUALITY_MODELS"] = "judge-a"      # the single-judge tests below; the two-judge rules are tested in the E section
ls._track_claude = lambda r, model=None: r
class Msgs:
    def create(self, **kw):
        content = kw["messages"][0]["content"]
        SENT.append([c for c in content if c.get("type") == "image"])
        SENT_PROMPT.append(content[0]["text"]); MAXTOK.append(kw.get("max_tokens"))
        MODELS.append(kw.get("model"))
        if ANSWER["raise"] or kw.get("model") in ANSWER["raise_models"]: raise RuntimeError("api down")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=ANSWER["per_model"].get(kw.get("model"), ANSWER["text"]))])
SENT_PROMPT = []; MAXTOK = []; MODELS = []
class FakeClient:
    def __init__(self, api_key=None): self.messages = Msgs()
ls.anthropic.Anthropic = FakeClient

def core(r):
    return {k: v for k, v in r.items() if k not in ("by_model", "blockiness")}
ANSWER.update(text="ANSWER: blocky"); SENT.clear()
v = ls.assess_photo_quality(jpeg(2000, 1500), "t")
check("Q1 'ANSWER: blocky' (one word after the marker) -> verdict blocky, overlay unknown, call ok", core(v) == {"verdict": "blocky", "overlay": "unknown", "call_ok": True}, v)
ANSWER.update(text="Smooth and smeared at 100%.\nANSWER: Soft portal"); v2 = ls.assess_photo_quality(jpeg())
ANSWER.update(text="ANSWER: ok none."); v3 = ls.assess_photo_quality(jpeg())
ANSWER.update(text="Two sentences. I rate it ok at first.\nANSWER: ok none\nCorrection, final: ANSWER: Blocky, agency"); v4 = ls.assess_photo_quality(jpeg())
check("Q1b two-word answers: the technical verdict and the overlay are read separately", core(v2) == {"verdict": "soft", "overlay": "portal", "call_ok": True} and v3["verdict"] == "ok" and v3["overlay"] == "none" and v4["verdict"] == "blocky" and v4["overlay"] == "agency", (v2, v3, v4))
ANSWER.update(text="ANSWER: portal")
check("Q1c the old combined word 'portal' is NOT a technical verdict (unknown, never a problem)", ls.assess_photo_quality(jpeg())["verdict"] == "unknown")
ANSWER.update(text="soft portal")
check("Q1d no ANSWER line (bare words, or reasoning cut off): unknown, never a problem", ls.assess_photo_quality(jpeg())["verdict"] == "unknown")
ANSWER.update(text="")
check("Q1e a reply with no text at all (a model that only 'thought') -> unknown, call ok, no exception", core(ls.assess_photo_quality(jpeg())) == {"verdict": "unknown", "overlay": "unknown", "call_ok": True})
MAXTOK.clear(); ANSWER.update(text="ANSWER: ok none"); ls.assess_photo_quality(jpeg())
check("Q1f the judge call leaves room for reasoning (max_tokens 600)", MAXTOK == [600], MAXTOK)
ANSWER.update(text="ANSWER: blocky")
ANSWER.update(text="Blocky.")
check("Q2 two images are sent: the whole photo and a crop", len(SENT[0]) == 2, len(SENT))
crop = Image.open(io.BytesIO(base64.b64decode(SENT[0][1]["source"]["data"])))
whole = Image.open(io.BytesIO(base64.b64decode(SENT[0][0]["source"]["data"])))
check("Q3 the second image is a 768x768 crop at the REAL pixels (not scaled); the first is the scaled whole photo", crop.size == (768, 768) and max(whole.size) == 768, (crop.size, whole.size))
ANSWER.update(text="great")
check("Q4 an answer outside the four words is 'unknown', never a problem", ls.assess_photo_quality(jpeg())["verdict"] == "unknown")
ANSWER.update(raise_=True); ANSWER["raise"] = True
check("Q5 API error -> unknown, call_ok False, no exception", core(ls.assess_photo_quality(jpeg())) == {"verdict": "unknown", "call_ok": False})
ANSWER["raise"] = False
check("Q6 the prompt asks for two words: technical (ok/soft/blocky) then overlay (none/portal/agency), the technical one not influenced by the overlay", all(w in SENT_PROMPT[0] for w in ("TWO words", "FIRST word", "SECOND word", "- ok:", "- soft:", "- blocky:", "- none:", "- portal:", "- agency:", "never influenced by the second word", "ANSWER:", "at most two short sentences")))
check("Q6b only soft and blocky are poor: a portal watermark or an agency logo is never a reason to discard", ls.PHOTO_QUALITY_POOR == ("soft", "blocky") and set(ls.PHOTO_QUALITY_WORDS) == {"ok", "soft", "blocky"} and set(ls.PHOTO_OVERLAY_WORDS) == {"none", "portal", "agency"})

# ── two judge models: poor when ANY says so (2026-10-29) ─────────────────────
def run_two(a_text, b_text, raise_models=(), unset=False):
    os.environ["PVS_QUALITY_MODELS"] = "judge-a,judge-b"
    ANSWER["per_model"] = {"judge-a": a_text, "judge-b": b_text}; ANSWER["raise_models"] = set(raise_models)
    MODELS.clear(); MAXTOK.clear()
    r = ls.assess_photo_quality(jpeg())
    ANSWER["per_model"] = {}; ANSWER["raise_models"] = set()
    return r
os.environ.pop("PVS_QUALITY_MODELS")
check("E1 default judges: the default model and claude-haiku-5-5", ls.photo_quality_models() == (ls.MODEL, "claude-haiku-5-5"), ls.photo_quality_models())
os.environ["PVS_QUALITY_MODELS"] = " x , y "
check("E2 PVS_QUALITY_MODELS overrides the list (spaces ignored); one name = one judge", ls.photo_quality_models() == ("x", "y"))
r = run_two("ANSWER: ok none", "ANSWER: ok none")
check("E3 both ok -> ok, per-model verdicts kept, one request per model with its own model name and the same token room", r["verdict"] == "ok" and r["by_model"] == {"judge-a": "ok", "judge-b": "ok"} and MODELS == ["judge-a", "judge-b"] and MAXTOK == [600, 600], (r, MODELS))
r = run_two("ANSWER: ok none", "ANSWER: soft none")
check("E4 one judge says soft, the other ok -> soft (the photo is poor when ANY judge says so)", r["verdict"] == "soft" and r["by_model"] == {"judge-a": "ok", "judge-b": "soft"}, r)
r = run_two("ANSWER: blocky none", "ANSWER: soft none")
check("E5 both see a problem, different words -> the first judge's word", r["verdict"] == "blocky", r)
r = run_two("ANSWER: ok none", "x", raise_models={"judge-b"})
check("E6a the second judge's call fails -> the first judge decides, call ok, the broken one is ignored", r["verdict"] == "ok" and r["call_ok"] and r["by_model"] == {"judge-a": "ok"}, r)
r = run_two("x", "ANSWER: soft none", raise_models={"judge-a"})
check("E6b the first judge's call fails -> the second decides (soft)", r["verdict"] == "soft" and r["call_ok"], r)
r = run_two("x", "x", raise_models={"judge-a", "judge-b"})
check("E7 both calls fail -> unknown, call_ok False, no by_model", core(r) == {"verdict": "unknown", "call_ok": False} and "by_model" not in r, r)
r = run_two("no answer line here", "ANSWER: ok none")
check("E8a one answers without an ANSWER line (unknown), the other ok -> ok", r["verdict"] == "ok", r)
r = run_two("no answer line", "also none")
check("E8b nobody gives a usable answer -> unknown, call ok, never a problem", r["verdict"] == "unknown" and r["call_ok"] and r["overlay"] == "unknown", r)
r = run_two("ANSWER: ok", "ANSWER: ok portal")
check("E9 the overlay comes from the first judge that gave one", r["overlay"] == "portal", r)
r = run_two("ANSWER: ok agency", "ANSWER: ok portal")
check("E10 two overlays: the first judge's wins", r["overlay"] == "agency", r)
rr = ls.assess_photo_quality(jpeg(), models=("only-this",))
check("E11 models= argument overrides the setting for one call", MODELS[-1] == "only-this", MODELS)
os.environ["PVS_QUALITY_MODELS"] = "judge-a"

# ── free pixel check for JPEG blocks (2026-10-29) ────────────────────────────
import numpy as np
from PIL import ImageFilter
_rng = np.random.RandomState(3)
_base = Image.fromarray(_rng.randint(0, 255, (180, 320, 3), dtype=np.uint8)).resize((1440, 810), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
_photo = Image.fromarray(np.clip(np.asarray(_base).astype(np.float32) + _rng.normal(0, 4, (810, 1440, 3)), 0, 255).astype(np.uint8))
def jq(img, q):
    b = io.BytesIO(); img.save(b, "JPEG", quality=q); return b.getvalue()
s95, s70, s20, s10, s3 = (ls.blockiness_score(jq(_photo, q)) for q in (95, 70, 20, 10, 3))
check("B1 the score grows with compression: q95 about 1, q70 under 2.5, q20 above 4, q10 well above, q3 at the cap", s95 < 1.3 and s70 < 2.5 and s20 > 4 and s10 > 8 and s3 == ls.BLOCKINESS_CAP, (s95, s70, s20, s10, s3))
sb = ls.blockiness_score(jq(_photo.filter(ImageFilter.GaussianBlur(8)), 95))
check("B2 a blurred (smooth) photo has no block grid: score about 1, so blur is never read as blocks", sb < 1.3, sb)
buf = io.BytesIO(); Image.new("RGB", (800, 600), (120, 120, 120)).save(buf, "JPEG")
check("B3 a perfectly flat image scores 0 (never a problem); a tiny image or garbage bytes give None", ls.blockiness_score(buf.getvalue()) == 0.0 and ls.blockiness_score(jpeg(20, 20)) is None and ls.blockiness_score(b"not an image") is None)
check("B4 default limit 2.5 (measured: real photos max 1.44, damaged copies min 3.25); PVS_BLOCKINESS_MAX overrides; a bad value falls back to the default; 0 switches off",
      (os.environ.pop("PVS_BLOCKINESS_MAX"), ls.photo_blockiness_max())[1] == 2.5 and (os.environ.__setitem__("PVS_BLOCKINESS_MAX", "3.5"), ls.photo_blockiness_max())[1] == 3.5
      and (os.environ.__setitem__("PVS_BLOCKINESS_MAX", "abc"), ls.photo_blockiness_max())[1] == 2.5 and (os.environ.__setitem__("PVS_BLOCKINESS_MAX", "0"), ls.photo_blockiness_max())[1] == 0.0)
from PIL import Image as _PI
_big, _mid, _edge = _PI.new("RGB", (4096, 3041)), _PI.new("RGB", (1500, 1000)), _PI.new("RGB", (1920, 1080))
_v = ls.to_video_scale(_big)
check("B5 a photo above the video scale is brought to long side 1920 (aspect kept); smaller or equal ones are untouched",
      max(_v.size) == 1920 and abs(_v.size[0] / _v.size[1] - 4096 / 3041) < 0.002 and ls.to_video_scale(_mid) is _mid and ls.to_video_scale(_edge) is _edge, _v.size)
import base64 as _b64, io as _io
_buf = _io.BytesIO(); _big.save(_buf, "JPEG")
_c = _PI.open(_io.BytesIO(_b64.b64decode(ls._native_crop_b64(_buf.getvalue()))))
_buf2 = _io.BytesIO(); _mid.save(_buf2, "JPEG")
_c2 = _PI.open(_io.BytesIO(_b64.b64decode(ls._native_crop_b64(_buf2.getvalue()))))
check("B5b the crop is 768 x 768 for a big photo, and the whole 1000 px height of a smaller photo is cropped to 768 too", _c.size == (768, 768) and _c2.size == (768, 768), (_c.size, _c2.size))
REAL_MAX, DAMAGED_MIN = 1.436, 3.246      # measured on the server 2026-10-29: 101 real photos / six q3 copies
check("B4b the default limit sits between the measured real photos (max 1.436) and the lowest damaged copy (3.246), with margin on both sides", REAL_MAX * 1.5 < ls.BLOCKINESS_MAX_DEFAULT < DAMAGED_MIN * 0.85, ls.BLOCKINESS_MAX_DEFAULT)
os.environ["PVS_BLOCKINESS_MAX"] = "4"
os.environ["PVS_QUALITY_MODELS"] = "judge-a"
ANSWER.update(text="ANSWER: ok none"); ANSWER["per_model"] = {}
bad = jq(_photo, 10); good = jq(_photo, 95)
r = ls.assess_photo_quality(bad)
check("B5 the model says ok but the pixel check sees blocks -> blocky (the miss that was unacceptable), the pixel vote is in by_model with the score", r["verdict"] == "blocky" and r["by_model"] == {"judge-a": "ok", "blockiness": "blocky"} and r["blockiness"] > 8, r)
r = ls.assess_photo_quality(good)
check("B6 a normal photo: ok, pixel vote ok, score reported", r["verdict"] == "ok" and r["by_model"]["blockiness"] == "ok" and r["blockiness"] < 1.3, r)
ANSWER.update(text="ANSWER: soft none")
r = ls.assess_photo_quality(bad)
check("B7 the model already says soft: its word decides (the pixel vote is only the fallback word)", r["verdict"] == "soft", r)
ANSWER.update(raise_=True); ANSWER["raise"] = True
r = ls.assess_photo_quality(bad)
check("B8 every model call fails but the pixel check sees blocks -> blocky, call_ok True (a check that worked)", r["verdict"] == "blocky" and r["call_ok"] and r["by_model"] == {"blockiness": "blocky"}, r)
r = ls.assess_photo_quality(good)
check("B9 every model call fails and the pixels are fine -> unknown, call_ok False (as before)", r["verdict"] == "unknown" and not r["call_ok"], r)
ANSWER["raise"] = False
os.environ["PVS_BLOCKINESS_MAX"] = "0"
ANSWER.update(text="ANSWER: ok none")
r = ls.assess_photo_quality(bad)
check("B10 limit 0: the pixel check is off (no pixel vote, the model decides)", r["verdict"] == "ok" and "blockiness" not in r["by_model"], r)
os.environ["PVS_BLOCKINESS_MAX"] = "0"

# ── the quality filter works in the SELECTION (2026-10-29) ───────────────────
def pool(cats):
    """by_category-like pool: {cat: [photo dicts in rank order]} from {cat: [names]}"""
    return {c: [{"url": n, "category": c} for n in names] for c, names in cats.items()}
VERDICT = {}
def assess_named(content, label=""):
    return {"verdict": VERDICT.get(content, "ok"), "overlay": OVERLAY.get(content, "none"), "call_ok": True}
FETCHED = []
def fetch_named(url, fallback_url=None, timeout=20, attempts=1):
    FETCHED.append(url)
    return {"ok": True, "content": url, "url_used": url, "used_fallback": False, "error": None}
real_fetch = ls.fetch_photo_bytes
ls.fetch_photo_bytes = fetch_named
os.environ.pop("PVS_QUALITY_CHECK", None); os.environ.pop("PVS_QUALITY_ENFORCE", None)

VERDICT.clear(); VERDICT.update({"liv1": "blocky", "kit2": "soft"})
OVERLAY = {"bed1": "portal", "liv3": "agency"}
bc = pool({"living": ["liv1", "liv2", "liv3"], "kitchen": ["kit1", "kit2"], "bedrooms": ["bed1"]})
s_ = ls.filter_poor_quality_candidates(bc, assess=assess_named)
check("Q7 enforcing is the default: the blocky top candidate is removed, the next one comes first", [p["url"] for p in bc["living"]] == ["liv2", "liv3"], bc["living"])
check("Q8 a poor photo that was not first is removed too, the good ones stay in order", [p["url"] for p in bc["kitchen"]] == ["kit1"] and [p["url"] for p in bc["bedrooms"]] == ["bed1"])
check("Q8b photos labelled portal / agency are KEPT (only labelled)", [p["url"] for p in bc["living"]] == ["liv2", "liv3"] and bc["bedrooms"][0]["overlay"] == "portal" and bc["living"][1]["overlay"] == "agency" and bc["bedrooms"][0]["quality"] == "ok" and not bc["bedrooms"][0].get("quality_rejected"))
check("Q9 summary: 6 judged, 2 poor, enforced", s_["checked"] == 6 and s_["poor"] == 2 and s_["enforced"], s_)
check("Q10 every judged photo is tagged with its verdict; removed ones carry quality_rejected",
      all("quality" in p for pl in bc.values() for p in pl) and ls._quality_gap_note([{"quality_rejected": True}]).startswith(" 1 photo(s)"))

VERDICT.clear(); VERDICT.update({"liv1": "soft"})
bc = pool({"living": ["liv1", "liv2"]})
ls.filter_poor_quality_candidates(bc, assess=assess_named, enforce=False)
check("Q11 measure-only (enforce off): nothing removed, the verdict is saved and the photo marked poor", [p["url"] for p in bc["living"]] == ["liv1", "liv2"] and bc["living"][0].get("quality_poor") and not bc["living"][0].get("quality_rejected"))
os.environ["PVS_QUALITY_ENFORCE"] = "0"
bc = pool({"living": ["liv1", "liv2"]})
ls.filter_poor_quality_candidates(bc, assess=assess_named)
check("Q12 PVS_QUALITY_ENFORCE=0 gives the same measure-only behaviour", len(bc["living"]) == 2)
os.environ.pop("PVS_QUALITY_ENFORCE")

FETCHED.clear(); VERDICT.clear()
bc = pool({"living": ["a%d" % i for i in range(10)]})
ls.filter_poor_quality_candidates(bc, assess=assess_named)
check("Q13 only the best-ranked candidates are judged (QUALITY_JUDGE_PER_CATEGORY), not all 10", len(FETCHED) == ls.QUALITY_JUDGE_PER_CATEGORY, FETCHED)
os.environ["PVS_QUALITY_CHECK"] = "0"; FETCHED.clear()
bc = pool({"living": ["liv1"]})
check("Q14 PVS_QUALITY_CHECK=0 switches the filter off: no download, no call", ls.filter_poor_quality_candidates(bc, assess=lambda *a, **k: 1 / 0) == {"enabled": False} and not FETCHED)
os.environ.pop("PVS_QUALITY_CHECK")
bc = pool({"living": ["liv1", "liv2"]})
s_ = ls.filter_poor_quality_candidates(bc, assess=lambda c, label="": 1 / 0)
check("Q15 an assessor that crashes gives 'unknown': nothing removed, no exception", s_["unknown"] == 2 and len(bc["living"]) == 2, s_)
ls.fetch_photo_bytes = lambda *a, **k: {"ok": False, "content": None, "url_used": None, "used_fallback": False, "error": "x"}
bc = pool({"living": ["liv1"]})
check("Q15b a photo that cannot be downloaded for the check is kept (unknown)", ls.filter_poor_quality_candidates(bc, assess=assess_named)["unknown"] == 1 and len(bc["living"]) == 1)
ls.fetch_photo_bytes = fetch_named
check("Q14b enforcing defaults to ON, off only with PVS_QUALITY_ENFORCE=0", ls.photo_quality_enforce_enabled() and not (os.environ.update(PVS_QUALITY_ENFORCE="0") or ls.photo_quality_enforce_enabled()))
os.environ.pop("PVS_QUALITY_ENFORCE")

# end to end through the real selection functions (ranking replaced by "keep the order")
ls.rank_photos_by_quality = lambda category, candidates, max_to_compare=6: candidates
def listing(names_by_cat):
    return [{"url": n, "category": c, "label_it": ""} for c, ns in names_by_cat.items() for n in ns]
cats6 = {"exterior": ["ext1"], "living": ["liv1", "liv2"], "kitchen": ["kit1"], "bedrooms": ["bed1"], "bathrooms": ["bat1"], "outdoor": ["out1"]}
orig_assess = ls.assess_photo_quality
ls.assess_photo_quality = assess_named
VERDICT.clear(); VERDICT.update({"liv1": "blocky"})
sel = ls.select_photos_for_scene_count(listing(cats6), 6)
check("S1 the standard selection skips the blocky living photo and takes the next one: still 6 photos, no gap",
      [p["url"] for p in sel["selected"]["living"]] == ["liv2"] and sel["total_selected"] == 6 and not sel["gaps"], sel)
VERDICT.clear(); VERDICT.update({"liv1": "blocky", "kit1": "soft"})
photos = listing({"exterior": ["ext1"], "living": ["liv1"], "kitchen": ["kit1"], "bedrooms": ["bed1"], "bathrooms": ["bat1"], "outdoor": ["out1"]})
sel = ls.select_photos_for_scene_count(photos, 6)
check("S2 not enough good photos: the gap names the quality reason (2 photos discarded)", sel["gaps"] and "2 photo(s) of the listing were discarded for insufficient image quality" in sel["gaps"][0], sel["gaps"])
rep = ls.build_selection_report(photos, sel, 6)
check("S3 the selection report lists the rejected photos with their verdicts and counts the judged ones",
      sorted(x["verdict"] for x in rep["quality_rejected"]) == ["blocky", "soft"] and rep["quality_checked"] == 6, rep["quality_rejected"])
VERDICT.clear()
sel = ls.select_photos_for_scene_count_premium(listing({"exterior": ["e1"], "living": ["l1"]}), 11)
check("S4 the premium selection goes through the same filter (its gap text exists and carries no quality note when nothing was discarded)", sel["gaps"] and "discarded" not in sel["gaps"][0], sel["gaps"])
VERDICT.update({"e1": "blocky", "l1": "soft"})
sel = ls.select_photos_for_scene_count_premium(listing({"exterior": ["e1"], "living": ["l1"]}), 11)
check("S5 premium: the quality note is in the gap when photos were discarded", "discarded for insufficient image quality" in sel["gaps"][0], sel["gaps"])
ls.assess_photo_quality = orig_assess
ls.fetch_photo_bytes = real_fetch

# the shared sender is still the only place that calls the API: the old one-photo function goes through it
ANSWER.update(text="hall"); SENT.clear()
MAXTOK.clear()
check("Q16 _vision_one_word (room questions) still works through the same sender, unchanged: bare word, small token limit", ls._vision_one_word("u", None, "q") == ("hall", True) and len(SENT[0]) == 1 and MAXTOK == [20], MAXTOK)

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
check("R6 the quality filter lives in the selection only: no second implementation in api_server", "check_selected_photo_quality" not in api and "filter_poor_quality_candidates" not in api)
src_ls = open("listing_scraper.py").read()
check("R7 the filter is called from the ONE shared ranking step used by both selections", src_ls.count("filter_poor_quality_candidates(by_category)") == 1 and src_ls.count("_categorize_and_rank_photos(photos,") == 2)

print()
print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
