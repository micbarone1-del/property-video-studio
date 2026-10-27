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
for mv, (p0, p1) in cp.FRAME_PAIR.items():
    bx = cp.frame_pair_boxes(mv, W, H)
    if not bx: bad.append((mv, "none")); continue
    for (l, t_, r, bt) in bx:
        if not (0 <= l < r <= W and 0 <= t_ < bt <= H): bad.append((mv, "outside"))
        if abs((r - l) / (bt - t_) - W / H) > 0.01: bad.append((mv, "aspect"))
    (a0, a1) = bx
    if (a0[2] - a0[0]) != (a1[2] - a1[0]) or (a0[3] - a0[1]) != (a1[3] - a1[1]): bad.append((mv, "frames differ in size = a zoom"))
    if a0[0] == a1[0]: bad.append((mv, "no sideways sweep"))
check("E1 every pair: both crops inside the photo, same aspect, EQUAL size (no zoom), different position", not bad, bad)
fwd = {"walk_in_explore", "walk_through", "walk_toward", "approach_facade", "approach_reveal", "step_out_onto", "reveal_pullback", "stand_look_around"}
check("E2 forward movements (and the remapped/reverse ones) have NO pair", not (fwd & set(cp.FRAME_PAIR)), fwd & set(cp.FRAME_PAIR))
check("E3 unknown movement / tiny image -> None", cp.frame_pair_boxes("zzz", W, H) is None and cp.frame_pair_boxes("walk_in_gentle", 1, 1) is None)
lt = cp.frame_pair_boxes("walk_in_turn_left", W, H); rt = cp.frame_pair_boxes("walk_in_turn_right", W, H)
check("E4 turn left sweeps right->left, turn right left->right", lt[0][0] > lt[1][0] and rt[0][0] < rt[1][0])
g = cp.frame_pair_boxes("walk_in_gentle", W, H)
check("E5 sweep covers the full free margin (first at the left edge, last at the right edge)", g[0][0] == 0 and g[1][2] == W, g)
img = Image.new("RGB", (800, 600), (200, 200, 200)); img.paste((255, 0, 0), (20, 220, 100, 380))   # red block near the LEFT edge, fully outside the right-hand crop (which starts at x=120)
buf = io.BytesIO(); img.save(buf, "JPEG"); data = buf.getvalue()
pair = ef.make_frame_pair_bytes(data, "walk_in_gentle")
o1, o2 = Image.open(io.BytesIO(pair[0])), Image.open(io.BytesIO(pair[1]))
check("E6 both frames have the same size as the photo", o1.size == (800, 600) and o2.size == (800, 600))
def red(i): return sum(1 for x in range(0, 800, 10) for y in range(0, 600, 10) if i.getpixel((x, y))[0] > 200 and i.getpixel((x, y))[1] < 80)
check("E7 first frame (left part) shows the left object, last frame (right part) does not: a sweep, nothing new", red(o1) > 0 and red(o2) == 0, (red(o1), red(o2)))
check("E8 no rule / garbage input -> None, never an exception", ef.make_frame_pair_bytes(data, "walk_in_explore") is None and ef.make_frame_pair_bytes(b"junk", "walk_in_gentle") is None)

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
(job / "job_meta.json").write_text(json.dumps({"scenes_config": [{"scene_id": "sc_1", "pov_movement": "walk_in_gentle", "space_type": "large", "caption": "x"}],
                                               "qc_results": [{"scene": 0, "type": "video", "issues": ["sedia nuova"]}]}))
check("E11 estimate = direct price in EUR", abs(ex.est_eur() - 1.10) < 0.01, ex.est_eur())
calls = []
def fake_gen(img, dur, outp, **kw):
    calls.append(kw); Path(outp).write_bytes(b"x"); return True
check("E12 without --go nothing is generated and nothing is spent", ex.cmd_run("jobX", 0, "base", False, fake_gen) == 0 and not calls and ex.spent() == 0)
rc = ex.cmd_run("jobX", 0, "pair", True, fake_gen)
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
check("E17b straight variant exists, no end frame, adds the no-rotation text", "straight" in ex.VARIANTS and "no pivoting" in ex.STRAIGHT_ADD and ex.cmd_run("jobX", 0, "straight", False, fake_gen) in (0, 3))
# fresh budget so the cap does not hide these (own temp dir)
tmp2 = Path(tempfile.mkdtemp()); os.environ["PVS_JOBS_DIR"] = str(tmp2); importlib.reload(ex)
(tmp2 / "_test_scratch").mkdir(); (tmp2 / "jobY" / "images").mkdir(parents=True)
Image.new("RGB", (640, 360), (90, 90, 90)).save(tmp2 / "jobY" / "images" / "sc_1.jpg")
(tmp2 / "jobY" / "job_meta.json").write_text(json.dumps({"scenes_config": [{"scene_id": "sc_1", "pov_movement": "walk_in_explore", "space_type": "large"}]}))
import video_generation as _vg
seen = []
def spy(img, dur, outp, **kw):
    seen.append((kw["pov_movement"], kw["end_frame"], _vg._LUMA_RULES, _vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"])); Path(outp).write_bytes(b"x"); return True
_rules0, _tok0 = _vg._LUMA_RULES, _vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"]
ex.cmd_run("jobY", 0, "subtle", True, spy)
check("E17c subtle: movement forced to subtle_rotate, strict rules added, no end frame", seen[-1][0] == "subtle_rotate" and seen[-1][1] is False and ex.STRICT_ADD in seen[-1][2], seen[-1][:2])
_vg._LUMA_RULES = _rules0
ex.cmd_run("jobY", 0, "target", True, spy)
check("E17d target: scene movement kept, its own motion text replaces the parallax one, no-rotation text added", seen[-1][0] == "walk_in_explore" and seen[-1][3] == ex.TARGET_MOTION and "parallax" not in ex.TARGET_MOTION and "never dodge" in ex.TARGET_MOTION and ex.STRAIGHT_ADD in seen[-1][2], seen[-1][0])
_vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"] = _tok0; _vg._LUMA_RULES = _rules0
(tmp2 / "jobF").mkdir(); (tmp2 / "jobF" / "images").mkdir(); Image.new("RGB", (64, 36)).save(tmp2 / "jobF" / "images" / "sc_f.jpg")
(tmp2 / "jobF" / "job_meta.json").write_text(json.dumps({"scenes_config": [{"scene_id": "sc_f", "pov_movement": "walk_in_explore"}]}))
check("E17e pair on a forward movement: refused with no generation and no spend", ex.cmd_run("jobF", 0, "pair", True, fake_gen) == 4)
seen.clear()
ex.cmd_run("jobY", 0, "anchor", True, spy, anchor_ask=lambda p: '"the far wall with the bookshelves".\nextra line')
check("E17f anchor: Claude's phrase (cleaned, first line) goes into the motion text, movement forced to the straight one, no end frame", seen and seen[-1][0] == "walk_in_explore" and seen[-1][1] is False and "toward the far wall with the bookshelves," in seen[-1][3] and "never dodge it" in seen[-1][3], seen[-1][:2] if seen else None)
check("E17g anchor with no answer from Claude: refused, no generation, no spend", ex.cmd_run("jobY", 0, "anchor", True, spy, anchor_ask=lambda p: None) == 5 and len(seen) == 1)
check("E17h anchor_phrase rejects junk (empty / too long)", ex.anchor_phrase("x", ask=lambda p: "") == "" and ex.anchor_phrase("x", ask=lambda p: "a" * 200) == "" and ex.anchor_phrase("x", ask=lambda p: "the window") == "the window")
_vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"] = _tok0; _vg._LUMA_RULES = _rules0
seen.clear()
check("E19a parse 'phrase | side' (quotes/dots cleaned, bad side -> center, junk -> empty)", ex.parse_anchor_side('"the far wall". | Right') == ("the far wall", "right") and ex.parse_anchor_side("a bed | middle") == ("a bed", "center") and ex.parse_anchor_side("a bed") == ("a bed", "center") and ex.parse_anchor_side("") == ("", "") and ex.parse_anchor_side("x" * 120 + " | left") == ("", ""))
check("E19b pan movements turn toward an off-centre anchor, never move forward/sideways", all(("pan to the right" in ex.anchor_motion_for(m, "the doors", "right") and "does not move forward or sideways" in ex.anchor_motion_for(m, "the doors", "right")) for m in ("walk_in_turn_left", "walk_in_turn_right", "subtle_rotate", "stand_look_around")) and "at most 8 degrees" in ex.anchor_motion_for("subtle_rotate", "d", "left") and "at most 12 degrees" in ex.anchor_motion_for("walk_in_turn_left", "d", "left"))
check("E19c centred anchor: turning movements fall back to a push-in (nothing to turn toward)", "push-in toward the doors" in ex.anchor_motion_for("walk_in_turn_left", "the doors", "center") and "push-in" in ex.anchor_motion_for("subtle_rotate", "the doors", "center") and "ten centimetres" in ex.anchor_motion_for("subtle_rotate", "the doors", "center"))
check("E19d sideways movement = short arc around the anchor, anchor stays centred", "arc around the bed" in ex.anchor_motion_for("walk_in_gentle", "the bed", "left") and "to the left" in ex.anchor_motion_for("walk_in_gentle", "the bed", "left") and "to the right" in ex.anchor_motion_for("walk_in_gentle", "the bed", "center") and "stays at the centre" in ex.anchor_motion_for("walk_in_gentle", "the bed", "left"))
check("E19e forward movements (walk_in_explore, outward_view...) = the straight approach text", ex.anchor_motion_for("outward_view", "the view", "right") == ex.ANCHOR_MOTION.format(anchor="the view") and ex.anchor_motion_for("walk_in_explore", "x y", "left") == ex.ANCHOR_MOTION.format(anchor="x y"))
(tmp2 / "jobM").mkdir(); (tmp2 / "jobM" / "images").mkdir(); Image.new("RGB", (64, 36)).save(tmp2 / "jobM" / "images" / "sc_m.jpg")
(tmp2 / "jobM" / "job_meta.json").write_text(json.dumps({"scenes_config": [{"scene_id": "sc_m", "pov_movement": "walk_in_turn_left", "space_type": "bedroom"}]}))
def spy2(img, dur, outp, **kw):
    seen.append((kw["pov_movement"], kw["end_frame"], _vg._LUMA_RULES, _vg._LUMA_MOVEMENT_TOKENS.get(kw["pov_movement"]))); Path(outp).write_bytes(b"x"); return True
_tok_l = _vg._LUMA_MOVEMENT_TOKENS["walk_in_turn_left"]
ex.cmd_run("jobM", 0, "anchormove", True, spy2, anchor_ask=lambda p: "the wardrobe wall | left")
check("E19f anchormove: scene movement KEPT, its text replaced by the anchor-relative one, strict rules, no end frame", seen and seen[-1][0] == "walk_in_turn_left" and seen[-1][1] is False and "pan to the left" in seen[-1][3] and "the wardrobe wall" in seen[-1][3] and ex.STRICT_ADD in seen[-1][2], seen[-1][:2] if seen else None)
_vg._LUMA_MOVEMENT_TOKENS["walk_in_turn_left"] = _tok_l; _vg._LUMA_RULES = _rules0
n = len(seen)
check("E19g anchormove with no answer: refused, no generation, no spend", ex.cmd_run("jobM", 0, "anchormove", True, spy2, anchor_ask=lambda p: None) == 5 and len(seen) == n)
_vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"] = _tok0; _vg._LUMA_RULES = _rules0
check("E17 bad variant refused", ex.cmd_run("jobX", 0, "nope", True, fake_gen) == 2)
check("E18 the script only writes under _test_scratch", "SCRATCH / f\"exp_" in open("exp_luma.py").read() and "rmtree" not in open("exp_luma.py").read() and ".unlink" not in open("exp_luma.py").read())
print(f"\nRESULT: {'ALL PASS' if not fails else fails} ({ok_n}/{ok_n+len(fails)})")
sys.exit(1 if fails else 0)
