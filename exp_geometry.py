"""
exp_geometry.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-10-30). Free, local, no API.

Measures, with plain image geometry (SIFT features + a similarity fit, OpenCV, already a project dependency), what really happened
between a START frame and an END frame, instead of trusting a language model's estimate:
  scale        how many times larger the content got (1.0 = no forward move)
  rotation     degrees (should be ~0: the camera must not turn)
  FOE          the point everything expands from, as a fraction of the picture size from the centre (0,0 = centre).
               A camera that moves straight along its viewing axis expands from the CENTRE; an end frame made by walking toward a target
               that is NOT at the centre expands from that target and LOOKS like a sideways slide.
  inside       share of the END frame whose content is already inside the START frame (1.0 = the end view stays inside the start view)
  footprint    the END frame outlined on the START picture, saved as an image in jobs/_test_scratch (geom_<label>.jpg)
One global similarity model is an approximation (a room has depth, nearer things move more): read the numbers as an indicator.

  python3 exp_geometry.py LABEL START_IMAGE END_IMAGE
"""
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

OUT_DIR = Path(os.environ.get("PVS_SCRATCH_DIR", "/var/www/property-video-studio/jobs/_test_scratch"))
PUBLIC = "https://api.propertyvideostudioai.com/test-scratch/"
WORK_W = 800


def _nonrigid(a, b, M) -> dict:
    """How much of the END frame does NOT follow the single global move (2026-10-30, added after two end frames that passed the gate gave clips with a
    zig-zag path and a deformed door / radiator). Start is warped onto the end frame with the fitted similarity, then dense optical flow measures what is
    still moving: pixels (at 800 px width) that move differently from the global model = objects that changed or a non-rigid view change.
    A room has depth, so a part of this residual is normal parallax: compare frames, do not read it as an absolute verdict."""
    try:
        H, W = b.shape[:2]
        ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        wa = cv2.warpAffine(ga, M, (W, H))
        valid = cv2.warpAffine(np.full_like(ga, 255), M, (W, H)) > 250
        valid = cv2.erode(valid.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
        if valid.mean() < 0.2:
            return {"resid_diff": None, "resid_flow_med": None, "resid_flow_p90": None}
        d = np.abs(cv2.GaussianBlur(wa, (5, 5), 0).astype(np.float32) - cv2.GaussianBlur(gb, (5, 5), 0).astype(np.float32))[valid]
        flow = cv2.calcOpticalFlowFarneback(wa, gb, None, 0.5, 4, 25, 3, 5, 1.1, 0)
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)[valid]
        return {"resid_diff": round(float(d.mean()), 1), "resid_flow_med": round(float(np.median(mag)), 2), "resid_flow_p90": round(float(np.percentile(mag, 90)), 2)}
    except Exception as e:
        return {"resid_error": str(e)[:80]}


def analyse(start_path, end_path, overlay_path=None) -> dict:
    a = cv2.imread(str(start_path))
    b = cv2.imread(str(end_path))
    if a is None or b is None:
        return {"ok": False, "reason": "image not readable"}
    k = WORK_W / a.shape[1]
    a = cv2.resize(a, (WORK_W, max(1, round(a.shape[0] * k))))
    b = cv2.resize(b, (a.shape[1], a.shape[0]))          # end resized to the start's size (the clip generator does the same)
    H, W = a.shape[:2]
    sift = cv2.SIFT_create(nfeatures=3000)
    ka, da = sift.detectAndCompute(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), None)
    kb, db = sift.detectAndCompute(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), None)
    if da is None or db is None or len(ka) < 20 or len(kb) < 20:
        return {"ok": False, "reason": "too few features"}
    raw = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [m for m, n in (p for p in raw if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 12:
        return {"ok": False, "reason": f"too few matches ({len(good)})"}
    pa = np.float32([ka[m.queryIdx].pt for m in good])
    pb = np.float32([kb[m.trainIdx].pt for m in good])
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if M is None:
        return {"ok": False, "reason": "no stable transform"}
    inl = inl.ravel().astype(bool)
    A, t = M[:, :2], M[:, 2]                              # x_end = A x_start + t
    s = float(math.sqrt(abs(np.linalg.det(A))))
    rot = math.degrees(math.atan2(A[1, 0], A[0, 0]))
    try:
        c = np.linalg.solve(np.eye(2) - A, t)             # fixed point of the map = focus of expansion
        foe = [round(float((c[0] - W / 2) / W), 3), round(float((c[1] - H / 2) / H), 3)]
    except np.linalg.LinAlgError:
        foe = [None, None]
    # share of the end frame that lies inside the start frame
    gx, gy = np.meshgrid(np.linspace(0, W - 1, 60), np.linspace(0, H - 1, 60))
    pts = np.stack([gx.ravel(), gy.ravel()], axis=1)
    back = (np.linalg.inv(A) @ (pts - t).T).T
    inside = float(np.mean((back[:, 0] >= 0) & (back[:, 0] <= W - 1) & (back[:, 1] >= 0) & (back[:, 1] <= H - 1)))
    res = {"ok": True, "matches": len(good), "inliers": int(inl.sum()), "scale": round(s, 3), "rotation_deg": round(rot, 2),
           "foe_x": foe[0], "foe_y": foe[1], "inside": round(inside, 3), "inlier_ratio": round(float(inl.sum()) / len(good), 3)}
    res.update(_nonrigid(a, b, M))
    if overlay_path:
        corners = np.array([[0, 0], [W, 0], [W, H], [0, H]], dtype=np.float32)
        poly = (np.linalg.inv(A) @ (corners - t).T).T
        img = a.copy()
        cv2.polylines(img, [poly.astype(np.int32)], True, (0, 0, 255), 4)
        if foe[0] is not None:
            cv2.circle(img, (int(W / 2 + foe[0] * W), int(H / 2 + foe[1] * H)), 10, (0, 255, 255), -1)
        cv2.circle(img, (W // 2, H // 2), 8, (255, 255, 0), 2)
        cv2.putText(img, "red = end frame outline | yellow = expansion point | cyan = centre", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imwrite(str(overlay_path), img)
    return res


def verdict(r: dict) -> str:
    if not r.get("ok"):
        return "NOT MEASURABLE: " + r.get("reason", "?")
    notes = []
    notes.append("clear forward move" if r["scale"] >= 1.12 else "almost no forward move (scale < 1.12)")
    if abs(r["rotation_deg"]) > 2.5:
        notes.append(f"the camera turned ({r['rotation_deg']} deg)")
    fx, fy = r["foe_x"], r["foe_y"]
    if fx is None or max(abs(fx), abs(fy)) > 0.2:
        notes.append("expansion point far from the centre: it looks like a SIDEWAYS slide, not a straight advance")
    elif max(abs(fx), abs(fy)) > 0.1:
        notes.append("expansion point a little off centre")
    else:
        notes.append("expansion point near the centre: straight advance")
    notes.append("end view stays inside the start view" if r["inside"] >= 0.97 else f"only {round(r['inside'] * 100)}% of the end view is inside the start view")
    return "; ".join(notes)


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    label, start, end = sys.argv[1:4]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"geom_{label}.jpg"
    r = analyse(start, end, out)
    print(json.dumps(r))
    print("READING:", verdict(r))
    if r.get("ok"):
        print("OUTLINE:", PUBLIC + out.name)


if __name__ == "__main__":
    main()
