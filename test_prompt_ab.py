"""test_prompt_ab.py - offline checks of exp_prompt_ab (no network, no spend)."""
import json, os, sys, tempfile, types
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_JOBS_DIR"] = str(tmp)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _n in ("fal_client", "moviepy", "anthropic"):
    if _n not in sys.modules:
        try:
            __import__(_n)
        except Exception:
            sys.modules[_n] = types.ModuleType(_n)
if not hasattr(sys.modules["anthropic"], "Anthropic"):
    sys.modules["anthropic"].Anthropic = lambda *a, **k: "REAL"
import exp_prompt_ab as ab
from PIL import Image
fails = 0
def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1

BASE = ("slow 3D dolly shot moving through the room, extremely slow and subtle, this is a frozen photograph of an empty, still room: every wall keeps the same place, "
        "the only thing that moves is the camera, which makes the movement described above smoothly, at a constant slow speed, "
        "everything in view at the start stays in view and in place while the parts of the room nearest the edges leave the frame, "
        "the shot ends on a view of the same room that contains exactly the same elements as the first frame, the camera tilts down slightly")
nb, left = ab.nomove(BASE)
check("T1 B removes move/moves/moving", "moving" not in nb and "moves" not in nb)
check("T2 B keeps the word movement and removes down", "movement described above" in nb and "travelment" not in nb and not ab.BAD_RE.search(nb))
check("T2b B reports a leftover word it cannot remove", ab.nomove("slide, down-left turn, and DOWN")[1] != [] or ab.BAD_RE.search(ab.nomove("slide, down-left turn, and DOWN")[0]) is None)
check("T3 B keeps the rest of the prompt", "frozen photograph" in nb and "dolly shot" in nb)
nc, miss = ab.lock(BASE)
check("T4 C starts with the stationary prefix and has no movement clause", nc.startswith("Stationary view, locked off camera") and "the only thing that moves" not in nc and miss == 0)
check("T5 C counts a missing clause", ab.lock("this is a frozen photograph x")[1] == 3)

REAL = ("Very slow straight forward camera push-in toward distant wooded hillside, advancing less than three metres in total, smooth continuous motion at a constant slow speed, no stepping or bobbing, realistic physics, extremely slow and subtle, "
        "this is a frozen photograph of a still scene: every wall keeps the same place, and the light stays steady, the only thing that moves is the camera, which makes the movement described above smoothly, at a constant slow speed, "
        "everything in view at the start stays in view and in place while the parts of the scene nearest the edges leave the frame, the shot ends on a view of the same scene that contains exactly the same elements as the first frame, "
        "every shadow and every reflection stays as in the source photo and the scene holds only what the source photo shows, The shot ends on a view of the scene showing a curved road that the camera pushes along.")
rc_, rm = ab.lock(REAL)
check("T15 C on a REAL production prompt: all 3 clauses applied, no push-in, no end-view description", rm == 0 and "push" not in rc_.lower() and "curved road" not in rc_ and rc_.startswith("Stationary view, locked off camera") and "nothing moves" in rc_)
nr, lr = ab.nomove(REAL)
check("T16 B on a REAL production prompt: no forbidden word left, movement kept", lr == [] and "movement described above" in nr)
REAL2 = "Very slow straight forward camera push-in toward brick house entrance and far row of houses beyond the paved drive, advancing less than three metres in total, the camera keeps the same height"
r2, f2 = ab.retarget(REAL2); s2, g2 = ab.shorter(REAL2)
check("T17 F replaces only the target", f2 and "push-in toward the centre of the frame, advancing less than three metres" in r2 and "entrance" not in r2)
check("T18 G replaces only the travel", g2 and "less than one metre" in s2 and "three metres" not in s2 and "entrance" in s2)
check("T19 F/G report a prompt without those phrases", ab.retarget("nothing here")[1] is False and ab.shorter("nothing here")[1] is False)
jd = tmp / "job1"; (jd / "clips").mkdir(parents=True); (jd / "images").mkdir()
Image.new("RGB", (640, 360), (120, 120, 120)).save(jd / "images" / "scene_000.jpg")
(jd / "job_meta.json").write_text(json.dumps({"scenes_config": [{"scene_id": "s0", "pov_movement": "walk_in_explore"}]}))
(jd / "clips" / "scene_000.mp4.view.json").write_text(json.dumps({"prompt": BASE, "scale": 1.3, "center": [0.5, 0.5]}))
check("T6 the production prompt is found next to the clip", ab.find_clip_notes("job1", 0).get("view_data", {}).get("prompt") == BASE)
check("T7 a scene without sidecar is reported, not invented", ab.build_jobs([("job1", 5)], ["A"], 1)[1] != [])
jobs, pb = ab.build_jobs([("job1", 0)], ["A", "B", "C", "D"], 2)
check("T8 4 variants x 2 reps = 8 clips; A is the untouched prompt", len(jobs) == 8 and all(j["prompt"] == BASE for j in jobs if j["variant"] == "A" or j["variant"] == "D"))
check("T9 B and C differ from A", all(j["prompt"] != BASE for j in jobs if j["variant"] in "BC"))
nj, npb = ab.build_jobs([("job1", 0)], ["A", "N"], 2, make_near=lambda j, i, n, v: ("NEAR PROMPT", "target='x'"))
check("T20 N uses the prompt built by the production chain, once per scene, for every rep", len(nj) == 4 and [x["prompt"] for x in nj if x["variant"] == "N"] == ["NEAR PROMPT"] * 2 and npb == [])
nj2, npb2 = ab.build_jobs([("job1", 0)], ["N"], 1, make_near=lambda j, i, n, v: (None, "the director gave no plan"))
check("T21 a failed N build is reported and skipped, never replaced by another prompt", nj2 == [] and npb2 and "the director gave no plan" in npb2[0])
nj3, _ = ab.build_jobs([("job1", 0)], ["N"], 1)
check("T22 plan mode (no --go) builds nothing and spends nothing", len(nj3) == 1 and "built at run time" in nj3[0]["prompt"])
kf = ab.mid_keyframe(tmp / "job1" / "images" / "scene_000.jpg", 1.3, [0.5, 0.5], tmp / "mid.jpg")
check("T10 the half-way keyframe has the photo size", Image.open(kf).size == (640, 360))
calls = []
def fake(photo, prompt, out, keyframe=None):
    calls.append((prompt, keyframe)); out.write_bytes(b"x"); return True
rc = ab.cmd_plan_or_run("job1:0", ["A", "B", "D"], 1, False, generate=fake)
check("T11 plan without --go generates nothing and spends nothing", rc == 0 and not calls and ab.spent() == 0)
rc = ab.cmd_plan_or_run("job1:0", ["A", "B", "D"], 1, True, generate=fake)
check("T12 run generates every clip, the D clip gets a keyframe, spend = clips x 0.06", len(calls) == 3 and sum(1 for c in calls if c[1] is not None) == 1 and abs(ab.spent() - 0.18) < 1e-9)
ab.CAP_USD = 0.1
rc = ab.cmd_plan_or_run("job1:0", ["A", "B", "D"], 1, True, generate=fake)
check("T13 over the cap is refused, nothing more generated", rc == 3 and len(calls) == 3)
keys = sorted(ab.OUT.glob("key_*.json"))
check("T14 the key file maps each blind code to its variant", keys and {k["variant"] for k in json.loads(keys[0].read_text())} == {"A", "B", "D"})
import json as _j
import movement_director as _md, described_view as _dv
(tmp / "job1" / "clips" / "scene_000.mp4.plan.json").write_text(_j.dumps({"entries": [{"hints": {"space_type": "outdoor", "depth": "deep", "anchor": "x", "anchor_side": "center", "reflective_surface": "none", "output_format": "landscape"}}]}))
calls = {"plan": 0, "desc": []}
_md.plan = lambda *a, **k: (calls.__setitem__("plan", calls["plan"] + 1) or {"move": "forward", "sentence": "Very slow straight forward camera push-in toward the yard, advancing less than three metres in total", "target": "yard", "scale": 1.12, "slow": True})
_dv.describe = lambda *a, **k: (calls["desc"].append(os.environ.get("PVS_DESCRIBE_NEUTRAL")) or ("LAST-NEUTRAL" if os.environ.get("PVS_DESCRIBE_NEUTRAL") == "1" else "LAST-STANDARD"))
notes = ab.find_clip_notes("job1", 0)
ab._NEAR_CACHE.clear()
pn, _ = ab.near_prompt("job1", 0, notes, tmp / "job1" / "images" / "scene_000.jpg", "N")
p1, _ = ab.near_prompt("job1", 0, notes, tmp / "job1" / "images" / "scene_000.jpg", "N1")
p2, _ = ab.near_prompt("job1", 0, notes, tmp / "job1" / "images" / "scene_000.jpg", "N2")
check("T23 N, N1 and N2 of one scene share ONE director plan (only the thing under test differs)", calls["plan"] == 1)
check("T24 N1 uses the neutral description, N and N2 the standard one", pn.endswith("LAST-STANDARD") and p1.endswith("LAST-NEUTRAL") and p2.endswith("LAST-STANDARD") and calls["desc"] == ["0", "1"])
check("T25 N2 has the short rules (much shorter), N and N1 the full ones", len(p2.split()) < len(pn.split()) - 60 and abs(len(pn.split()) - len(p1.split())) < 3)
check("T25b env restored after the calls", os.environ.get("PVS_LUMA_SHORT_RULES") is None and os.environ.get("PVS_DESCRIBE_NEUTRAL") is None and os.environ.get("PVS_DIRECTOR_NEAR") is None)
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
