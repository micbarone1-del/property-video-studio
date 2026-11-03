"""Movement director (2026-11-02). Zero cost, no network, no key: Claude is faked. Run: python3 test_movement_director.py (numbered PASS/FAIL)."""
import json, os, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
from PIL import Image
import movement_director as md
import video_generation as vg
import camera_plan
import described_view as dv
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}"))
    fails += 0 if c else 1

FWD = {"view": "interior", "move": "forward", "target": "the far window", "travel": "medium", "risk": "low",
       "sentence": "slow straight forward camera push-in toward the far window, the camera keeps the same height and direction and stops well before it",
       "bulky_near_camera": False, "mirror_visible": False, "reason": "deep room"}
ROT = {"view": "interior", "move": "rotate_right", "target": "centre of the frame", "travel": "short", "risk": "low",
       "sentence": "slow gentle rotation to the right of at most 8 degrees, the camera stays in place", "bulky_near_camera": False, "mirror_visible": False, "reason": "x"}
LAT = dict(ROT, move="lateral_left", sentence="very slow glide of less than half a metre to the left at constant speed")
DEEP = {"space_type": "large", "depth": "deep", "output_format": "landscape"}
SHAL = {"space_type": "medium", "depth": "shallow", "output_format": "landscape"}

# A. switch
os.environ.pop("PVS_DIRECTOR", None)
check("MD1 off by default", not md.enabled())
os.environ["PVS_DIRECTOR"] = "1"
check("MD2 PVS_DIRECTOR=1 turns it on", md.enabled())

# B. validation: accepted
p, pr = md.validate(dict(FWD), DEEP)
check("MD3 a good forward answer is accepted as Claude's plan, tail added", p and p["source"] == "claude" and p["move"] == "forward" and md.TAIL in p["sentence"] and not pr, (p, pr))
check("MD4 travel medium in a deep room -> crop scale 1.25", p["scale"] == 1.25)
p, _ = md.validate(dict(FWD, travel="long"), dict(DEEP, depth="medium"))
check("MD5 travel is capped by depth (long in a medium room -> medium)", p["travel"] == "medium" and p["scale"] == 1.25)
p, _ = md.validate(dict(FWD, travel="long"), dict(DEEP, space_type="outdoor"))
check("MD6 outdoor scenes are held to short (facade gate case)", p["travel"] == "short")
p, _ = md.validate(dict(FWD, travel="long", bulky_near_camera=True), DEEP)
check("MD7 Claude's own 'bulky object near the camera' caps travel to short", p["travel"] == "short")

# C. validation: refused
for n, bad in (("MD8 unknown move", dict(FWD, move="orbit")), ("MD9 banned word (zoom)", dict(FWD, sentence="slow zoom toward the far window")),
               ("MD10 empty sentence", dict(FWD, sentence="")), 
                ("MD13 sentence too long", dict(FWD, sentence="forward " + "word " * 80)),
               ("MD14 forward without saying forward", dict(FWD, sentence="slowly look at the far window")), ("MD15 unknown risk", dict(FWD, risk="maybe"))):
    p, pr = md.validate(bad, DEEP)
    check(n + " -> refused", p is None and pr, (p, pr))
p, pr = md.validate("not a dict", DEEP)
check("MD16 non-object answer refused", p is None)

# D. sideways moves: Claude's decision inside the environment gates
p, pr = md.validate(dict(ROT), DEEP)
check("MD17 rotation allowed in a deep landscape room when Claude says risk low", p and p["move"] == "rotate_right" and p["scale"] == 1.1 and p["source"] == "claude", (p, pr))
p, pr = md.validate(dict(LAT), DEEP)
check("MD18 lateral glide allowed under the same conditions", p and p["move"] == "lateral_left" and p["source"] == "claude", (p, pr))
p, _ = md.validate(dict(ROT, risk="medium"), DEEP)
check("MD19 Claude's own risk not low -> safe plan, not the sideways move", p["source"] == "fallback" and p["move"] == "forward" and "risk" in p["adjusted"], p)
for n, h in (("MD20 shallow room", SHAL), ("MD21 portrait frame", dict(DEEP, output_format="portrait")), ("MD22 small space", dict(DEEP, space_type="small")),
             ("MD23 mirror in view (analysis)", dict(DEEP, reflective_surface="large")), ("MD24 foreground risk", dict(DEEP, foreground_risk=True))):
    p, _ = md.validate(dict(LAT), h)
    check(n + " -> sideways refused, safe plan", p["source"] == "fallback" and p["move"] in ("forward", "static") and "not allowed" in p["adjusted"], p)
p, _ = md.validate(dict(ROT, mirror_visible=True), DEEP)
check("MD25 a mirror that only Claude sees also closes the gate (the bedroom case)", p["source"] == "fallback", p)
p, pr = md.validate(dict(ROT, sentence="slow rotation to the right of at most 30 degrees"), DEEP)
check("MD26 rotation over 12 degrees refused", p is None and pr, (p, pr))
p, pr = md.validate(dict(ROT, sentence="slow rotation to the right"), DEEP)
check("MD27 rotation without a degree limit refused", p is None and pr)
p, pr = md.validate(dict(LAT, sentence="very slow glide of less than half a metre to the right"), DEEP)
check("MD28 lateral glide whose sentence says the other side refused", p is None and pr)

# E. safe plans, static, aerial
sp = md.safe_plan(DEEP, "x")
check("MD29 safe plan in a deep room = the positive push-in toward the centre (no negations)", sp["move"] == "forward" and sp["sentence"] == md.forward_sentence(camera_plan.CENTRE_ANCHOR) and "never" not in sp["sentence"] and sp["source"] == "fallback")
sp = md.safe_plan(SHAL, "x")
check("MD30 safe plan in a shallow room = the almost static token", sp["move"] == "static" and sp["sentence"] == vg._LUMA_MOVEMENT_TOKENS["subtle_rotate"])
p, _ = md.validate(dict(FWD, view="aerial"), DEEP)
check("MD31 an aerial view is made static and flagged aerial", p["move"] == "static" and p["aerial"] is True and p["scale"] == md.STATIC_SCALE, p)
p, _ = md.validate(dict(FWD, move="static", sentence="almost static shot with imperceptibly subtle depth parallax"), DEEP)
check("MD32 a static plan uses the proven static token, not free text", p["sentence"] == vg._LUMA_MOVEMENT_TOKENS["subtle_rotate"])

# F. plan(): history, fallback, no answer, rework feedback, cost merge
tmp = Path(tempfile.mkdtemp())
photo = tmp / "p.jpg"; Image.new("RGB", (400, 300), (120, 130, 140)).save(photo)
calls = []
def fake(answer):
    def _c(photo_path, prompt, usage):
        calls.append(prompt)
        usage.update({"input_tokens": 1000, "output_tokens": 200, "calls": 1, "cost_eur": 0.01})
        return answer if isinstance(answer, str) or answer is None else json.dumps(answer)
    return _c
clip = tmp / "scene_001.mp4"
md._claude = fake(FWD)
r = md.plan(photo, DEEP, clip)
h = md.read_history(clip)
check("MD33 plan() returns Claude's plan and writes one history entry (hints, raw answer, plan, usage)", r["source"] == "claude" and len(h["entries"]) == 1 and h["entries"][0]["raw"]["move"] == "forward" and h["entries"][0]["usage"], h)
check("MD34 first attempt: no rework text in the question", "REWORK" not in calls[-1])
md._claude = fake("garbage text")
r = md.plan(photo, DEEP, clip, qc_feedback="clip QC issues: invented shelving unit")
check("MD35 unreadable answer -> safe plan (never an exception), history keeps the problem", r["source"] == "fallback" and md.read_history(clip)["entries"][-1]["problems"], r)
check("MD36 rework: the question carries the QC issue AND the previous move", "REWORK" in calls[-1] and "invented shelving unit" in calls[-1] and "previous attempt used move=forward" in calls[-1], calls[-1][-700:])
md._claude = fake(None)
check("MD37 no answer at all -> None (caller keeps the old table), history says so", md.plan(photo, DEEP, clip) is None and md.read_history(clip)["entries"][-1]["problems"] == ["no answer from Claude"])
def boom(*a, **k): raise RuntimeError("x")
md._claude = boom
check("MD38 an exception inside -> None, never raised", md.plan(photo, DEEP, clip) is None)
job = {"claude_usage": {}, "qc_results": [{"scene": 1, "type": "video", "issues": ["new shelf appears"]}]}
check("MD39 merge_into_job adds the real cost and the history once", md.merge_into_job(job, clip, "sc_1") and job["claude_usage"]["calls"] == 3 and len(job["director_history"]) == 3, job)
check("MD40 second merge adds nothing (counted)", md.merge_into_job(job, clip, "sc_1") is False and len(job["director_history"]) == 3)
check("MD41 qc_feedback_for reads the last video QC issues and the job's earlier plan of that scene",
      "new shelf appears" in md.qc_feedback_for(job, 1, "sc_1") and "previous attempt used move=" in md.qc_feedback_for(job, 1, "sc_1"))

# G. integration with the prompt
tok = "SENTENCE-FROM-DIRECTOR"
pr = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape", "none", "the window", "center", "deep", "LASTVIEW", tok)
check("MD42 motion_override replaces the movement token AND the anchor text; positive rules + last view stay", pr.startswith(tok) and "LASTVIEW" in pr and "3D dolly" not in pr and "push-in toward the window" not in pr, pr[:200])
pr0 = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape")
check("MD43 without override the prompt is exactly the old one", vg._LUMA_MOVEMENT_TOKENS["walk_in_explore"] in pr0 and tok not in pr0)
dv_calls = []
os.environ["PVS_POSITIVE_PROMPT"] = "1"
va = sys.modules.get("vision_analysis") or __import__("vision_analysis")
va._claude_vision_call = lambda imgs, prompt, mt, model=None, usage_out=None: (dv_calls.append(prompt) or json.dumps({"last_view": "The shot ends on a view of the room showing a sofa."}))
big = tmp / "big.jpg"; Image.new("RGB", (1000, 800), (90, 90, 90)).save(big)
dv.describe(big, "walk_in_explore", "large", tmp / "c2.mp4", scale=1.25)
check("MD44 described_view uses the director's scale", json.loads(dv.sidecar_path(tmp / "c2.mp4").read_text())["scale"] == 1.25)
dv.describe(big, "walk_in_explore", "large", tmp / "c3.mp4")
check("MD45 without a scale it keeps the tested default (1.3)", json.loads(dv.sidecar_path(tmp / "c3.mp4").read_text())["scale"] == 1.3)

# H. camera_plan.intent_kwargs and scene rework wiring
os.environ.pop("PVS_ANCHOR", None); os.environ.pop("PVS_DIRECTOR", None)
check("MD46 both switches off: intent_kwargs {} (as before)", camera_plan.intent_kwargs({"anchor": "the window", "anchor_side": "center", "depth": "deep"}) == {})
os.environ["PVS_DIRECTOR"] = "1"
check("MD47 director on, no anchor: only the depth is passed", camera_plan.intent_kwargs({"depth": "deep"}) == {"depth": "deep"})
os.environ["PVS_ANCHOR"] = "1"
check("MD48 anchor on + usable anchor: unchanged behaviour", camera_plan.intent_kwargs({"anchor": "the far window", "anchor_side": "center", "depth": "deep"}) == {"anchor": "the far window", "anchor_side": "center", "depth": "deep"})
import scene_rework
check("MD49 rework feedback empty when the director is off", (os.environ.pop("PVS_DIRECTOR") and scene_rework._director_feedback(job, 1, "sc_1")) == "")
src = Path("scene_rework.py").read_text()
check("MD50 rework passes qc_feedback to generate_video", "qc_feedback=_director_feedback(job, scene_idx, scene_id)" in src)
vsrc = Path("video_generation.py").read_text()
check("MD51 ONE place calls the director (generate_video_single); no other module does", vsrc.count("movement_director.plan(") == 1 and sum(Path(f).read_text().count("movement_director.plan(") for f in ("api_server.py", "scene_rework.py", "listing_scraper.py")) == 0)

# I. target frame (2026-11-02): the description is written for the move, centred on the director's target
p, _ = md.validate(dict(FWD, target_x=0.6, target_y=0.45), DEEP)
check("MD52 the plan keeps the target's place in the photo", p["center"] == (0.6, 0.45), p.get("center"))
p, _ = md.validate(dict(FWD, target_x=0.68, target_y="x"), DEEP)
check("MD53 a near-edge or unreadable target position is kept near the middle", p["center"] == (0.65, 0.5), p.get("center"))
p, _ = md.validate(dict(FWD, target_x=0.95, target_y=0.5), DEEP)
check("MD53b an extreme target (x=0.95) is retargeted to the exact centre (2026-11-03)", p["center"] == (0.5, 0.5) and p["target"] == "the centre of the frame", p)
q = []
va._claude_vision_call = lambda imgs, prompt, mt, model=None, usage_out=None: (q.append(prompt) or json.dumps({"last_view": "The shot ends on a view of the room showing a window."}))
plan_f = {"move": "forward", "sentence": "slow straight forward camera push-in toward the far window", "target": "the far window", "center": (0.6, 0.5), "scale": 1.25}
dv.describe(big, "walk_in_explore", "large", tmp / "c4.mp4", scale=1.25, plan=plan_f)
check("MD54 with a plan the question to Claude carries the move and the target, and the 60-word limit", "far window" in q[-1] and "push-in" in q[-1] and "at most 60 words" in q[-1], q[-1][-400:])
dv.describe(big, "walk_in_explore", "large", tmp / "c5.mp4", scale=1.25)
check("MD55 without a plan the question is the tested one (no addendum)", "The camera move for this shot" not in q[-1])
dv.describe(big, "walk_in_explore", "large", tmp / "c6.mp4", scale=1.25, plan=dict(plan_f, move="static"))
check("MD56 a static plan gets no move addendum", "The camera move for this shot" not in q[-1])
check("MD57 the centre is stored in the note next to the clip", json.loads(dv.sidecar_path(tmp / "c4.mp4").read_text())["center"] == [0.6, 0.5])
lv = "The shot ends on a view of the room showing a grey sofa on the left, a round table in the centre, two closed windows on the right and a lamp in the background."
full = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape", "none", "", "center", "deep", lv, p["sentence"])
old = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape")
check("MD58 the final Luma prompt is not heavier than today's (words)", len(full.split()) <= len(old.split()) + 30, (len(full.split()), len(old.split())))

# J. 2026-11-02 fixes after jobs 73fed155 / de90cbaf / 50472245
for n, tg in (("MD59 a door", "the balcony door"), ("MD60 a mirror", "the mirror"), ("MD61 a wall TV and sideboard", "far wall with wall-mounted TV and sideboard"),
              ("MD62 a wall picture (the cityscape photograph)", "cityscape photograph on the far wall")):
    p, pr = md.validate(dict(FWD, target=tg, target_x=0.3), DEEP)
    check(n + " as target -> Claude's forward move is KEPT, retargeted to the centre in the positive sentence (not the old negative fallback)",
          p and p["source"] == "claude" and p["move"] == "forward" and p["target"] == camera_plan.CENTRE_ANCHOR and "retargeted" in p["adjusted"]
          and p["center"] == (0.5, 0.5) and "never" not in p["sentence"], (p, pr))
p, _ = md.validate(dict(FWD, target="the window with a garden view", mirror_visible=True), DEEP)
check("MD63 a window is a good target even when a mirror is in the photo (only glass / mirror targets are refused)", p["target"] == "the window with a garden view" and "adjusted" not in p, p)
p, _ = md.validate(dict(FWD, target="the glass door", mirror_visible=True), DEEP)
check("MD64 a glass target with a mirror in view is retargeted", p["target"] == camera_plan.CENTRE_ANCHOR)
p, _ = md.validate(dict(FWD, sentence="Slow push forward toward the building"), dict(DEEP, space_type="outdoor"))
check("MD65 outdoor forward moves always get the very-slow wording with a total advance under three metres, and are marked slow",
      p["slow"] is True and p["sentence"].startswith("Very slow") and "less than three metres" in p["sentence"], p)
p, _ = md.validate(dict(FWD), DEEP)
check("MD66 indoor forward moves are not marked slow", p["slow"] is False and "three metres" not in p["sentence"])
pr_slow = vg.assemble_pov_prompt("outdoor", "approach_facade", "bright_natural", "very_slow", "luma", "landscape", "none", "", "center", "deep", "LV", "SENT")
check("MD67 the pace words of a slow scene are 'extremely slow and subtle'", "extremely slow and subtle" in pr_slow)
vs = Path("video_generation.py").read_text()
check("MD68 generate_video_single passes very_slow for a slow plan", '"very_slow" if (plan and plan.get("slow")) else intensity' in vs)
check("MD69 the director's question has room for the whole answer (max_tokens 1000)", "prompt, 1000," in Path("movement_director.py").read_text())
check("MD70 wall pictures are unsafe anchors for the analysis too (one list)", camera_plan.clean_anchor("framed cityscape photograph") == "" and camera_plan.clean_anchor("far window with a view") != "")
_H = {"space_type": "large", "depth": "medium", "output_format": "landscape"}
def _fw(t, x):
    return {"view": "interior", "move": "forward", "target": t, "target_x": x, "target_y": 0.5, "travel": "medium", "risk": "low", "bulky_near_camera": False,
            "mirror_visible": False, "reason": "x",
            "sentence": f"Slow straight forward camera push-in toward the {t}, the camera keeps the same height and direction and stops well before it"}
p, _ = md.validate(_fw("glazed patio panels on the far right wall", 0.8), _H)
check("MD71 a forward target on a side wall (phrase and x) becomes the centre of the frame (job 3fcff5a9 scene 2 turned right)", p["target"] == "the centre of the frame" and "off to one side" in p["adjusted"], p)
p, _ = md.validate(_fw("kitchen island", 0.85), _H)
check("MD72 a forward target at x=0.85 is retargeted to the centre even when the phrase names no side", p["target"] == "the centre of the frame", p)
p, _ = md.validate(_fw("kitchen island", 0.5), _H)
check("MD73 a central target is kept", p["target"] == "kitchen island" and not p.get("adjusted"), p)
p, _ = md.validate(_fw("far end wall of the room", 0.5), _H)
check("MD74 'far end wall' is not a side", p["target"] == "far end wall of the room", p)
check("MD75 the director's question tells Claude the target must be central", "target_x between 0.3 and 0.7" in Path("movement_director.py").read_text())
print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAIL'}")
sys.exit(1 if fails else 0)
