"""Camera candidates (2026-10-26): additive prompt pieces + the camera_test_clips tool. Zero cost (fake providers / dry run)."""
import io, os, sys, types, tempfile, contextlib
REPO = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, REPO)
st = tempfile.mkdtemp(prefix="pvscam_"); os.environ["PVS_FAKE_DIR"] = st; os.environ["PVS_FAKE_PROVIDERS"] = "1"; os.environ["LUMA_DIRECT"] = "true"
fc = types.ModuleType("fal_client"); fc.subscribe = fc.upload_file = lambda *a, **k: "REAL"
an = types.ModuleType("anthropic"); an.Anthropic = lambda *a, **k: "REAL"
sys.modules.setdefault("fal_client", fc); sys.modules.setdefault("anthropic", an)
import video_generation as vg
res = []
def check(n, ok, info=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + n + ("" if ok else f" -- {info}"))

old_ok = all(vg.assemble_pov_prompt("large", mv, "bright_natural", "very_slow", "luma", "landscape") == f"{vg._LUMA_MOVEMENT_TOKENS[mv]}, {vg._LUMA_INTENSITY_SUFFIX['very_slow']}, {vg._LUMA_RULES}"
             for mv in ("walk_in_explore", "reveal_pullback", "step_out_onto", "subtle_rotate"))
check("C1 existing Luma prompts are byte-identical to before when no reflective surface is given", old_ok)
p_none = vg.assemble_pov_prompt("bedroom", "subtle_rotate", "bright_natural", "very_slow", "luma", "landscape", "none")
p_big = vg.assemble_pov_prompt("bedroom", "subtle_rotate", "bright_natural", "very_slow", "luma", "landscape", "large")
p_small = vg.assemble_pov_prompt("bedroom", "subtle_rotate", "bright_natural", "very_slow", "luma", "landscape", "small")
check("C2 the mirror rule is added only when a reflective surface was found (small or large)", vg._LUMA_MIRROR_RULE not in p_none and p_big.endswith(vg._LUMA_MIRROR_RULE) and p_small.endswith(vg._LUMA_MIRROR_RULE))
f, o = vg._LUMA_MOVEMENT_TOKENS["approach_facade"], vg._LUMA_MOVEMENT_TOKENS["outward_view"]
check("C3 candidate movements never zoom out / reveal outside the photo, the terrace/garden one never turns back and does not name the horizon",
      "never zooms out" in f and "never reveals anything outside the starting image" in f and "backward" not in f and "reverse" not in f
      and "outside the starting image" in o and "never turns back" in o and "horizon" not in o and "landscape" not in o and "trees" not in o)
check("C4 the candidates are the defaults now (Michele reviewed the test clips 2026-10-26; the table is camera_plan.py, see test_camera_plan.py)",
      vg.SPACE_DEFAULT_MOVEMENT["outdoor"] == "approach_facade" and vg.SPACE_DEFAULT_MOVEMENT["elevated"] == "outward_view")
check("C5 other tiers ignore the reflective argument (Veo/Lyra prompts identical)",
      all(vg.assemble_pov_prompt("bedroom", "subtle_rotate", "bright_natural", "very_slow", t, "landscape", "large") == vg.assemble_pov_prompt("bedroom", "subtle_rotate", "bright_natural", "very_slow", t, "landscape", "none") for t in ("premium", "eco")))

# the tool: dry run prints the 3 prompts and spends nothing
from PIL import Image
cwd = os.getcwd(); work = tempfile.mkdtemp(prefix="pvscamjob_"); os.chdir(work)
os.makedirs("jobs/41ae5a44/images")
for i in (0, 3, 5): Image.new("RGB", (800, 600), (120, 160, 200)).save(f"jobs/41ae5a44/images/scene_{i:03d}.jpg")
import camera_test_clips as ct
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = ct.main(False)
out = buf.getvalue()
check("C6 dry run: rc 0, 3 prompts printed, says DRY RUN, writes nothing but the scratch folder", rc == 0 and out.count("PROMPT:") == 3 and "DRY RUN" in out and not os.path.exists("jobs/41ae5a44/clips"), out[-300:])
check("C7 the facade case uses the facade candidate and the mirror case carries the mirror rule", "approach_facade" in out and vg._LUMA_MIRROR_RULE in out)
os.remove("jobs/41ae5a44/images/scene_005.jpg")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc2 = ct.main(True)
check("C8 a missing photo stops BEFORE any generation (rc 2)", rc2 == 2 and "nothing generated" in buf.getvalue())
os.chdir(cwd)
print(f"\n{sum(res)}/{len(res)} PASS"); sys.exit(0 if all(res) else 1)
