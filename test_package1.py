"""Package 1 (2026-10-12): resync data-loss fix, retries for photo download and TTS measurement, scene captions off.
No network, no API keys: everything external is stubbed."""
import os, sys, types, tempfile, shutil
sys.path.insert(0, os.getcwd())
for name in ("anthropic",):
    try:
        __import__(name)
    except Exception:
        m = types.ModuleType(name); m.Anthropic = object; sys.modules[name] = m
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

class Resp:
    def __init__(self, code, content=b"JPEGDATA"):
        self.status_code = code; self.content = content
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

def run_download(seq):
    calls = []
    it = iter(seq)
    def fake_get(url, timeout=0):
        calls.append(url)
        x = next(it)
        if isinstance(x, Exception): raise x
        return x
    ls.requests.get = fake_get
    d = Path(tempfile.mkdtemp())
    sleeps.clear()
    r = ls.download_photo("http://x/y.jpg", d, "p")
    return r, len(calls), d

r, n, d = run_download([Resp(200)])
check("D0 first try ok, no sleep", r["ok"] and n == 1 and not sleeps and (d / "p.jpg").read_bytes() == b"JPEGDATA")
r, n, d = run_download([requests.ConnectionError("boom"), requests.Timeout("slow"), Resp(200)])
check("D1 two transient errors then ok", r["ok"] and n == 3 and len(sleeps) == 2, (r, n))
r, n, d = run_download([Resp(500), Resp(503), Resp(200)])
check("D2 HTTP 5xx retried", r["ok"] and n == 3, (r, n))
r, n, d = run_download([Resp(429), Resp(200)])
check("D3 HTTP 429 retried", r["ok"] and n == 2, (r, n))
r, n, d = run_download([Resp(404)])
check("D4 404 is permanent: one call, no sleep", (not r["ok"]) and n == 1 and not sleeps, (r, n))
r, n, d = run_download([requests.Timeout("a"), requests.Timeout("b"), requests.Timeout("c")])
check("D5 always failing: 3 attempts then clean failure", (not r["ok"]) and n == 3 and "3 attempts" in r["error"], (r, n))
check("D6 no file left on failure", not (d / "p.jpg").exists())

# TTS measurement retries
vg = types.ModuleType("voice_generation"); pd = types.ModuleType("pydub")
class Seg:
    def __len__(self): return 5000
class AS:
    @staticmethod
    def from_file(p): return Seg()
pd.AudioSegment = AS
sys.modules["voice_generation"] = vg; sys.modules["pydub"] = pd
def make_tts(results):
    it = iter(results); calls = []
    def gen(text, path, voice_id=None, **kw):
        calls.append(1)
        x = next(it)
        if isinstance(x, Exception): raise x
        if x: open(path, "wb").write(b"mp3")
        return x
    vg.generate_speech = gen
    return calls
sleeps.clear(); calls = make_tts([True])
r = ls._measure_tts_duration("ciao")
check("T0 first try ok", r["ok"] and r["duration_secs"] == 5.0 and len(calls) == 1 and not sleeps)
sleeps.clear(); calls = make_tts([False, False, True])
r = ls._measure_tts_duration("ciao")
check("T1 two failures then ok (backoff 2s, 4s)", r["ok"] and len(calls) == 3 and sleeps == [2, 4], (r, sleeps))
sleeps.clear(); calls = make_tts([RuntimeError("quota"), True])
r = ls._measure_tts_duration("ciao")
check("T2 exception then ok", r["ok"] and len(calls) == 2, r)
sleeps.clear(); calls = make_tts([False, False, False])
r = ls._measure_tts_duration("ciao")
check("T3 always failing: 3 attempts, ok False, no exception", (not r["ok"]) and len(calls) == 3 and r["duration_secs"] is None, r)

# captions switched off
sel = {"selected": {"living": [{"local_path": "a.jpg"}], "kitchen": [{"local_path": "b.jpg"}]}}
caps = {"living": "Soggiorno", "kitchen": "Cucina"}
check("C0 flag is OFF by default", ls.SCENE_CAPTIONS_ENABLED is False)
sc = ls.build_standard_video_scenes_config(sel, caps)
check("C1 standard builder: empty captions", len(sc) == 2 and all(s["caption"] == "" for s in sc), sc)
psel = {"selected": {ls.PREMIUM_PRIORITY_ORDER[0]: [{"local_path": "a.jpg"}]}}
pc = ls.build_premium_video_scenes_config(psel, {}, )
check("C2 premium builder: empty captions", len(pc) == 1 and pc[0]["caption"] == "", pc)
check("C3 generate_captions makes no Claude call and returns {}", ls.generate_captions_for_categories("desc", ["living"]) == {})
ls.SCENE_CAPTIONS_ENABLED = True
sc = ls.build_standard_video_scenes_config(sel, caps)
check("C4 flag ON restores captions", [s["caption"] for s in sc] == ["Soggiorno", "Cucina"], sc)
ls.SCENE_CAPTIONS_ENABLED = False

# safe directory swap
from safe_fs import replace_dir_atomic
base = Path(tempfile.mkdtemp())
(base / "images").mkdir(); (base / "images" / "old.jpg").write_bytes(b"OLD")
(base / "images.new").mkdir(); (base / "images.new" / "new.jpg").write_bytes(b"NEW")
replace_dir_atomic(base / "images.new", base / "images")
check("S1 swap: new content live, old kept as images.prev",
      (base / "images" / "new.jpg").exists() and not (base / "images" / "old.jpg").exists()
      and (base / "images.prev" / "old.jpg").read_bytes() == b"OLD" and not (base / "images.new").exists())
(base / "images.new").mkdir(); (base / "images.new" / "n2.jpg").write_bytes(b"N2")
replace_dir_atomic(base / "images.new", base / "images")
check("S2 second swap replaces the previous .prev", (base / "images.prev" / "new.jpg").exists() and (base / "images" / "n2.jpg").exists())
base2 = Path(tempfile.mkdtemp()); (base2 / "n").mkdir(); (base2 / "n" / "f").write_bytes(b"1")
replace_dir_atomic(base2 / "n", base2 / "images")
check("S3 swap works when there was no images dir", (base2 / "images" / "f").exists())
base3 = Path(tempfile.mkdtemp()); (base3 / "images").mkdir(); (base3 / "images" / "keep.jpg").write_bytes(b"K")
try:
    replace_dir_atomic(base3 / "does_not_exist", base3 / "images"); raised = False
except Exception:
    raised = True
check("S4 failing swap puts the old photos back and raises", raised and (base3 / "images" / "keep.jpg").read_bytes() == b"K")

# resync endpoint: validate first, never wipe before the swap (source-level check; the web framework is not needed)
src = open("api_server.py", encoding="utf-8").read()
i = src.index("async def resync_draft(")
j = src.index('@app.post("/jobs/{job_id}/narration")')
seg = src[i:j]
check("R1 resync no longer rmtree()s the real images dir", "shutil.rmtree(str(img_dir)" not in seg)
check("R2 resync validates (Pass 1) before it writes (Pass 2)", seg.index("_validate_image_bytes") < seg.index("replace_dir_atomic") < len(seg))
check("R3 resync writes into a scratch dir and swaps", 'job_dir / "images.new"' in seg and "replace_dir_atomic(new_img_dir, img_dir)" in seg)

print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
