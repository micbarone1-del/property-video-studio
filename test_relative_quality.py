import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageFilter
import photo_metrics as pm
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
im = Image.fromarray(x.astype("uint8")).convert("RGB")
a = pm.relative_quality(im)
b = pm.relative_quality(im.filter(ImageFilter.GaussianBlur(10)))
p = pm.relative_quality(im.resize((333, 250), Image.BILINEAR).resize((2000, 1500), Image.NEAREST))
chk("Q1 sharp image: no grid", a["period"] < 1.05, a)
chk("Q2 blurred image has a lower fine_mid than the sharp one", b["fine_mid"] < a["fine_mid"] - 0.05, (a, b))
chk("Q3 enlarged pixels give a clear period peak at the right k", p["period"] > 5 and p["period_k"] == 6, p)
w = pm.relative_quality(Image.new("RGB", (2000, 1500), (230, 230, 225)))
chk("Q4 plain wall is NOT flagged (no fine_mid, no grid)", w.get("fine_mid") is None and w["period"] == 1.0, w)
chk("Q5 same input, same numbers (deterministic)", pm.relative_quality(im) == a)
chk("Q6 unreadable input gives {} and never raises", pm.relative_quality_of_bytes(b"x") == {})
print("FAILS", F); sys.exit(1 if F else 0)
