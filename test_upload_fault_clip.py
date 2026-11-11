import os, sys, json, types, tempfile, time
sys.path.insert(0, os.getcwd())
st = tempfile.mkdtemp(prefix="pvsfake_"); os.environ["PVS_FAKE_DIR"] = st
os.environ["PVS_FAKE_PROVIDERS"] = "1"; os.environ["LUMA_DIRECT"] = "true"; os.environ["FAL_FALLBACK_ENABLED"] = "true"
fc = types.ModuleType("fal_client"); fc.subscribe = fc.upload_file = lambda *a, **k: "REAL"
an = types.ModuleType("anthropic"); an.Anthropic = lambda *a, **k: "REAL"
sys.modules["fal_client"] = fc; sys.modules["anthropic"] = an
import fake_providers as fp, video_generation as vg
fp.install_if_enabled()
from PIL import Image
img = os.path.join(st, "r.jpg"); Image.new("RGB", (1600, 1200), (120, 160, 200)).save(img)
n = [1]
def faults(d):
    p = os.path.join(st, "faults.json"); open(p, "w").write(json.dumps(d)); t = time.time() + n[0]; os.utime(p, (t, t)); n[0] += 1
def run(label, d):
    faults(d); out = os.path.join(st, label + ".mp4")
    try: r = vg.generate_video_single(img, 5, out, model_tier="luma")
    except Exception: r = "RAISED"
    return r, os.path.exists(out)
a, b, c = run("A", {"fal_upload": ["http_500", "ok"]}), run("B", {"fal_upload": ["http_500"] * 3}), run("C", {"fal_upload": ["http_500"] * 12})
T = [("K1 un errore di caricamento: la ripetizione produce la clip", a == (True, True)),
     ("K2 tre errori di fila: clip mancante, False, nessun file", b == (False, False)),
     ("K3 errore sempre: clip mancante, False, nessun file", c == (False, False))]
bad = 0
for t, ok in T:
    print("PASS" if ok else "FAIL", t); bad += (not ok)
raise SystemExit(bad)
