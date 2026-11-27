import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image
import photo_format as pf
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)
def enc(img, fmt, **kw):
    b = io.BytesIO(); img.save(b, format=fmt, **kw); return b.getvalue()
def dim(b):
    return Image.open(io.BytesIO(b)).size
# P1 PNG with transparency (RGBA): used to raise "cannot write mode RGBA as JPEG" (job upload, 2026-11-27)
rgba = Image.new("RGBA", (800, 800), (10, 120, 200, 255)); rgba.paste((0, 0, 0, 0), (0, 0, 100, 100))
out = pf.normalize_photo_to_format(enc(rgba, "PNG"), "landscape")
chk("P1 RGBA png, landscape job: no exception, JPEG bytes out", out[:2] == b"\xff\xd8")
chk("P2 RGBA png: result is exactly 16:9", abs(dim(out)[0] / dim(out)[1] - 16 / 9) < 0.02)
out = pf.normalize_photo_to_format(enc(rgba, "PNG"), "portrait")
chk("P3 RGBA png, portrait job: no exception", out[:2] == b"\xff\xd8")
flat, ch = pf.open_upright(enc(rgba, "PNG"))
chk("P4 transparent pixel becomes white, mode RGB", flat.mode == "RGB" and flat.getpixel((5, 5)) == (255, 255, 255) and ch)
pal = Image.new("P", (640, 360)); pal.info["transparency"] = 0
chk("P5 palette png with transparency: no exception", pf.normalize_photo_to_format(enc(pal, "PNG", transparency=0), "landscape")[:2] == b"\xff\xd8")
# O1 EXIF orientation 6 (phone portrait stored sideways): must come out upright
side = Image.new("RGB", (400, 300), (50, 90, 130)); ex = Image.Exif(); ex[274] = 6
jb = enc(side, "JPEG", exif=ex.tobytes())
chk("O1 trimmed_size sees the upright portrait (300x400)", pf.trimmed_size(jb) == (300, 400))
out = pf.normalize_photo_to_format(jb, "portrait")
chk("O2 EXIF 6 photo in a portrait job is re-encoded upright (9:16 crop of 300x400)", dim(out)[1] > dim(out)[0] and out != jb)
out = pf.normalize_photo_to_format(jb, "landscape")
chk("O3 EXIF 6 photo in a landscape job: 16:9 band cut from the UPRIGHT picture (width 300)", dim(out)[0] == 300 and abs(dim(out)[0] / dim(out)[1] - 16 / 9) < 0.02)
# U unchanged behaviour: a normal 16:9 photo goes through byte for byte
ok = enc(Image.new("RGB", (1600, 900), (90, 90, 90)), "JPEG")
chk("U1 plain 16:9 JPEG, no EXIF: original bytes returned untouched", pf.normalize_photo_to_format(ok, "landscape") == ok)
okp = enc(Image.new("RGB", (1600, 900), (90, 90, 90)), "PNG")
chk("U2 plain 16:9 RGB PNG: original bytes returned untouched", pf.normalize_photo_to_format(okp, "landscape") == okp)
exif1 = Image.Exif(); exif1[274] = 1
o1 = enc(Image.new("RGB", (1600, 900), (90, 90, 90)), "JPEG", exif=exif1.tobytes())
chk("U3 EXIF orientation 1 (normal): original bytes returned untouched", pf.normalize_photo_to_format(o1, "landscape") == o1)
gray = enc(Image.new("L", (1600, 900), 120), "PNG")
chk("U4 grayscale PNG: no exception, bytes untouched", pf.normalize_photo_to_format(gray, "landscape") == gray)
print("FAILURES:", F)
sys.exit(1 if F else 0)
