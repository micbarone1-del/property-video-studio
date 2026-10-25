"""Tests of the clip QC with Claude (vision_analysis.analyse_output, 2026-10-25, backlog 83). No network, no API key, no video.
The model answers are FIXTURES written from the real defects of job 41ae5a44 (Michele's review)."""
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.getcwd())
try:
    import fal_client  # noqa
except Exception:
    fc = types.ModuleType("fal_client")
    fc.subscribe = lambda *a, **k: {"results": ""}
    fc.upload_file = lambda p: "http://x/y.jpg"
    sys.modules["fal_client"] = fc
import vision_analysis as va

ok_n, fails = 0, []


def check(name, cond, extra=""):
    global ok_n
    if cond:
        ok_n += 1
        print(f"PASS {name}")
    else:
        fails.append(name)
        print(f"FAIL {name} {extra}")


def ans(**kw):
    d = {"people": False, "same_space": True, "new_structure": [], "severity": "none", "artifacts": False,
         "first_frame": "a balcony with a tiled floor", "last_frame": "the same balcony"}
    d.update(kw)
    return json.dumps(d)


# ---- A. parsing and verdict rules (pure)
p = va._parse_clip_qc(ans())
check("A1 clean answer parses", p and p["severity"] == "none" and p["same_space"] is True)
check("A2 answer with text around / comments parses", va._parse_clip_qc('Ecco:\n{"people": false, "same_space": true, // note\n "new_structure": [], "severity": "none", "artifacts": false, "first_frame": "a", "last_frame": "b"}') is not None)
check("A3 garbage / missing keys / bad severity -> None", all(va._parse_clip_qc(x) is None for x in ("", "no json", '{"x":1}', ans(severity="huge"))))
check("A4 nothing wrong -> pass", va.clip_qc_verdict(va._parse_clip_qc(ans())) == ("pass", []))
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(people=True)))
check("A5 a person/shadow/reflection -> reject", v == "reject" and iss)
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(new_structure=["two single beds instead of one double bed", "door with handle instead of the sliding glass door"], severity="major")))
check("A6 REAL DEFECT scene 3 of 41ae5a44 (double bed -> two single beds, sliding door -> door): reject, both named", v == "reject" and "single beds" in iss[0] and "sliding" in iss[0], iss)
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(new_structure=["a slightly different shelf"], severity="minor")))
check("A7 minor doubt -> flag", v == "flag")
check("A8 visible artifacts -> flag; another place -> reject",
      va.clip_qc_verdict(va._parse_clip_qc(ans(artifacts=True)))[0] == "flag" and va.clip_qc_verdict(va._parse_clip_qc(ans(same_space=False)))[0] == "reject")
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(new_structure=["a door"], severity="none")))
check("A9 a listed item with severity none does not fail the clip (the model said it is not a problem)", v == "pass")

# ---- B. analyse_output with fakes (the frames and the model are replaced)
tmp = tempfile.mkdtemp()
frames = []


def fake_frame(path, position="first"):
    f = os.path.join(tmp, f"{position}_{len(frames)}.jpg")
    open(f, "wb").write(b"x")
    frames.append(f)
    return f


va._extract_video_frame = fake_frame
calls = []


def make_call(reply):
    def _call(images, prompt, max_tokens=250):
        calls.append((images, prompt, max_tokens))
        return reply
    return _call


va._claude_vision_call = make_call(ans(first_frame="a walkway with a tiled floor and a brick wall", last_frame="the terrace"))
r = va.analyse_output("clip.mp4", "photo.jpg", "elevated")
check("B1 REAL DEFECT scene 5 of 41ae5a44 (balcony, walkway/brick wall words): pass, the known space type is never contested",
      r["verdict"] == "pass" and r["space_matches"] is True and r["error"] is None, r)
check("B2 the model gets photo + first + last frame, and is told the known space type and not to judge it",
      len(calls[-1][0]) == 3 and calls[-1][0][0] == "photo.jpg" and "(elevated)" in calls[-1][1] and "NEVER judge" in calls[-1][1])
check("B3 both frame descriptions are stored; result keeps every key the pipeline/UI reads",
      r["output_description"].startswith("a walkway") and r["last_description"] == "the terrace" and all(k in r for k in
      ("verdict", "people_detected", "space_matches", "structural_hallucinations", "quality_score", "issues", "original_description", "output_description", "error")), r)
va._claude_vision_call = make_call(ans(new_structure=["two single beds instead of one double bed"], severity="major"))
r = va.analyse_output("clip.mp4", "photo.jpg", "bedroom")
check("B4 invented structure -> reject with structural_hallucinations True", r["verdict"] == "reject" and r["structural_hallucinations"] is True and r["new_structure"], r)
va._claude_vision_call = make_call(None)
r = va.analyse_output("clip.mp4", "photo.jpg", "large")
check("B5 Claude unavailable -> flag with the reason (never a silent pass), no exception", r["verdict"] == "flag" and r["error"] and r["issues"], r)
va._claude_vision_call = make_call("not json at all")
check("B6 unusable answer -> flag", va.analyse_output("clip.mp4", "photo.jpg")["verdict"] == "flag")


def boom(images, prompt, max_tokens=250):
    raise RuntimeError("network down")


va._claude_vision_call = boom
check("B7 exception inside -> flag, never raises", va.analyse_output("clip.mp4", "photo.jpg")["verdict"] == "flag")
va._extract_video_frame = lambda p, position="first": None
check("B8 frames cannot be extracted -> flag", va.analyse_output("clip.mp4", "photo.jpg")["verdict"] == "flag")
check("B9 temporary frames are removed after the check", all(not os.path.exists(f) for f in frames))

# ---- C. wiring / no second implementation
src = open(va.__file__).read()
body = src[src.index("def analyse_output("):src.index("# ── 3. TTS QUALITY CONTROL")]
check("C1 the keyword/Florence QC is gone from analyse_output (no _STRUCTURAL_KW, _PEOPLE_KW, Florence caption, no interior/exterior rule)",
      not any(w in body for w in ("_STRUCTURAL_KW", "_PEOPLE_KW", "_BODY_PART_KW", "_describe_image", "strong_interior", "strong_outdoor")) and not any(w in src for w in ("_STRUCTURAL_KW =", "_PEOPLE_KW  ", "_BODY_PART_KW =")))
check("C2 ONE Claude vision implementation: _claude_vision_text delegates to _claude_vision_call", "return _claude_vision_call([image_path], prompt, max_tokens)" in src)
api = open(os.path.join(os.path.dirname(va.__file__), "api_server.py")).read()
check("C3 the pipeline still calls analyse_output(clip, photo, space_type) (signature unchanged)", "analyse_output, clip_out, original_img, space_type" in api)
# ---- D. qc_validate (read-only validation tool): plan() only
import qc_validate as qv
from pathlib import Path
jd = Path(tempfile.mkdtemp())
(jd / "aaaa1111" / "clips").mkdir(parents=True)
(jd / "aaaa1111" / "images").mkdir()
for i in range(3):
    (jd / "aaaa1111" / "clips" / f"scene_{i:03d}.mp4").write_bytes(b"c")
    (jd / "aaaa1111" / "images" / f"scene_{i:03d}.jpg").write_bytes(b"p")
(jd / "aaaa1111" / "clips" / "scene_001.mp4").unlink()
(jd / "aaaa1111" / "job_meta.json").write_text(json.dumps({
    "scenes_config": [{}, {}, {}], "scenes": [{"index": 0, "space_type": "outdoor"}, {"index": 2, "space_type": "elevated"}],
    "qc_results": [{"scene": 2, "type": "video", "verdict": "reject", "issues": ["Space mismatch"]}, {"scene": 0, "type": "tts", "verdict": "pass"}]}))
rows = qv.plan("aaaa1111", jd)
check("D1 plan: only scenes with BOTH photo and clip; old verdict and space type are read from job_meta",
      [r["scene"] for r in rows] == [0, 2] and rows[1]["old_verdict"] == "reject" and rows[1]["space_type"] == "elevated" and rows[0]["old_verdict"] is None, rows)
bad = []
for j in ("../x", "_test_scratch", ".h", ""):
    try:
        qv.plan(j, jd)
        bad.append(j)
    except ValueError:
        pass
check("D3 path tricks raise ValueError", not bad, bad)
qsrc = open(qv.__file__).read()
check("D4 the validation tool writes and deletes nothing", not any(w in qsrc for w in ("write_text", "write_bytes", "open(", "rmtree", ".unlink(", "os.remove", "shutil", "json.dump")))
print(f"\n{ok_n}/{ok_n + len(fails)} PASS")
raise SystemExit(1 if fails else 0)
