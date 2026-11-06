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


def relative_quality(im) -> dict:
    """2026-11-06: scale-free measures that do not depend on WHAT is in the photo (a plain white wall gives low lap/detail even when in focus; these compare
    the photo with itself). MEASUREMENT ONLY until calibrated (calibrate_quality.py --objective). Returns {} when it cannot be measured (never raises).
      fine_mid : gradient energy at 1024 px width divided by the same at 512 px. Sharp natural photo ~0.55-0.9; blurred or enlarged from a small picture
                 ~0.5 or less (the finest scale holds nothing the half scale does not).
      period   : on a centre patch at the REAL pixels, the strongest repetition of edges every k pixels (k = 2..7), best offset: edge strength on the
                 grid lines divided by the strength between them. ~1.0 = no grid; enlarged pixels (nearest/bilinear from a smaller picture) give a clear peak.
      period_k : the k of that peak."""
    try:
        import numpy as np
        g = im.convert("L")
        w1 = 1024
        a = np.asarray(g.resize((w1, max(2, round(g.height * w1 / g.width)))), dtype="float32")
        b = np.asarray(g.resize((w1 // 2, max(2, round(g.height * (w1 // 2) / g.width)))), dtype="float32")
        e1 = float(np.abs(np.diff(a, axis=1)).mean()); e2 = float(np.abs(np.diff(b, axis=1)).mean())
        fine_mid = round(e1 / e2, 3) if e2 > 0.05 else None
        arr = np.asarray(g, dtype="float32")
        h, w = arr.shape
        ph, pw = min(h, 768), min(w, 1024)
        patch = arr[(h - ph) // 2:(h - ph) // 2 + ph, (w - pw) // 2:(w - pw) // 2 + pw]
        dh = np.abs(np.diff(patch, axis=1)); dv = np.abs(np.diff(patch, axis=0))
        best, best_k = 1.0, None
        for k in range(2, 8):
            sc = []
            for d, axis in ((dh, 1), (dv, 0)):
                prof = d.mean(axis=1 - axis)
                idx = np.arange(prof.shape[0]) % k
                m = np.array([prof[idx == o].mean() for o in range(k)])
                others = (m.sum() - m.max()) / (k - 1)
                sc.append(m.max() / others if others > 1e-6 else 1.0)
            v = (sc[0] + sc[1]) / 2
            if v > best:
                best, best_k = v, k
        return {"fine_mid": fine_mid, "period": round(float(best), 3), "period_k": best_k}
    except Exception:
        return {}


def relative_quality_of_bytes(content: bytes) -> dict:
    try:
        import io
        from PIL import Image
        return relative_quality(Image.open(io.BytesIO(content)).convert("RGB"))
    except Exception:
        return {}
