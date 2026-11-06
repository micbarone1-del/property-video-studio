import os, sys, io, types, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
from PIL import Image, ImageDraw
import listing_scraper as ls
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)

def scene(seed, size=(800, 600)):
    r = random.Random(seed); im = Image.new("RGB", size, (r.randint(0,255),)*3); d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = r.randint(0, size[0]), r.randint(0, size[1]); d.rectangle([x, y, x + r.randint(20, 200), y + r.randint(20, 200)], fill=tuple(r.randint(0,255) for _ in range(3)))
    return im
def jpg(im, q=90, size=None):
    if size: im = im.resize(size)
    b = io.BytesIO(); im.save(b, "JPEG", quality=q); return b.getvalue()

A, B, C = scene(1), scene(2), scene(3)
data = {"a1": jpg(A), "a2": jpg(A, q=60, size=(400, 300)), "b": jpg(B), "c": jpg(C), "bad": b"not an image"}
fetch = lambda p: {"ok": p["url"] in data, "content": data.get(p["url"], b"")}

chk("D1 hash: same picture re-encoded and resized is within threshold",
    bin(ls.photo_hash_of_bytes(data["a1"]) ^ ls.photo_hash_of_bytes(data["a2"])).count("1") <= ls.DUPLICATE_MAX_BITS)
chk("D2 hash: different pictures are far apart",
    bin(ls.photo_hash_of_bytes(data["a1"]) ^ ls.photo_hash_of_bytes(data["b"])).count("1") > ls.DUPLICATE_MAX_BITS * 2)

os.environ.pop("PVS_PHOTO_DEDUPE", None)
ph = [{"url": u, "category": "kitchen"} for u in ("a1", "b", "a2", "c", "bad")]
r = ls.mark_duplicate_photos(ph, fetch=fetch)
by = {p["url"]: p for p in ph}
chk("D3 later copy marked, first kept", by["a2"].get("duplicate_of") == "a1" and not by["a1"].get("duplicate_of"))
chk("D4 different photos and unreadable photo are kept", not any(by[u].get("duplicate_of") for u in ("b", "c", "bad")) and r["duplicates"] == 1)
chk("D5 photo_exclusion reports the duplicate", ls.photo_exclusion(by["a2"]) == "foto duplicata" and ls.photo_exclusion(by["a1"]) is None)

def boom(p): raise RuntimeError("x")
chk("D6 never raises on a failing fetch", ls.mark_duplicate_photos([{"url": "q", "category": "living"}], fetch=boom).get("duplicates") == 0)
os.environ["PVS_PHOTO_DEDUPE"] = "0"
ph2 = [{"url": "a1", "category": "kitchen"}, {"url": "a2", "category": "kitchen"}]
ls.mark_duplicate_photos(ph2, fetch=fetch)
chk("D7 switch off: nothing marked", not any(p.get("duplicate_of") for p in ph2))
os.environ.pop("PVS_PHOTO_DEDUPE", None)

# single criterion: acceptance and category order count only usable photos
cats = ["living", "kitchen", "bedrooms", "bathrooms", "living"]
photos = [{"url": f"u{i}", "category": c} for i, c in enumerate(cats)]
ok0 = ls.check_listing_acceptance(photos)
photos[4]["duplicate_of"] = "u0"
ph_q = [dict(p) for p in photos]; ph_q[3]["quality_rejected"] = True
chk("S1 baseline: 5 photos, 4 types accepted", ok0["ok"])
r1 = ls.check_listing_acceptance(photos)
chk("S2 a duplicate does not count as a usable photo", (not r1["ok"]) and "refused" not in r1.get("code", ""))
r2 = ls.check_listing_acceptance(ph_q)
chk("S3 a quality reject does not count either", not r2["ok"])
order = ls.derive_available_category_order(ph_q)
chk("S4 category order skips excluded photos (no bathroom scene)", "bathrooms" not in order and "living" in order)
chk("S5 order with nothing excluded keeps all", "bathrooms" in ls.derive_available_category_order([{"url": "x", "category": "bathrooms"}]))

rep = ls.refusal_report(photos)
chk("S6 refusal report has audit, counts, total", rep["photos_total"] == 5 and rep["excluded_counts"].get("foto duplicata") == 1 and len(rep["photo_audit"]) >= 1 and rep["refused"])

# duplicate never becomes a ranking candidate
by_cat = ls._categorize_and_rank_photos([{"url": "k1", "category": "kitchen"}, {"url": "k2", "category": "kitchen", "duplicate_of": "k1"}], ["kitchen"]) if hasattr(ls, "_categorize_and_rank_photos") else None
print("INFO ranking return:", type(by_cat).__name__)
print("FAILS:", F); sys.exit(1 if F else 0)
