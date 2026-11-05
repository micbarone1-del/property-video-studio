"""test_exp_outside.py - offline checks of exp_outside on synthetic clips (no network, no spend)."""
import os, sys, tempfile
from pathlib import Path
import cv2, numpy as np
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_VOLUME_SCRATCH"] = str(tmp)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_outside as eo
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
def texture(seed):
    rng = np.random.default_rng(seed)
    b = cv2.GaussianBlur(rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8), (0, 0), 3)
    for _ in range(160):
        x, y = int(rng.integers(0, 1500)), int(rng.integers(0, 800))
        cv2.rectangle(b, (x, y), (x + int(rng.integers(20, 90)), y + int(rng.integers(20, 90))), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
    return b
base, other = texture(3), texture(11)
def make(name, fn, n=120, fps=24):
    p = tmp / name
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps, (480, 270))
    for i in range(n):
        w.write(fn(i / (n - 1)))
    w.release()
    return p
def crop(src, x0, y0, cw, ch):
    return cv2.resize(src[int(y0):int(y0 + ch), int(x0):int(x0 + cw)], (480, 270))
cx, cy, W0, H0 = 800, 450, 800, 450
still = make("still.mp4", lambda t: crop(base, cx - W0 / 2, cy - H0 / 2, W0, H0))
push = make("push.mp4", lambda t: crop(base, cx - W0 * (1 - 0.12 * t) / 2, cy - H0 * (1 - 0.12 * t) / 2, W0 * (1 - 0.12 * t), H0 * (1 - 0.12 * t)))
pan = make("pan.mp4", lambda t: crop(base, cx - W0 / 2 + 400 * t, cy - H0 / 2, W0, H0))
back = make("back.mp4", lambda t: crop(base, cx - W0 * (1 + 0.5 * t) / 2, cy - H0 * (1 + 0.5 * t) / 2, W0 * (1 + 0.5 * t), H0 * (1 + 0.5 * t)))
K = np.array([[1200.0, 0, 800], [0, 1200.0, 450], [0, 0, 1]])
def yawframe(t):
    a = np.deg2rad(25 * t)
    R = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    return crop(cv2.warpPerspective(base, K @ R @ np.linalg.inv(K), (1600, 900)), 400, 225, 800, 450)
yaw = make("yaw.mp4", yawframe)
swap = make("swap.mp4", lambda t: crop(base if t < 0.5 else other, cx - W0 / 2, cy - H0 / 2, W0, H0))     # the second half is a DIFFERENT picture (an invented room)
r = {k: eo.clip(v) for k, v in dict(still=still, push=push, pan=pan, back=back, yaw=yaw, swap=swap).items()}
for k, v in r.items():
    print(k, v)
check("O1 all clips measured", all(v.get("ok") for v in r.values()))
check("O2 still: nothing outside", r["still"]["outside_max"] is not None and r["still"]["outside_max"] < 0.03 and r["still"]["unreg"] == 0)
check("O3 a 12% push-in stays inside the original field of view", r["push"]["outside_max"] < 0.05)
check("O4 a pan of half a frame: about half of the frame is outside", 0.3 < r["pan"]["outside_max"] < 0.7)
check("O5 pulling back 50%: a large share is outside", r["back"]["outside_max"] > 0.3)
check("O6 a 25 degree yaw: a large share is outside", r["yaw"]["outside_max"] > 0.2)
check("O7 a different picture in the second half: frames that cannot be registered count as 1.0 in outside_cons", r["swap"]["unreg"] > 0 and r["swap"]["outside_cons"] == 1.0)
check("O8 the order push < yaw, pan, back holds", r["push"]["outside_max"] + 0.15 < min(r["yaw"]["outside_max"], r["pan"]["outside_max"], r["back"]["outside_max"]))
blank = make("blank.mp4", lambda t: np.zeros((270, 480, 3), np.uint8), n=60)
check("O9 a blank clip claims nothing", eo.clip(blank).get("outside_max") is None)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
