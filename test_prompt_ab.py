"""test_prompt_ab.py - offline checks of exp_prompt_ab (no network, no spend)."""
import json, os, sys, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_JOBS_DIR"] = str(tmp)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
