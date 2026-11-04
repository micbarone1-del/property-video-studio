"""test_photo_metrics.py - offline checks of the measured sharpness stored next to the quality verdict (2026-11-04)."""
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import types
for _n in ("anthropic", "fal_client", "moviepy"):
    if _n not in sys.modules:
        sys.modules[_n] = types.ModuleType(_n)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: None)
import numpy as np
from PIL import Image
import photo_metrics as pm
import listing_scraper as ls
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}"))
    fails += 0 if c else 1
rng = np.random.default_rng(1)
sharp = Image.fromarray(rng.integers(0, 255, (1500, 2000, 3), dtype="uint8"))
soft = sharp.resize((200, 150)).resize((2000, 1500))
a, b = pm.sharpness(sharp), pm.sharpness(soft)
check("P1 a detailed picture measures far sharper than an enlarged small one", a["lap"] > 100 * b["lap"] and a["detail"] > 10 * b["detail"], (a, b))
buf = io.BytesIO(); sharp.save(buf, "JPEG", quality=90)
check("P2 sharpness_of_bytes reads a JPEG", pm.sharpness_of_bytes(buf.getvalue()).get("lap", 0) > 0)
check("P3 unreadable input gives {} and never raises", pm.sharpness_of_bytes(b"not an image") == {} and pm.sharpness_of_bytes("liv1") == {})
# the filter stores the measure next to the verdict and the audit carries both
ls.fetch_photo_bytes = lambda url, fallback_url=None, timeout=20, attempts=1: {"ok": True, "content": buf.getvalue(), "url_used": url, "used_fallback": False, "error": None}
bc = {"living": [{"url": "u1", "category": "living"}]}
ls.filter_poor_quality_candidates(bc, assess=lambda content, label="": {"verdict": "soft", "call_ok": True}, enforce=False)
p = bc["living"][0]
check("P4 the filter stores the measure next to the verdict (and still enforces nothing here)", p["quality"] == "soft" and p["sharp"].get("lap", 0) > 0 and not p.get("quality_rejected"))
au = ls.build_photo_audit([p])
check("P5 the photo audit carries verdict and measure", au[0]["quality"] == "soft" and au[0]["sharp"]["lap"] == p["sharp"]["lap"])
sys.exit(1 if fails else 0)
