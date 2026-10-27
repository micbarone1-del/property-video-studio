"""Camera direction toward an anchor (2026-10-27). Zero cost, no network. Guards: with the switch OFF (default) nothing changes, byte for byte;
with it ON only the straight forward movements of the Luma prompt change; unsafe / missing anchors fall back; one implementation of the text."""
import sys, os, re, types, ast, asyncio, subprocess, tempfile, importlib, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
os.environ.pop("PVS_ANCHOR", None)
import camera_plan as cp
import video_generation as vg
import vision_analysis as va
import exp_luma as ex
res = []
def check(n, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + n + ("" if ok else f" -- {info}"))

# ---- A. OFF: byte-identical to the pre-change prompts -----------------------------------------------------------------------------
tmp = tempfile.mkdtemp()
old_src = None
for ref in ("HEAD", "HEAD~1", "HEAD~2"):      # the last commit WITHOUT the camera direction (the server has the patch committed on top)
    try:
        cand = subprocess.check_output(["git", "show", ref + ":video_generation.py"], stderr=subprocess.DEVNULL).decode()
    except Exception:
        continue
    if "PRODUCTION_ANCHOR_MOVEMENTS" not in cand:
        old_src = cand; break
if old_src and "PRODUCTION_ANCHOR_MOVEMENTS" not in old_src:
    open(os.path.join(tmp, "vg_old.py"), "w").write(old_src); sys.path.insert(0, tmp)
    import vg_old
    diffs = []
    for tier in ("eco", "standard", "premium", "luma"):
        for mv in list(vg._LUMA_MOVEMENT_TOKENS) + ["unknown"]:
            for sp in ("large", "small", "corridor", "bedroom", "outdoor"):
                for fmt in ("landscape", "portrait"):
                    for refl in ("none", "small"):
                        a = vg.assemble_pov_prompt(sp, mv, "bright_natural", "natural_pace", tier, fmt, refl)
                        b = vg_old.assemble_pov_prompt(sp, mv, "bright_natural", "natural_pace", tier, fmt, refl)
                        if a != b: diffs.append((tier, mv, sp, fmt, refl))
    check("A1 no anchor: every prompt of every tier/movement/space/format equals the previous version byte for byte", not diffs, diffs[:3])
else:
    check("A1 (previous version not available in this checkout: skipped)", True)
check("A2 anchor='' explicit equals the default call", vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape", "none", "", "center", "") == vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma"))

# ---- B. ON: which prompts change -----------------------------------------------------------------------------------------------
def P(mv, tier="luma", fmt="landscape", refl="none", anchor="the French doors", side="center", depth="medium", sp="large"):
    return vg.assemble_pov_prompt(sp, mv, "bright_natural", "natural_pace", tier, fmt, refl, anchor, side, depth)
base_explore = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma")
p = P("walk_in_explore")
check("B1 walk_in_explore + anchor: the approved push-in toward the anchor + the first-frame text", "push-in toward the French doors" in p and "never dodge it" in p and cp.ANCHOR_STRICT in p and p != base_explore)
check("B2 outward_view + anchor: also anchored", "push-in toward the French doors" in P("outward_view", sp="elevated"))
check("B3 stand_look_around (remapped to walk_in_explore) + anchor: anchored", "push-in toward the French doors" in P("stand_look_around"))
check("B4 sideways / turning / near-static movements are NOT anchored in production (untested)", all("French doors" not in P(m) for m in ("walk_in_gentle", "walk_in_turn_left", "walk_in_turn_right", "subtle_rotate", "approach_facade", "walk_through")))
check("B5 the other models' prompts ignore the anchor", all(P("walk_in_explore", tier=t) == vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", t) for t in ("eco", "standard", "premium")))
check("B6 a mirror / glass photo (reflective_surface small|large) keeps the old prompt: no contradiction with 'never move toward glass'", all("French doors" not in P("walk_in_explore", refl=r) and P("walk_in_explore", refl=r) == vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape", r) for r in ("small", "large")))
check("B7 portrait keeps its anti-drift text next to the anchor", "no lateral drift" in P("walk_in_explore", fmt="portrait") and "French doors" in P("walk_in_explore", fmt="portrait"))
check("B8 shallow depth = much shorter push; medium/deep/unknown = the approved text", "less than half a metre" in P("walk_in_explore", depth="shallow") and all("half a metre" not in P("walk_in_explore", depth=d) for d in ("medium", "deep", "")))
check("B9 the experiment tool and production share ONE text (same objects)", ex.ANCHOR_MOTION is cp.ANCHOR_MOTION and ex.STRICT_ADD is cp.ANCHOR_STRICT and ex.anchor_motion_for is cp.anchor_motion_for and ex.parse_anchor_side is cp.parse_anchor_answer)

# ---- C. the safety net of the anchor itself ------------------------------------------------------------------------------------------
check("C1 clean_anchor: ok / none / empty / too long / unsafe words", cp.clean_anchor("the far end of the living room") == "the far end of the living room" and cp.clean_anchor("none") == "" and cp.clean_anchor(None) == "" and cp.clean_anchor("a" * 90) == "" and all(cp.clean_anchor(x) == "" for x in ("a large mirror", "the TV screen", "a woman on the sofa", "the dog", "reflection in the glass")))
check("C2 criteria v2: far / central / fixed / worth looking at. Doors, fixtures, near railings, mirrors, screens are rejected (job 26d7a774 feedback); views, windows, beds, fireplaces pass",
      all(cp.clean_anchor(x) for x in ("the distant skyline beyond the terrace", "a window with a view of the garden", "the double bed", "the fireplace", "the far wall with the bookshelves", "the outdoor terrace view"))
      and all(cp.clean_anchor(x) == "" for x in ("glass sliding door to balcony", "French doors on the right wall", "the doorway to the hall", "stainless steel sink and countertop", "the bathtub", "metal railing along balcony edge", "curved balcony with railing", "large mirrored wardrobe with white frame", "wall mirror", "reflecting glass wall", "two screens on the desk", "the curtains", "a potted plant")))
check("C3 sides: left/right/center kept, anything else = center", cp.clean_side("Left") == "left" and cp.clean_side("middle") == "center" and cp.clean_side(None) == "center")
os.environ.pop("PVS_ANCHOR", None)
check("C4 intent_kwargs OFF = {} whatever the scene", cp.intent_kwargs({"anchor": "the bed", "depth": "deep"}) == {})
os.environ["PVS_ANCHOR"] = "1"
check("C5 intent_kwargs ON: centred valid scene -> kwargs; edge / no / unsafe / junk anchor -> {}; bad depth -> ''", cp.intent_kwargs({"anchor": "the bed", "anchor_side": "center", "depth": "deep"}) == {"anchor": "the bed", "anchor_side": "center", "depth": "deep"}
      and cp.intent_kwargs({"anchor": "the bed", "anchor_side": "left", "depth": "deep"}) == {} and cp.intent_kwargs({"anchor": "the bed", "anchor_side": "right"}) == {}
      and cp.intent_kwargs({}) == {} and cp.intent_kwargs({"anchor": "mirror"}) == {} and cp.intent_kwargs(None) == {} and cp.intent_kwargs({"anchor": "the bed", "anchor_side": "center", "depth": "huge"})["depth"] == ""
      and all(cp.intent_kwargs({"anchor": a, "anchor_side": sd}) == {} for a, sd in (("glass sliding door to balcony", "right"), ("stainless steel sink and countertop", "center"), ("metal railing along balcony edge", "center"))))

check("C6 a far window / horizon high in the frame is accepted, a lower anchor and a ceiling lamp are not", cp.anchor_usable("distant green foliage and trees", "center", "upper") != "" and cp.anchor_usable("far window with natural light", "center", "upper") != "" and cp.anchor_usable("the bed", "center", "lower") == "" and cp.anchor_usable("ceiling lamp", "center", "upper") == "")

# ---- D. the photo analysis: same call, extra keys only when ON --------------------------------------------------------------------
seen = {}
def fake_text(path, prompt, max_tokens=250):
    seen["prompt"], seen["max"] = prompt, max_tokens
    return seen["answer"]
va._claude_vision_text = fake_text
seen["answer"] = '{"room":"living","size":"large","depth":"deep","confidence":0.9,"description":"x","anchor":"the view over the terrace","anchor_side":"Center","anchor_height":"middle"}'
r = va._classify_room_claude("x.jpg")
check("D1 ON: the prompt carries the v2 anchor rules, the answer carries a cleaned anchor + side", va.ROOM_PROMPT_ANCHOR in seen["prompt"] and r["anchor"] == "the view over the terrace" and r["anchor_side"] == "center")
check("D1b the prompt states the v2 criteria (centre + far, worth seeing, no door / fixture / near railing / reflections, 'none' allowed)", all(w in va.ROOM_PROMPT_ANCHOR for w in ("CENTRE", "FAR", "NEVER a door", "sink", "railing", "DISTANT VIEW", '"none"', "anchor_height")))
seen["answer"] = '{"room":"terrace","size":"large","depth":"deep","confidence":0.9,"description":"x","anchor":"the railing","anchor_side":"center","anchor_height":"lower"}'
check("D1c anchor low in the frame (a near railing pulls the camera down): rejected", va._classify_room_claude("x.jpg")["anchor"] == "")
seen["answer"] = '{"room":"living","size":"large","depth":"deep","confidence":0.9,"description":"x","anchor":"the far wall","anchor_side":"right","anchor_height":"middle"}'
check("D1d anchor at the edge (side right): rejected, the camera would turn toward it", va._classify_room_claude("x.jpg")["anchor"] == "")
seen["answer"] = '{"room":"bathroom","size":"small","depth":"shallow","confidence":0.9,"description":"x","anchor":"the large mirror","anchor_side":"center"}'
r = va._classify_room_claude("x.jpg")
check("D2 ON: Claude names a mirror -> anchor '' (side '')", r["anchor"] == "" and r["anchor_side"] == "")
seen["answer"] = '{"room":"living","size":"large","depth":"deep","confidence":0.9,"description":"x"}'
check("D3 ON: an answer without the anchor keys still parses (anchor '')", va._classify_room_claude("x.jpg")["anchor"] == "")
os.environ.pop("PVS_ANCHOR")
seen["answer"] = '{"room":"living","size":"large","depth":"deep","confidence":0.9,"description":"x","anchor":"the doors","anchor_side":"left"}'
r = va._classify_room_claude("x.jpg")
check("D4 OFF: the prompt is exactly ROOM_PROMPT (same size limit as before) and no anchor key is returned", seen["prompt"] == va.ROOM_PROMPT and seen["max"] == 250 and "anchor" not in r)
os.environ["PVS_ANCHOR"] = "1"
seen["answer"] = '{"room":"living","size":"large","depth":"deep","confidence":0.9,"description":"x","anchor":"the far wall","anchor_side":"center"}'
fp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False); fp.write(b"x"); fp.close()
a = va.analyse_input(fp.name)
check("D5 analyse_input returns anchor, anchor_side, depth and the same movement as before", a["anchor"] == "the far wall" and a["anchor_side"] == "center" and a["depth"] == "deep" and a["suggested_movement"] == "walk_in_explore")
va._classify_room_claude = lambda p: None
va._analyse_input_florence = lambda p, d: va._build_input_result("large_interior", "medium", 0.5, "f", "florence")
check("D6 Claude unavailable (Florence fallback): empty anchor, no crash", va.analyse_input(fp.name)["anchor"] == "")

# ---- E. api_server (cannot be imported here: no fastapi): the function is extracted and run; the call sites are checked in the source --
src = open("api_server.py").read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_apply_vision_analysis_to_scenes")
ns = {"asyncio": asyncio, "camera_plan": cp, "log": logging.getLogger("t")}
exec(compile(ast.Module([fn], []), "api_server_fn", "exec"), ns)
import vision_analysis
vision_analysis.analyse_input = lambda path: {"v7_space_type": "large", "suggested_movement": "walk_in_explore", "depth": "deep", "anchor": "the doors", "anchor_side": "left"}
from pathlib import Path
scenes = [{"pov_movement": "x"}]
asyncio.run(ns["_apply_vision_analysis_to_scenes"](scenes, [Path(fp.name)]))
check("E1 ON: the scene stores anchor, side and depth next to space_type / pov_movement", scenes[0].get("anchor") == "the doors" and scenes[0].get("anchor_side") == "left" and scenes[0].get("depth") == "deep" and scenes[0]["pov_movement"] == "walk_in_explore")
os.environ.pop("PVS_ANCHOR")
scenes = [{"pov_movement": "x"}]
asyncio.run(ns["_apply_vision_analysis_to_scenes"](scenes, [Path(fp.name)]))
check("E2 OFF: scenes_config is exactly as before (no new keys)", set(scenes[0]) == {"pov_movement", "space_type"}, scenes[0])
check("E3 the main generation call and the scene rework both read camera_plan.intent_kwargs(scene)", src.count("camera_plan.intent_kwargs(scene)") == 1 and open("scene_rework.py").read().count("camera_plan.intent_kwargs(scene)") == 1)
check("E4 generate_video_single accepts and passes anchor / anchor_side / depth", "anchor, anchor_side, depth," in open("video_generation.py").read() and "anchor:         str  = \"\"" in open("video_generation.py").read())
check("E5 the legacy batch tool video_assembly.py is not part of the production path (no pov_movement there)", "pov_movement" not in open("video_assembly.py").read())
os.unlink(fp.name)
print(f"\nRESULT: {'ALL PASS' if all(res) else 'FAILURES'} ({sum(res)}/{len(res)})")
sys.exit(0 if all(res) else 1)
