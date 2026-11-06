import os, sys, io, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import numpy as np
from PIL import Image, ImageFilter
import listing_scraper as ls
F = 0
def chk(n, c, info=""):
    global F
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); F += (not c)

rng = np.random.default_rng(3)
x = np.zeros((1500, 2000), dtype="float32")
for s in (200, 60, 20, 6):
    n = rng.normal(size=(1500 // max(1, s // 4) + 2, 2000 // max(1, s // 4) + 2)).astype("float32")
    x += np.asarray(Image.fromarray(n).resize((2000, 1500), Image.BICUBIC)) * s ** 0.5
x = (x - x.min()) / (x.max() - x.min()) * 255
sharp = Image.fromarray(x.astype("uint8")).convert("RGB")
def jpg(im):
    b = io.BytesIO(); im.save(b, "JPEG", quality=92); return b.getvalue()
SHARP = jpg(sharp)
BLUR = jpg(sharp.filter(ImageFilter.GaussianBlur(10)))
PIXEL = jpg(sharp.resize((333, 250), Image.BILINEAR).resize((2000, 1500), Image.NEAREST))

ls._image_b64_for_vision = lambda c: "x"; ls._native_crop_b64 = lambda c: "x"
def judge(word):
    ls._assess_with_model = lambda images, model, label: {"verdict": word, "overlay": "none", "call_ok": True}
os.environ.pop("PVS_OBJECTIVE_QUALITY", None)

judge("ok");   r = ls.assess_photo_quality(SHARP, "t", models=("m",))
chk("O1 sharp photo, model ok -> ok", r["verdict"] == "ok", r)
judge("soft"); r = ls.assess_photo_quality(SHARP, "t", models=("m",))
chk("O2 model says soft but the measure does not confirm -> kept (ok), recorded as unconfirmed", r["verdict"] == "ok" and r["soft_unconfirmed"] == ["m"], r)
judge("soft"); r = ls.assess_photo_quality(BLUR, "t", models=("m",))
chk("O3 model soft AND measured blur -> soft", r["verdict"] == "soft", r)
judge("ok");   r = ls.assess_photo_quality(BLUR, "t", models=("m",))
chk("O4 measured blur alone (model ok) does NOT discard (AND rule)", r["verdict"] == "ok", r)
judge("ok");   r = ls.assess_photo_quality(PIXEL, "t", models=("m",))
chk("O5 enlarged pixels discard on their own even if the model says ok (OR)", r["verdict"] == "blocky" and r["by_model"].get("period") == "blocky", r)
judge("blocky"); r = ls.assess_photo_quality(SHARP, "t", models=("m",))
chk("O6 a model 'blocky' still counts alone (unchanged)", r["verdict"] == "blocky", r)
os.environ["PVS_OBJECTIVE_QUALITY"] = "0"
judge("soft"); r = ls.assess_photo_quality(SHARP, "t", models=("m",))
chk("O7 switch off: old behaviour (model soft discards)", r["verdict"] == "soft" and r["objective"] is None, r)
os.environ.pop("PVS_OBJECTIVE_QUALITY")
ls._assess_with_model = lambda images, model, label: {"verdict": "unknown", "overlay": "unknown", "call_ok": False}
r = ls.assess_photo_quality(PIXEL, "t", models=("m",))
chk("O8 every model call fails: enlarged pixels still decide", r["verdict"] == "blocky", r)
r = ls.assess_photo_quality(SHARP, "t", models=("m",))
chk("O9 every model call fails and nothing measured wrong: unknown, never a problem", r["verdict"] == "unknown", r)
judge("ok"); a = ls.assess_photo_quality(SHARP, "t", models=("m",)); b = ls.assess_photo_quality(SHARP, "t", models=("m",))
chk("O10 same photo, same measured numbers", a["objective"] == b["objective"])
print("FAILS", F); sys.exit(1 if F else 0)
