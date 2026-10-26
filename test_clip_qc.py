"""Tests of the clip QC with Claude (vision_analysis.analyse_output, 2026-10-25, backlog 83). No network, no API key, no video.
The model answers are FIXTURES (synthetic: the 41ae5a44 scene 3 'defect' was reviewed by Michele on 2026-10-25 and is NOT a defect, it is one bed reflected in a mirror)."""
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
check("A6 SYNTHETIC answer (a bed count and a door kind changed; NOT a real defect, see status.md 2026-10-25 correction): reject, both named", v == "reject" and "single beds" in iss[0] and "sliding" in iss[0], iss)
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(new_structure=["a slightly different shelf"], severity="minor")))
check("A7 minor doubt -> flag", v == "flag")
check("A8 visible artifacts -> flag; another place -> reject",
      va.clip_qc_verdict(va._parse_clip_qc(ans(artifacts=True)))[0] == "flag" and va.clip_qc_verdict(va._parse_clip_qc(ans(same_space=False)))[0] == "reject")
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(new_structure=["a door"], severity="none")))
check("A9 a listed item with severity none does not fail the clip (the model said it is not a problem)", v == "pass")

# 2026-10-26 (Michele, real job 6dddfd66): doubtful person -> flag with text, not reject; minor with nothing listed -> pass; major with nothing listed -> reject with text
qd = va._parse_clip_qc(ans(possible_person=True))
check("A10 possible_person parsed", qd and qd["possible_person"] is True and va._parse_clip_qc(ans())["possible_person"] is False)
v, iss = va.clip_qc_verdict(qd)
check("A11 faint/ambiguous figure (tile pattern) -> flag WITH a text to read, NOT reject", v == "flag" and len(iss) == 1 and "verificare" in iss[0].lower(), (v, iss))
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(people=True, possible_person=True)))
check("A12 a clear person still rejects (one issue, not two)", v == "reject" and len(iss) == 1)
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(severity="minor")))
check("A13 minor severity with nothing listed -> pass (no empty flag)", v == "pass" and iss == [])
v, iss = va.clip_qc_verdict(va._parse_clip_qc(ans(severity="major")))
check("A14 major with nothing listed -> reject with a generic text", v == "reject" and len(iss) == 1)
check("A15 every flag/reject carries text", all(va.clip_qc_verdict(va._parse_clip_qc(ans(**k)))[1] for k in
      ({"possible_person": True}, {"artifacts": True}, {"people": True}, {"same_space": False}, {"severity": "major"})))
check("A16 prompt asks for possible_person", "possible_person" in va.CLIP_QC_PROMPT)

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
    def _call(images, prompt, max_tokens=250, model=None, usage_out=None):
        calls.append((images, prompt, max_tokens))
        if usage_out is not None:
            usage_out.update({"input_tokens": 1000, "output_tokens": 100, "calls": 1, "cost_eur": 0.001})
        return reply
    return _call


va._claude_vision_call = make_call(ans(first_frame="a walkway with a tiled floor and a brick wall", last_frame="the terrace"))
r = va.analyse_output("clip.mp4", "photo.jpg", "elevated")
check("B1 scene 5 of 41ae5a44 (balcony, walkway/brick wall words): pass, the known space type is never contested",
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


def boom(images, prompt, max_tokens=250, model=None, usage_out=None):
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

# ---- E. Patch X (2026-10-25): inventory-first prompt, model choice, REAL cost of the QC counted once
try:
    import anthropic  # noqa
except Exception:                      # the sandbox has no SDK: a stub is enough, nothing here calls the network
    import types
    _m = types.ModuleType("anthropic"); _m.Anthropic = object; sys.modules["anthropic"] = _m
import listing_scraper as ls
import cost_tracker as ct
check("E1 the QC prompt makes the model list the photo's countable elements first (beds, doors, windows) and treats a change of number/kind as MAJOR",
      "STEP A" in va.CLIP_QC_PROMPT and "photo_elements" in va.CLIP_QC_PROMPT and "two single beds" in va.CLIP_QC_PROMPT and "sliding glass door" in va.CLIP_QC_PROMPT and "MAJOR" in va.CLIP_QC_PROMPT)
p2 = va._parse_clip_qc(ans(photo_elements=["1 double bed", "sliding glass door"]))
check("E2 photo_elements is kept (max 10 short items) and an answer without it still parses", p2["photo_elements"] == ["1 double bed", "sliding glass door"] and va._parse_clip_qc(ans())["photo_elements"] == [])
va._extract_video_frame = fake_frame
va._claude_vision_call = make_call(ans())
r = va.analyse_output("clip.mp4", "photo.jpg", "bedroom")
check("E3 the result carries the usage of THIS clip (tokens, calls, cost)", r["claude_usage"] == {"input_tokens": 1000, "output_tokens": 100, "calls": 1, "cost_eur": 0.001}, r.get("claude_usage"))
va._claude_vision_call = make_call(None)
r = va.analyse_output("clip.mp4", "photo.jpg", "bedroom")
check("E4 even a failed answer reports the usage it cost (never lost)", r["verdict"] == "flag" and r["claude_usage"]["calls"] == 1)
check("E5 cost formula: the 6 clips measured on 2026-10-25 (16692 in / 829 out, Haiku 4.5) = EUR 0.0194; new models are priced from the table",
      abs(ls.claude_cost_eur(16692, 829, "claude-haiku-4-5-20251001") - 0.0194) < 0.0002 and ls.claude_cost_eur(1_000_000, 0, "claude-haiku-5-5") < 0.10 and ls.claude_cost_eur(1_000_000, 0, "claude-sonnet-5-5") > 1.0
      and ls.claude_cost_eur(1000, 100, "unknown-model") > 0)
m = ls.merge_claude_usage({"input_tokens": 10, "output_tokens": 5, "calls": 2, "cost_eur": 0.01}, {"input_tokens": 1000, "output_tokens": 100, "calls": 1, "cost_eur": 0.002})
check("E6 merging usage sums tokens, calls and cost; None is accepted on either side", m == {"input_tokens": 1010, "output_tokens": 105, "calls": 3, "cost_eur": 0.012} and ls.merge_claude_usage(None, None)["calls"] == 0, m)
api = open(os.path.join(os.path.dirname(va.__file__), "api_server.py")).read()
check("E7 the pipeline adds the QC usage of every clip to the job's claude_usage (the field the actual cost reads)",
      'merge_claude_usage(JOBS[job_id].get("claude_usage"), vid_qc.get("claude_usage"))' in api and "claude_usage" in api[api.index("def _record_actual_cost"):api.index("def _record_actual_cost") + 600])
scn = [{"duration": 5, "voiceover": "x"}] * 6
a0 = ct.calculate_actual_cost(scn, ["luma"] * 6, [{"chars": 100}] * 6, True, True, "premium", 0.0)
a1 = ct.calculate_actual_cost(scn, ["luma"] * 6, [{"chars": 100}] * 6, True, True, "premium", 0.02)
check("E8 the ACTUAL cost has no estimated QC line (it would count the QC twice) and includes the real Claude cost exactly once",
      a0.get("vision_eur", 0) == 0 and abs((a1["total_eur"] - a0["total_eur"]) - 0.02) < 0.0011, (a0, a1))
e0 = ct.estimate_job_cost(scn, do_upscale=True, do_vision_qc=True)
e1 = ct.estimate_job_cost(scn, do_upscale=True, do_vision_qc=False)
check("E9 the ESTIMATE counts one Claude check per clip (6 clips), none when the QC is off", e0["vision_calls"] == 6 and abs(e0["vision_eur"] - 6 * ct.CLIP_QC_EST_EUR_PER_CLIP) < 1e-6 and e1["vision_eur"] == 0, (e0, e1))
qsrc2 = open(qv.__file__).read()
check("E10 qc_validate can try another model without changing the default (--model), and prints the cost", "--model" in qsrc2 and "CLIP_QC_MODEL" in qsrc2 and "merge_claude_usage" in qsrc2)
check("Z1 prompt: the mirror rule is present and the wrong example (double bed -> two single beds) is gone", "REFLECTION" in va.CLIP_QC_PROMPT and "one double bed that became two single beds" not in va.CLIP_QC_PROMPT)
check("Z2 max_tokens leaves room for Haiku 5.5 (its JSON was cut at 700)", va.CLIP_QC_MAX_TOKENS >= 1000 and "max_tokens=CLIP_QC_MAX_TOKENS" in open(va.__file__).read())
check("E11 the default QC model is Sonnet 5.5 and the cost ESTIMATE per clip matches the price table for it (within 15%)",
      va.CLIP_QC_DEFAULT_MODEL == "claude-sonnet-5-5" and (va.CLIP_QC_MODEL == va.CLIP_QC_DEFAULT_MODEL or os.getenv("CLIP_QC_MODEL"))
      and abs(ct.CLIP_QC_EST_EUR_PER_CLIP - ls.claude_cost_eur(3285, 340, va.CLIP_QC_DEFAULT_MODEL)) / ct.CLIP_QC_EST_EUR_PER_CLIP < 0.15,
      (ct.CLIP_QC_EST_EUR_PER_CLIP, ls.claude_cost_eur(3285, 340, va.CLIP_QC_DEFAULT_MODEL)))
print(f"\n{ok_n}/{ok_n + len(fails)} PASS")
raise SystemExit(1 if fails else 0)

