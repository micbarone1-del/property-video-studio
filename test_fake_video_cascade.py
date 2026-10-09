import os, sys, json, types, tempfile, time, subprocess
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, REPO)
st = tempfile.mkdtemp(prefix="pvsfake_"); os.environ["PVS_FAKE_DIR"] = st
os.environ["PVS_FAKE_PROVIDERS"] = "1"; os.environ["LUMA_DIRECT"] = "true"
fc = types.ModuleType("fal_client"); fc.subscribe = fc.upload_file = lambda *a, **k: "REAL"
an = types.ModuleType("anthropic"); an.Anthropic = lambda *a, **k: "REAL"
sys.modules["fal_client"] = fc; sys.modules["anthropic"] = an
import fake_providers as fp
import video_generation as vg
fp.install_if_enabled()
res = []
def check(n, ok, info=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + n + ("" if ok else f" -- {info}"))
from PIL import Image
img = os.path.join(st, "r.jpg"); Image.new("RGB", (1600, 1200), (120, 160, 200)).save(img)
def faults(d):
    p = os.path.join(st, "faults.json"); open(p, "w").write(json.dumps(d)); t = time.time() + faults.n; os.utime(p, (t, t)); faults.n += 1
faults.n = 1
def dur(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p], capture_output=True, text=True)
    return float(json.loads(o.stdout)["format"]["duration"])
def calls(kind): return [json.loads(l) for l in open(os.path.join(st, "outbox.jsonl")) if json.loads(l)["kind"] == kind] if os.path.exists(os.path.join(st, "outbox.jsonl")) else []
def reset_outbox():
    p = os.path.join(st, "outbox.jsonl")
    if os.path.exists(p): os.remove(p)
check("V0 LUMA_DIRECT on in this module", vg.LUMA_DIRECT is True)

out = os.path.join(st, "c1.mp4"); reset_outbox()
ok = vg.generate_video_single(img, 5, out, model_tier="luma")
check("V1 normal clip via Luma direct: True + playable ~5s", ok and os.path.exists(out) and abs(dur(out) - 5) < 0.5, (ok,))
check("V1b only Luma direct was called (no fal)", len(calls("luma_create")) == 1 and len(calls("fal_subscribe")) == 0, (len(calls("luma_create")), len(calls("fal_subscribe"))))

faults({"luma_direct": ["http_400"], "luma_fal": ["failed"]}); reset_outbox(); out = os.path.join(st, "c2.mp4")
ok = vg.generate_video_single(img, 5, out, model_tier="luma")
fs = [c["endpoint"] for c in calls("fal_subscribe")]
check("V2 Luma 400 + same-price fal Luma fails: STOP, no Veo/LTX", (not ok) and len(calls("luma_create")) == 1 and any("luma" in e for e in fs) and not any(("veo" in e) or ("ltx" in e) for e in fs) and not os.path.exists(out), (ok, fs))

faults({"luma_direct": ["http_400"]}); reset_outbox(); out = os.path.join(st, "c2b.mp4")
ok = vg.generate_video_single(img, 5, out, model_tier="luma")
fs = [c["endpoint"] for c in calls("fal_subscribe")]
check("V2b Luma 400 but fal Luma works: clip produced at the same price, no Veo", ok and os.path.exists(out) and not any("veo" in e for e in fs), (ok, fs))

faults({"luma_direct": ["http_500"]}); reset_outbox(); out = os.path.join(st, "c3.mp4")
ok = vg.generate_video_single(img, 5, out, model_tier="luma")
check("V3 Luma transient HTTP 500: fal Luma fallback produces a clip", ok and os.path.exists(out), (ok, [c["endpoint"] for c in calls("fal_subscribe")]))

faults({"luma_direct": ["http_500"], "luma_fal": ["failed"]}); reset_outbox(); out = os.path.join(st, "c3b.mp4")
ok = vg.generate_video_single(img, 5, out, model_tier="luma")
fs = [c["endpoint"] for c in calls("fal_subscribe")]
check("V3b transient error on both Luma paths: full cascade to Veo still works", ok and any("veo" in e for e in fs), (ok, fs))

faults({"luma_direct": ["failed"], "luma_fal": ["failed"]}); reset_outbox(); out = os.path.join(st, "c4.mp4")
ok = vg.generate_video_single(img, 5, out, model_tier="luma")
fs = [c["endpoint"] for c in calls("fal_subscribe")]
check("V4 Luma accepted-then-failed on both: escalates to Veo (KNOWN GAP, backlog 59 -- asserts current behavior)", ok and any("veo" in e for e in fs), (ok, fs))
print("RESULT:", "ALL PASS" if all(res) else "FAILURES", f"({sum(res)}/{len(res)})")
