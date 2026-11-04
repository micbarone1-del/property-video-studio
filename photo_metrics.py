"""photo_metrics.py - measured (not judged) sharpness of a photo. ONE implementation, used by the intake (listing_scraper) and by photo_sheet.py (2026-11-04).
No opinion and no threshold here: the numbers are stored next to the quality judge's verdict so the filter can be calibrated against them (Michele: 'le tue misure valgono di piu').
"""


def sharpness(im) -> dict:
    """{'lap': edge strength at 1024 px width (higher = sharper; plain walls give low values), 'detail': mean loss going to half size and back (about 0 = no real detail)}.
    Returns {} when it cannot be measured (never raises)."""
    try:
        import numpy as np
        g = im.convert("L")
        g = g.resize((1024, max(1, round(g.height * 1024 / g.width))))
        a = np.asarray(g, dtype="float32")
        lap = a[1:-1, 1:-1] * 4 - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
        half = np.asarray(g.resize((512, max(1, g.height // 2))).resize(g.size), dtype="float32")
        return {"lap": round(float(lap.var()), 1), "detail": round(float(np.abs(a - half).mean()), 2)}
    except Exception:
        return {}


def sharpness_of_bytes(content: bytes) -> dict:
    try:
        import io
        from PIL import Image
        return sharpness(Image.open(io.BytesIO(content)).convert("RGB"))
    except Exception:
        return {}
