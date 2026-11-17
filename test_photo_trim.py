"""Tests of the white padding border trim (photo_format) and of the portrait vote on trimmed size. Plain script: prints PASS/FAIL lines."""
import io, sys
import numpy as np
from PIL import Image
import photo_format as pf

fails = 0
def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (" " + str(info) if info and not cond else ""))
    if not cond:
        fails += 1

def room(w, h, seed=1):
    """A textured, room-like picture: gradients, darker floor and dark blocks, nothing uniform white on the edges."""
    r = np.random.RandomState(seed)
    y = np.linspace(0, 1, h)[:, None]; x = np.linspace(0, 1, w)[None, :]
    base = 150 + 60 * np.sin(6 * x) * np.cos(4 * y) - 40 * y
    base = base + r.normal(0, 6, (h, w))
    arr = np.clip(base, 20, 235)
    arr[int(h * .3):int(h * .9), int(w * .45):int(w * .5)] = 30
    return arr

def to_jpeg(arr3):
    im = Image.fromarray(np.clip(arr3, 0, 255).astype("uint8"))
    b = io.BytesIO(); im.save(b, "JPEG", quality=92); return b.getvalue()

def rgb(gray):
    return np.stack([gray, gray * 0.98, gray * 0.95], axis=2)

W, H = 2048, 1152
# T1: top band of 22 near-white rows (Marino case) is trimmed
a = room(W, H); a[:22, :] = 253
img = Image.open(io.BytesIO(to_jpeg(rgb(a))))
box = pf.border_box(img)
check("T1 top band 22 rows found", box[1] >= 20 and box[1] <= 24 and box[0] == 0 and box[2] == W and box[3] == H, box)
# T2: the output of normalize is exactly 16:9 and has no band
out = pf.normalize_photo_to_format(to_jpeg(rgb(a)), "landscape")
o = Image.open(io.BytesIO(out)); ow, oh = o.size
check("T2 exact 16:9 after trim", abs(ow / oh - 16 / 9) < 0.002, (ow, oh))
top_rows = np.asarray(o.convert("L"), dtype=float)[:6].mean()
check("T2 first rows are picture, not white", top_rows < 235, top_rows)
# T3: no band -> unchanged bytes (already 16:9)
raw = to_jpeg(rgb(room(W, H)))
check("T3 untouched photo returned as is", pf.normalize_photo_to_format(raw, "landscape") == raw)
# T4: a real white ceiling (smooth gradient, no sharp step) is not eaten
c = room(W, H); grad = np.linspace(255, 225, 80)[:, None]; c[:80, :] = grad
box = pf.border_box(Image.open(io.BytesIO(to_jpeg(rgb(c)))))
check("T4 white ceiling gradient kept", box[1] == 0, box)
# T5: bands on all four sides
d = room(W, H); d[:20] = 254; d[-20:] = 254; d[:, :30] = 254; d[:, -30:] = 254
box = pf.border_box(Image.open(io.BytesIO(to_jpeg(rgb(d)))))
check("T5 four sides", box[0] >= 28 and box[1] >= 18 and box[2] <= W - 28 and box[3] <= H - 18, box)
# T6: thickness cap (25 %): a 400 px white block is not removed beyond the cap
e = room(W, H); e[:400] = 254
box = pf.border_box(Image.open(io.BytesIO(to_jpeg(rgb(e)))))
check("T6 cap respected", box[1] == 0 or box[1] <= int(H * 0.25), box)
# T7: two rows only (below the minimum) are left alone
f = room(W, H); f[:2] = 254
check("T7 thin line ignored", pf.border_box(Image.open(io.BytesIO(to_jpeg(rgb(f)))))[1] == 0)
# T8: trimmed_size reflects the cut
check("T8 trimmed_size", pf.trimmed_size(to_jpeg(rgb(a)))[1] in range(1128, 1133), pf.trimmed_size(to_jpeg(rgb(a))))
# T9: a portrait photo with side padding that is really landscape: the vote sees the trimmed size
g = room(1200, 1600); g[:, :] = 253
g[400:1200, :] = room(1200, 800)          # a landscape picture centred on a portrait white canvas
sz = pf.trimmed_size(to_jpeg(rgb(g)))
check("T9 padded landscape on portrait canvas votes landscape", sz[0] >= sz[1], sz)
# T10: portrait normalisation still works (no trim, old crop)
p = room(900, 1600)
o = Image.open(io.BytesIO(pf.normalize_photo_to_format(to_jpeg(rgb(p)), "landscape")))
check("T10 portrait source cropped to landscape", abs(o.size[0] / o.size[1] - 16 / 9) < 0.01, o.size)
# T11: black / grey borders are not touched by this rule
h_ = room(W, H); h_[:22] = 20
check("T11 dark border not trimmed here", pf.border_box(Image.open(io.BytesIO(to_jpeg(rgb(h_)))))[1] == 0)
# T12: a 4:3 photo padded to 16:9 (pillar bars of 12.5 % per side, the usual Relinx case) is trimmed to the real picture
k = np.full((H, W), 253.0); pw = int(H * 4 / 3); x0 = (W - pw) // 2; k[:, x0:x0 + pw] = room(pw, H)
box = pf.border_box(Image.open(io.BytesIO(to_jpeg(rgb(k)))))
check("T12 4:3 pillars trimmed", box[0] >= x0 - 3 and box[2] <= x0 + pw + 3 and box[1] == 0, (box, x0))

print("RESULT", "ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
