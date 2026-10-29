"""calibrate_quality.py: dry run sends nothing, jobs/ is never written, duplicates/small files skipped, cap stops spending. No network."""
import io, os, sys, types, tempfile, shutil, hashlib, subprocess
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
from PIL import Image
import numpy as np
import listing_scraper as ls
import calibrate_quality as cq

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def jpg(w, h, seed):
    rng = np.random.RandomState(seed)
    buf = io.BytesIO(); Image.fromarray(rng.randint(0, 255, (h, w, 3), dtype=np.uint8)).save(buf, "JPEG"); return buf.getvalue()

root = tempfile.mkdtemp()
jobs = os.path.join(root, "jobs"); out = os.path.join(root, "out")
for j, files in {"aaaa1111": {"scene_000.jpg": jpg(1200, 800, 1), "scene_001.jpg": jpg(1200, 800, 2), "tiny.jpg": jpg(300, 200, 3)},
                 "bbbb2222": {"scene_000.jpg": jpg(1200, 800, 1), "scene_001.jpg": jpg(1400, 900, 4), "notes.txt": b"x"}}.items():
    os.makedirs(os.path.join(jobs, j, "images"))
    for n, b in files.items():
        open(os.path.join(jobs, j, "images", n), "wb").write(b)

def snapshot():
    return sorted((os.path.join(d, f), hashlib.sha1(open(os.path.join(d, f), "rb").read()).hexdigest()) for d, _, fs in os.walk(jobs) for f in fs)
before = snapshot()

photos, stats = cq.collect(__import__("pathlib").Path(jobs))
check("C1 unique usable photos = 3 (duplicate and tiny skipped, txt ignored)", len(photos) == 3, (len(photos), stats))
check("C2 counters: 5 images read, 1 duplicate, 1 too small", stats == {"files": 5, "duplicates": 1, "too_small_or_unreadable": 1}, stats)
check("C3 pick(2) spreads over both jobs", len({p["job"] for p in cq.pick(photos, 2)}) == 2)

# dry run: judge must not be called, nothing written
calls = []
ls.assess_photo_quality = lambda content, label="": calls.append(label) or {"verdict": "ok", "call_ok": True}
sys.argv = ["x", "--jobs-dir", jobs, "--out", out]
cq.main()
check("C4 dry run: zero judge calls", calls == [])
check("C5 dry run: output folder not created", not os.path.exists(out))

# real run with a fake judge
os.environ["ANTHROPIC_API_KEY"] = "test"
verd = iter(["ok", "soft", "blocky"])
ls.assess_photo_quality = lambda content, label="": {"verdict": next(verd), "call_ok": True}
sys.argv = ["x", "--run", "--jobs-dir", jobs, "--out", out]
cq.main()
csv_text = open(os.path.join(out, "verdicts.csv")).read().splitlines()
check("C6 csv has header + 3 rows", len(csv_text) == 4, csv_text)
check("C7 contact sheets written for each verdict", all(os.path.exists(os.path.join(out, f"sheet_{v}_1.jpg")) for v in ("ok", "soft", "blocky")))
check("C8 jobs/ untouched (same files, same bytes)", snapshot() == before)

# cap: the second call pushes the cost over the cap -> the rest are skipped
shutil.rmtree(out)
def costly(content, label=""):
    ls._claude_usage["input_tokens"] += 50_000_000
    return {"verdict": "ok", "call_ok": True}
ls.reset_claude_usage(); ls.assess_photo_quality = costly
sys.argv = ["x", "--run", "--cap", "0.10", "--jobs-dir", jobs, "--out", out]
import contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cq.main()
n_rows = len(open(os.path.join(out, "verdicts.csv")).read().splitlines()) - 1
check("C9 cap stops the run early (fewer than 3 judged)", n_rows < 3 and "stopped at the cap" in buf.getvalue(), (n_rows, buf.getvalue()[-200:]))
# ── control test with damaged copies ─────────────────────────────────────────
shutil.rmtree(out, ignore_errors=True)
calls2 = []
def judge_by_label(content, label=""):
    calls2.append(label)
    return {"verdict": "ok" if label.startswith("original") else ("soft" if label.startswith("blur") else "blocky"), "call_ok": True}
ls.reset_claude_usage(); ls.assess_photo_quality = judge_by_label
sys.argv = ["x", "--degrade-test", "3", "--jobs-dir", jobs, "--out", out]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cq.main()
check("D1 control-test dry run: no judge call, nothing written", calls2 == [] and not os.path.exists(out) and "12 calls" in buf.getvalue(), buf.getvalue()[-200:])
sys.argv = ["x", "--degrade-test", "3", "--run", "--jobs-dir", jobs, "--out", out]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cq.main()
txt = buf.getvalue()
check("D2 control test: 3 photos x 4 = 12 judge calls", len(calls2) == 12, len(calls2))
check("D3 the report says 9 of 9 damaged copies recognised and 0 of 3 false alarms", "recognised as soft/blocky: 9 of 9" in txt and "false alarms): 0 of 3" in txt, txt[-500:])
check("D4 9 damaged copies written under out/degraded, none under jobs/", len(os.listdir(os.path.join(out, "degraded"))) == 9 and snapshot() == before)
check("D5 results csv written", os.path.exists(os.path.join(out, "degrade_test.csv")))
orig = jpg(1200, 800, 7)
v = cq.make_variants(orig)
sizes = {k: Image.open(io.BytesIO(b)).size for k, b in v.items()}
check("D6 the three damaged copies keep the photo size and decode", set(v) == {"blur", "pixelated", "jpegblocks"} and all(s == (1200, 800) for s in sizes.values()), sizes)
def detail(b):
    a = np.asarray(Image.open(io.BytesIO(b)).convert("L"), dtype=float)
    return float(np.abs(np.diff(a, axis=1)).mean())
check("D7 blur and pixelated really remove fine detail (much lower edge energy than the original)", detail(v["blur"]) < detail(orig) * 0.5 and detail(v["pixelated"]) < detail(orig) * 0.7, (detail(orig), detail(v["blur"]), detail(v["pixelated"])))
check("D8 jpegblocks is much smaller than the original file (heavy compression)", len(v["jpegblocks"]) < len(orig) * 0.5, (len(v["jpegblocks"]), len(orig)))
# ── --model: another model for one run, and failed calls are reported ─────────
shutil.rmtree(out, ignore_errors=True)
old_model = ls.MODEL
sys.argv = ["x", "--degrade-test", "3", "--model", "claude-sonnet-5-5", "--jobs-dir", jobs, "--out", out]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cq.main()
check("M1 --model sets the judge model of this run and the cost estimate prices it", os.environ.get("PVS_QUALITY_MODELS") == "claude-sonnet-5-5" and "judge models: claude-sonnet-5-5" in buf.getvalue(), buf.getvalue()[:300])
os.environ.pop("PVS_QUALITY_MODELS", None)
old_model = None
ls.reset_claude_usage(); ls.assess_photo_quality = lambda content, label="": {"verdict": "unknown", "call_ok": False}
sys.argv = ["x", "--degrade-test", "3", "--run", "--jobs-dir", jobs, "--out", out]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cq.main()
check("M2 failed judge calls are reported loudly (wrong model name)", "12 of 12 judge calls FAILED" in buf.getvalue(), buf.getvalue()[-300:])
src = open("calibrate_quality.py").read()
check("C10 tool has no delete/move/write-to-jobs calls", not any(w in src for w in ("unlink", "rmtree", "os.remove", ".rename(", "shutil.move")))
shutil.rmtree(root)
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
