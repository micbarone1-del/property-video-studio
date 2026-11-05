"""test_exp_rotation.py - offline checks of exp_rotation on synthetic clips (no network, no spend)."""
import os, sys, tempfile
from pathlib import Path
import cv2, numpy as np
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_VOLUME_SCRATCH"] = str(tmp)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_rotation as er
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
rng = np.random.default_rng(3)
base = cv2.GaussianBlur(rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8), (0, 0), 3)
for _ in range(120):                       # texture to track: random filled rectangles
    x, y = int(rng.integers(0, 1500)), int(rng.integers(0, 800))
    cv2.rectangle(base, (x, y), (x + int(rng.integers(20, 90)), y + int(rng.integers(20, 90))), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
def make(name, fn, n=120, fps=24):
    p = tmp / name
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps, (480, 270))
    for i in range(n):
        x0, y0, cw, ch = fn(i / (n - 1))
        w.write(cv2.resize(base[int(y0):int(y0 + ch), int(x0):int(x0 + cw)], (480, 270)))
    w.release()
    return p
cx, cy, W0, H0 = 800, 450, 800, 450
still = make("still.mp4", lambda t: (cx - W0 / 2, cy - H0 / 2, W0, H0))
push = make("push.mp4", lambda t: (cx - W0 * (1 - 0.12 * t) / 2, cy - H0 * (1 - 0.12 * t) / 2, W0 * (1 - 0.12 * t), H0 * (1 - 0.12 * t)))
pan = make("pan.mp4", lambda t: (cx - W0 / 2 + 400 * t, cy - H0 / 2, W0, H0))
back = make("back.mp4", lambda t: (cx - W0 * (1 + 0.5 * t) / 2, cy - H0 * (1 + 0.5 * t) / 2, W0 * (1 + 0.5 * t), H0 * (1 + 0.5 * t)))
ms, mp, mn, mb = er.clip(still), er.clip(push), er.clip(pan), er.clip(back)
print(ms, mp, mn, mb)
check("R1 all four clips measured", all(m.get("ok") for m in (ms, mp, mn, mb)))
check("R2 still: nothing new", ms["new_frac"] < 0.03)
check("R3 a 12% push-in reveals (almost) nothing new", mp["new_frac"] < 0.05 and mp["zoom_net"] > 1.05)
check("R4 a pan of half a frame reveals a lot of new content", mn["new_frac"] > 0.3 and abs(mn["pan_frac"]) > 0.3)
check("R5 pulling back 50% reveals new content and zoom_net < 1", mb["new_frac"] > 0.2 and mb["zoom_net"] < 0.95)
check("R6 pan >> push-in, pullback >> push-in", mn["new_frac"] > mp["new_frac"] + 0.25 and mb["new_frac"] > mp["new_frac"] + 0.15)
check("R8 new_max is the largest share over the clip (>= the last one) and clean for a push-in", mp["new_max"] < 0.06 and mn["new_max"] >= mn["new_frac"] - 1e-9)
blank = tmp / "blank.mp4"
w = cv2.VideoWriter(str(blank), cv2.VideoWriter_fourcc(*"mp4v"), 24, (480, 270))
for _ in range(60):
    w.write(np.zeros((270, 480, 3), np.uint8))
w.release()
check("R7 an untrackable clip claims nothing", er.clip(blank).get("ok") is False)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
