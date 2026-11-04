"""Positive Luma prompt + described last view (2026-11-02). Zero cost, no network, no key: Claude and the file system are faked.
Run: python3 test_described_view.py   (numbered PASS/FAIL like the other test files)"""
import json, os, re, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
from PIL import Image
import described_view as dv
import video_generation as vg
import vision_analysis as va
import listing_scraper as ls
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}"))
    fails += 0 if c else 1

# --- A. the switch and the wording -----------------------------------------------------------------------------------------------------
os.environ.pop("PVS_POSITIVE_PROMPT", None)
check("DV1 on by default", dv.enabled())
for v in ("0", "false", "off", "no"):
    os.environ["PVS_POSITIVE_PROMPT"] = v
    if dv.enabled(): check(f"DV2 PVS_POSITIVE_PROMPT={v} turns it off", False)
os.environ["PVS_POSITIVE_PROMPT"] = "0"
check("DV2 PVS_POSITIVE_PROMPT=0/false/off/no turns it off", not dv.enabled())
os.environ.pop("PVS_POSITIVE_PROMPT")
LV = "The shot ends on a view of the room showing a grey sofa on the left, a round table in the centre and a closed window on the right."
r = dv.rules_for(LV, "large")
check("DV3 rules = positive text (with the standard no-move clause) + the description", r.startswith(dv.POSITIVE_RULES.replace(dv.NOMOVE_FROM, dv.NOMOVE_TO)) and r.endswith(LV))
check("DV4 the positive rules contain no negation list of the old kind", "no people" not in dv.POSITIVE_RULES and "do not invent" not in dv.POSITIVE_RULES and "no warping" not in dv.POSITIVE_RULES)
check("DV5 open-air scenes: 'room' becomes 'scene' in the rules and in the question to Claude; interiors keep the tested wording",
      "room" not in dv._scene_words(dv.POSITIVE_RULES, "outdoor") and "room" not in dv._scene_words(dv.DESCRIBE_PROMPT, "elevated")
      and dv._scene_words(dv.POSITIVE_RULES, "large") == dv.POSITIVE_RULES)
check("DV6 crop scale: forward movements 1.3, the rest 1.1; the scale follows the REMAPPED movement (portrait gentle -> forward)",
      dv.crop_scale("walk_in_explore") == 1.3 and dv.crop_scale("subtle_rotate") == 1.1 and dv.crop_scale(vg._remap_movement("walk_in_gentle", "portrait")) == 1.3
      and dv.crop_scale(vg._remap_movement("walk_in_gentle", "landscape")) == 1.1 and vg._remap_movement("stand_look_around", "landscape") == "walk_in_explore")

# --- B. the prompt ----------------------------------------------------------------------------------------------------------------------
bad = []
for tier in ("eco", "standard", "premium", "luma"):
    for mv in list(vg._LUMA_MOVEMENT_TOKENS) + ["unknown"]:
        for fmt in ("landscape", "portrait"):
            a = vg.assemble_pov_prompt("large", mv, "bright_natural", "natural_pace", tier, fmt, "none")
            b = vg.assemble_pov_prompt("large", mv, "bright_natural", "natural_pace", tier, fmt, "none", "", "center", "", "")
            if a != b: bad.append((tier, mv, fmt))
check("DV7 without a description every prompt of every tier/movement/format is unchanged (empty last_view = old rules)", not bad, bad[:3])
old = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape")
new = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape", "none", "", "center", "", LV)
check("DV8 with a description: same movement token and pace, the old rules are replaced by the positive text + description",
      new == f"{vg._LUMA_MOVEMENT_TOKENS['walk_in_explore']}, {vg._LUMA_INTENSITY_SUFFIX['natural_pace']}, {dv.rules_for(LV, 'large')}" and vg._LUMA_RULES in old and vg._LUMA_RULES not in new)
check("DV9 a description is ignored by the other models", all(vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", t, "landscape", "none", "", "center", "", LV) == vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", t, "landscape") for t in ("eco", "standard", "premium")))
mir = vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "landscape", "large", "", "center", "", LV)
check("DV10 the mirror/glass rule and the portrait anti-drift text still get added after the positive rules", mir.endswith(vg._LUMA_MIRROR_RULE) and
      vg.assemble_pov_prompt("large", "walk_in_explore", "bright_natural", "natural_pace", "luma", "portrait", "none", "", "center", "", LV).endswith("field of view stays fixed and centered throughout the shot"))

# --- C. the description ----------------------------------------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
photo = tmp / "p.jpg"; Image.new("RGB", (640, 360), (120, 110, 100)).save(photo)
clip = tmp / "scene_000.mp4"
seen = {}
def fake_call(paths, prompt, max_tokens=250, model=None, usage_out=None):
    seen.update(paths=list(paths), prompt=prompt, model=model)
    sizes = [Image.open(p).size for p in paths]; seen["sizes"] = sizes
    usage_out.update(ls.merge_claude_usage(usage_out, {"input_tokens": 1000, "output_tokens": 100, "calls": 1, "cost_eur": 0.0123}))
    return 'sure {"last_view": "' + LV + '"}'
va._claude_vision_call = fake_call
out = dv.describe(photo, "walk_in_explore", "large", clip)
check("DV11 returns Claude's sentence; the crop (1/1.3 of the photo, centred) is sent as image 2 with the whole photo as image 1",
      out == LV and seen["sizes"][0] == (640, 360) and seen["sizes"][1] == (round(640 / 1.3), round(360 / 1.3)) and seen["model"] == va.CLIP_QC_MODEL, seen.get("sizes"))
check("DV12 the temporary crop is deleted; nothing but the note is written next to the clip", not Path(seen["paths"][1]).exists() and sorted(p.name for p in tmp.iterdir()) == ["p.jpg", "scene_000.mp4.view.json"])
note = json.loads(dv.sidecar_path(clip).read_text())
check("DV13 the note keeps the sentence, scale, movement and the REAL usage, not yet counted", note["used"] and note["last_view"] == LV and note["scale"] == 1.3 and note["usage"]["cost_eur"] == 0.0123 and note["counted"] is False)
job = {"claude_usage": {"input_tokens": 5, "output_tokens": 5, "calls": 1, "cost_eur": 0.5}}
check("DV14 the cost is added to the job once", dv.merge_usage_into_job(job, clip) and abs(job["claude_usage"]["cost_eur"] - 0.5123) < 1e-9 and job["claude_usage"]["calls"] == 2)
check("DV15 a second call does not count it again", not dv.merge_usage_into_job(job, clip) and abs(job["claude_usage"]["cost_eur"] - 0.5123) < 1e-9)
dv.describe(photo, "walk_in_explore", "large", clip)
check("DV16 a new generation of the same clip writes a fresh note that is counted again (rework)", dv.merge_usage_into_job(job, clip) and abs(job["claude_usage"]["cost_eur"] - 0.5246) < 1e-9)
# failures -> '' (old rules), never an exception
for label, fn in (("no answer", lambda *a, **k: None), ("not JSON", lambda *a, **k: "blah"), ("empty sentence", lambda *a, **k: '{"last_view": ""}'),
                  ("too long", lambda *a, **k: '{"last_view": "' + "x" * 800 + '"}'), ("exception", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))):
    va._claude_vision_call = fn
    check(f"DV17 {label}: '' returned, no exception", dv.describe(photo, "walk_in_explore", "large", tmp / "x.mp4") == "")
va._claude_vision_call = fake_call
dv.note_prompt(clip, "PROMPT", True)
n2 = json.loads(dv.sidecar_path(clip).read_text())
check("DV18 the exact Luma prompt is kept next to the clip and keeps the description", n2["prompt"] == "PROMPT" and n2["positive_prompt"] is True and n2["last_view"] == LV)
dv.note_prompt(clip, "OLD", False)
n3 = json.loads(dv.sidecar_path(clip).read_text())
check("DV19 old-rules generation replaces the previous note (no stale description)", n3 == {"prompt": "OLD", "positive_prompt": False})

# --- D. wiring: one call site, Luma only, both generation paths add the cost -------------------------------------------------------------
vsrc = open("video_generation.py").read(); asrc = open("api_server.py").read()
check("DV20 one description call site, Luma only, behind the switch", vsrc.count("described_view.describe(") == 1 and 'if model_tier == "luma":\n            import described_view\n            import movement_director' in vsrc and "            if described_view.enabled():\n                last_view = described_view.describe(" in vsrc)   # 2026-11-02: the movement director sits between the import and the description
check("DV21 the pipeline AND the rework runner both add the described-view cost to the job", asrc.count("merge_usage_into_job") == 2)
check("DV22 the movement remap exists once and assemble_pov_prompt uses it", vsrc.count("def _remap_movement") == 1 and "pov_movement = _remap_movement(pov_movement, output_format)" in vsrc and vsrc.count("stand_look_around remap") == 1)
check("DV23 the positive text is defined once (exp_prompt imports it)", sum(open(f).read().count("this is a frozen photograph of an empty, still room") for f in ("described_view.py", "exp_prompt.py", "video_generation.py", "exp_luma.py")) == 1)
check("DV24 the old rules are untouched (fall-back)", "no people, no human shadows or silhouettes" in vsrc and vsrc.count("no human shadows") == 1)
import os as os
_o = os.environ.get("PVS_LUMA_NOMOVE")
os.environ["PVS_LUMA_NOMOVE"] = "0"
_std = dv.rules_for("view", "large")
os.environ.pop("PVS_LUMA_NOMOVE", None)
_nm = dv.rules_for("view", "large")           # no variable at all = the default
if _o is not None:
    os.environ["PVS_LUMA_NOMOVE"] = _o
check("DV-NM1 PVS_LUMA_NOMOVE=0 gives the old rules text", "the only thing that moves is the camera" in _std)
check("DV-NM2 by default (no variable) only that clause changes: no 'moves', 'movement' kept, same length class", "moves" not in _nm and "the only thing that changes is the camera position, which makes the movement described above" in _nm and _nm.replace("changes is the camera position", "moves is the camera") == _std)
_ns = {k: os.environ.pop(k, None) for k in ("PVS_DESCRIBE_NEUTRAL", "PVS_LUMA_SHORT_RULES")}
_aD = dv.plan_addendum()                       # no variable at all = the default (2026-11-04: neutral ON)
os.environ["PVS_DESCRIBE_NEUTRAL"] = "0"
_a0, _r0 = dv.plan_addendum(), dv.rules_for("view", "large")
os.environ["PVS_DESCRIBE_NEUTRAL"] = "1"; os.environ["PVS_LUMA_SHORT_RULES"] = "1"
_a1, _r1 = dv.plan_addendum(), dv.rules_for("view", "large")
for k, v in _ns.items():
    os.environ.pop(k, None)
    if v is not None:
        os.environ[k] = v
check("DV-N1D by default (no variable) the neutral description is used; PVS_DESCRIBE_NEUTRAL=0 gives the old one", _aD == _a1 and _aD != _a0)
check("DV-N1 PVS_DESCRIBE_NEUTRAL=0 asks for the path (old), the neutral one does not", "what lies on the path" in _a0 and "what lies on the path" not in _a1 and "toward, along, leads" in _a1)
check("DV-N2 short rules only with PVS_LUMA_SHORT_RULES=1: much shorter, still frozen photograph + constant slow speed, ends with the description", len(_r0.split()) > 120 and len(_r1.split()) < 70 and "frozen photograph" in _r1 and "constant slow speed" in _r1 and _r1.endswith("view"))
print("ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
