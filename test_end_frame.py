"""End frame (crop of the photo) + experiment budget guard. No network, no real Luma call."""
import io, json, os, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, os.getcwd())
try:
    import fal_client  # noqa
except Exception:
    fc = types.ModuleType("fal_client"); fc.subscribe = lambda *a, **k: {}; fc.upload_file = lambda p: "http://x/y.jpg"; sys.modules["fal_client"] = fc
from PIL import Image
import camera_plan as cp, end_frame as ef

ok_n, fails = 0, []
def check(n, c, e=""):
    global ok_n
    if c: ok_n += 1; print("PASS", n)
    else: fails.append(n); print("FAIL", n, e)

W, H = 1920, 1080
bad = []
for mv, (sc, dx, dy) in cp.END_FRAME_CROP.items():
    b = cp.end_frame_box(mv, W, H)
    l, t, r, bt = b
    if not (0 <= l < r <= W and 0 <= t < bt <= H): bad.append((mv, "outside"))
    if abs((r - l) / (bt - t) - W / H) > 0.01: bad.append((mv, "aspect"))
    if abs((r - l) - round(W * sc)) > 1: bad.append((mv, "scale"))
check("E1 every crop is inside the photo, same aspect ratio, right scale", not bad, bad)
check("E2 every movement with a Luma token has a rule, except the reverse one", set(__import__("video_generation")._LUMA_MOVEMENT_TOKENS) - set(cp.END_FRAME_CROP) == {"reveal_pullback"}, set(__import__("video_generation")._LUMA_MOVEMENT_TOKENS) - set(cp.END_FRAME_CROP))
check("E3 reverse dolly / unknown movement / tiny image -> no box", cp.end_frame_box("reveal_pullback", W, H) is None and cp.end_frame_box("zzz", W, H) is None and cp.end_frame_box("walk_in_explore", 1, 1) is None)
cb = cp.end_frame_box("approach_facade", W, H)
check("E4 centred approach: crop centred", abs((cb[0] + cb[2]) / 2 - W / 2) <= 1 and abs((cb[1] + cb[3]) / 2 - H / 2) <= 1)
l = cp.end_frame_box("walk_in_turn_left", W, H); r = cp.end_frame_box("walk_in_turn_right", W, H)
check("E5 turn left ends left of turn right; both still inside", l[0] < r[0] and l[0] >= 0 and r[2] <= W)
# image op
img = Image.new("RGB", (800, 600), (200, 200, 200)); img.paste((255, 0, 0), (300, 220, 500, 380))   # red block in the centre
buf = io.BytesIO(); img.save(buf, "JPEG"); data = buf.getvalue()
out = ef.make_end_frame_bytes(data, "walk_in_explore")
o = Image.open(io.BytesIO(out))
check("E6 end frame has the same size as the start image", o.size == (800, 600))
red = sum(1 for x in range(0, 800, 10) for y in range(0, 600, 10) if o.getpixel((x, y))[0] > 200 and o.getpixel((x, y))[1] < 80)
red0 = sum(1 for x in range(0, 800, 10) for y in range(0, 600, 10) if img.getpixel((x, y))[0] > 200 and img.getpixel((x, y))[1] < 80)
check("E7 it is a zoom-in on the centre (the centred block gets bigger), nothing new", red > red0 * 1.2, (red, red0))
check("E8 no rule / garbage input -> None, never an exception", ef.make_end_frame_bytes(data, "reveal_pullback") is None and ef.make_end_frame_bytes(b"junk", "walk_in_explore") is None)
# video_generation wiring
vg = open("video_generation.py").read()
check("E9 OFF by default (env PVS_END_FRAME), only the direct Luma call gets it", 'os.environ.get("PVS_END_FRAME", "0")' in vg and vg.count("end_frame_url=end_frame_url") == 1 and "if end_frame and model_tier == \"luma\" and LUMA_DIRECT" in vg)
check("E10 the request carries end_frame only when there is one", '**({"end_frame": {"url": end_frame_url}} if end_frame_url else {})' in vg)

# experiment script: budget guard
tmp = Path(tempfile.mkdtemp()); os.environ["PVS_JOBS_DIR"] = str(tmp)
import importlib, exp_luma as ex
importlib.reload(ex)
(tmp / "_test_scratch").mkdir()
job = tmp / "jobX"; (job / "images").mkdir(parents=True)
Image.new("RGB", (640, 360), (90, 90, 90)).save(job / "images" / "sc_1.jpg")
(job / "job_meta.json").write_text(json.dumps({"scenes_config": [{"scene_id": "sc_1", "pov_movement": "walk_in_explore", "space_type": "large", "caption": "x"}],
                                               "qc_results": [{"scene": 0, "type": "video", "issues": ["sedia nuova"]}]}))
check("E11 estimate = direct price in EUR", abs(ex.est_eur() - 1.10) < 0.01, ex.est_eur())
calls = []
def fake_gen(img, dur, outp, **kw):
    calls.append(kw); Path(outp).write_bytes(b"x"); return True
check("E12 without --go nothing is generated and nothing is spent", ex.cmd_run("jobX", 0, "base", False, fake_gen) == 0 and not calls and ex.spent() == 0)
rc = ex.cmd_run("jobX", 0, "endframe", True, fake_gen)
check("E13 with --go: generates once, end_frame passed True, spend recorded", rc == 0 and len(calls) == 1 and calls[0]["end_frame"] is True and calls[0]["model_tier"] == "luma" and abs(ex.spent() - 1.10) < 0.02, (rc, calls, ex.spent()))
ex.cmd_run("jobX", 0, "base", True, fake_gen)
check("E14 base variant: no end frame", calls[-1]["end_frame"] is False)
# fill up to the cap: 9 runs is 9.9, the 10th must be refused
for _ in range(7):
    ex.cmd_run("jobX", 0, "base", True, fake_gen)
n = len(calls)
check("E15 spent ~9.9 after 9 runs", abs(ex.spent() - 9.9) < 0.05, ex.spent())
rc = ex.cmd_run("jobX", 0, "base", True, fake_gen)
check("E16 the run that would pass EUR 10 is REFUSED and does not call the generator", rc == 3 and len(calls) == n and ex.spent() < 10.0, (rc, ex.spent()))
def failing(img, dur, outp, **kw): return False
ex2 = ex.SPEND.read_text(); before = ex.spent()
check("E17 bad variant refused", ex.cmd_run("jobX", 0, "nope", True, fake_gen) == 2)
check("E18 the script only writes under _test_scratch", "SCRATCH / f\"exp_" in open("exp_luma.py").read() and "rmtree" not in open("exp_luma.py").read() and ".unlink" not in open("exp_luma.py").read())
print(f"\nRESULT: {'ALL PASS' if not fails else fails} ({ok_n}/{ok_n+len(fails)})")
sys.exit(1 if fails else 0)
