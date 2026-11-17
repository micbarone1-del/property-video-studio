"""Tests of agency_logo.py (partner logo: white background keyed out, safe download rules, shared store). Prints PASS/FAIL."""
import io, os, sys, tempfile, json
from PIL import Image, ImageDraw
import agency_logo as al

fails = 0
def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (" " + str(info) if info and not cond else ""))
    if not cond: fails += 1

def jpeg_logo(bg=(255, 255, 255)):
    im = Image.new("RGB", (472, 461), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((60, 60, 410, 400), fill=(20, 60, 140))          # coloured disc
    d.rectangle((200, 200, 280, 260), fill=(255, 255, 255))     # a WHITE shape inside the logo
    b = io.BytesIO(); im.save(b, "JPEG", quality=90); return b.getvalue()

# L1 white-background JPEG: corners transparent, inside white kept opaque
img, note = al.prepare_partner_logo(jpeg_logo())
check("L1 corners transparent", all(img.getpixel(p)[3] == 0 for p in [(0, 0), (471, 0), (0, 460), (471, 460)]))
check("L1 disc opaque", img.getpixel((150, 230))[3] == 255)
check("L1 white inside the logo kept", img.getpixel((240, 230))[3] == 255, img.getpixel((240, 230)))
check("L1 note", "transparent" in note, note)
# L2 bbox of the result is the disc, not the whole canvas (the assembly crops to getbbox)
bb = img.getbbox()
check("L2 bbox is the logo", bb and bb[0] > 40 and bb[2] < 430, bb)
# L3 coloured background is left alone
img3, note3 = al.prepare_partner_logo(jpeg_logo(bg=(30, 120, 60)))
check("L3 coloured background not keyed", img3.getpixel((0, 0))[3] == 255 and "kept" in note3, note3)
# L4 a real PNG with alpha is kept as it is
png = Image.new("RGBA", (200, 200), (0, 0, 0, 0)); ImageDraw.Draw(png).ellipse((20, 20, 180, 180), fill=(200, 0, 0, 255))
b = io.BytesIO(); png.save(b, "PNG")
img4, note4 = al.prepare_partner_logo(b.getvalue())
check("L4 alpha logo kept", note4 == "alpha kept" and img4.getpixel((0, 0))[3] == 0)
# L5 not an image / too small
for name, data in (("text", b"hello"), ("tiny", (lambda: (lambda x: (x.save(x2 := io.BytesIO(), "PNG"), x2.getvalue())[1])(Image.new("RGB", (8, 8), "white")))())):
    try:
        al.prepare_partner_logo(data); ok = False
    except al.LogoError:
        ok = True
    check("L5 rejects " + name, ok)
# L6 download rules (no network needed: rejected before any request)
for url in ("http://relinx.it/logo.png", "https://127.0.0.1/logo.png", "https://localhost/x", "https://10.0.0.5/x", "ftp://relinx.it/x", "", None):
    try:
        al.fetch_logo_bytes(url); ok = False
    except al.LogoError:
        ok = True
    check("L6 refuses " + repr(url), ok)
# L7 store writes the file and the path goes to the agency (shared with the upload endpoint)
import cost_model
tmp = tempfile.mkdtemp()
from pathlib import Path; cost_model.AGENCIES_FILE = Path(tmp) / "agencies.json"
ag = cost_model.create_agency("Test Agency L7")
path = al.store_logo_png(ag["agency_id"], img, tmp)
check("L7 file written", os.path.exists(path) and path.endswith("clients/%s/logo.png" % ag["agency_id"]), path)
check("L7 path recorded on the agency", cost_model.get_agency(ag["agency_id"]).get("logo_path") == path)
# L8 update_from_partner_url never raises and reports a failure
r = al.update_from_partner_url(ag["agency_id"], "http://nope.invalid/x", tmp)
check("L8 failure reported, logo untouched", r["ok"] is False and cost_model.get_agency(ag["agency_id"]).get("logo_path") == path, r)
# L9 the request model accepts the field, the intake uses the shared module, the endpoint too
src = open("api_server.py").read()
check("L9 field in the request model", "agency_logo_url: str | None" in src)
check("L9 intake uses update_from_partner_url", src.count("agency_logo.update_from_partner_url") == 1)
check("L9 upload endpoint uses the shared store", "agency_logo.store_logo_png(agency_id, img, BASE_DIR)" in src and "logos_dir" not in src)
print("RESULT", "ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
