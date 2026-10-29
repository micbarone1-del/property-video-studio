"""scene_rework (2026-10-22, backlog 75): the ONE rework engine. No network, no API key,
no server, no real TTS/video: every outside call is a fake. Run: python3 test_scene_rework.py"""
import asyncio, copy, json, os, re, sys, tempfile, types, logging
from pathlib import Path
sys.path.insert(0, os.getcwd())
import scene_rework as sr
import cost_tracker as ct

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

log = logging.getLogger("t"); log.addHandler(logging.NullHandler())

# ── clip length: ONE rule ───────────────────────────────────────────────────
def old_first_generation(audio_secs, user):            # the inline rule of the job pipeline, verbatim
    if audio_secs > 0:
        return max(6, min(20, int(round((audio_secs + 2.0) / 2) * 2)))
    return user
def old_rework(audio_secs):                            # the rule the three rework copies had
    return max(4, min(8, int(((audio_secs + 2.0 + 1.99) // 2) * 2)))
same = all(sr.clip_seconds_for_audio(x / 10, 5) == old_first_generation(x / 10, 5) for x in range(1, 400))
check("T1 clip length equals the first-generation rule for audio 0.1-39.9 s", same)
check("T2 12 s of speech -> 14 s clip (the old rework rule gave 8 s)", sr.clip_seconds_for_audio(12.0, 5) == 14 and old_rework(12.0) == 8, (sr.clip_seconds_for_audio(12.0, 5), old_rework(12.0)))
check("T3 short audio still gets the 6 s minimum", sr.clip_seconds_for_audio(1.0, 5) == 6)
check("T4 no measurement / zero / None -> the scene's own duration",
      sr.clip_seconds_for_audio(None, 5) == 5 and sr.clip_seconds_for_audio(0, 7) == 7 and sr.clip_seconds_for_audio("x", 9) == 9)
check("T5 maximum 20 s", sr.clip_seconds_for_audio(60, 5) == 20)

# ── source image ────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    jd = Path(d); (jd / "images").mkdir()
    check("I1 no photo -> None", sr.find_source_image(jd, "sc_a", 0) is None)
    (jd / "images" / "scene_002.png").write_bytes(b"x")
    p = sr.find_source_image(jd, "sc_c", 2)
    check("I2 legacy scene_NNN photo is found and copied to the scene_id name", p is not None and p.name == "sc_c.png" and (jd / "images" / "sc_c.png").exists())
    (jd / "images" / "sc_b.webp").write_bytes(b"y")
    check("I3 scene_id photo wins", sr.find_source_image(jd, "sc_b", 1).name == "sc_b.webp")

# ── scene status ────────────────────────────────────────────────────────────
def first_gen_statuses(n=6, reject_at=4):
    return [{"index": i, "caption": f"c{i}", "video": "ok", "audio": "skipped",
             "qc_verdict": "reject" if i == reject_at else "pass"} for i in range(n)]
st = first_gen_statuses()
e = sr.update_scene_status(st, "sc_new5", 4, {"caption": "c4"}, video="ok", duration_used=5, qc_verdict="pass")
check("S1 first-generation entry (index, no scene_id) is updated in place: still 6 entries", len(st) == 6 and st[4] is e)
check("S2 stale 'reject' becomes 'pass' and the entry now carries its scene_id", e["qc_verdict"] == "pass" and e["scene_id"] == "sc_new5")
e2 = sr.update_scene_status(st, "sc_new5", 4, {"caption": "c4"}, video="ok", duration_used=5, qc_verdict="pass")
check("S3 a SECOND rework of the same scene still gives 6 entries (matched by scene_id)", len(st) == 6 and e2 is e)
st2 = first_gen_statuses() + [{"scene_id": "sc_x", "index": 4, "caption": "c4", "video": "ok", "audio": "skipped", "qc_verdict": "pass"}]
sr.update_scene_status(st2, "sc_x", 4, {"caption": "c4"}, video="ok", qc_verdict="pass")
check("S4 job already damaged by the old code (6 + appended twin) is repaired to 6 entries", len(st2) == 6 and sum(1 for s in st2 if s["index"] == 4) == 1 and st2[4]["qc_verdict"] == "pass" and st2[4]["scene_id"] == "sc_x", json.dumps(st2[4]))
st3 = first_gen_statuses(3)
sr.update_scene_status(st3, "sc_added", 3, {"caption": "nuova"}, video="ok")
check("S5 a scene added later is appended once", len(st3) == 4 and st3[3]["scene_id"] == "sc_added" and st3[3]["index"] == 3)
st4 = first_gen_statuses(3)
sr.update_scene_status(st4, "sc_a", 1, {}, audio="ok")
check("S6 audio-only touches only audio (video / duration untouched)", st4[1]["audio"] == "ok" and st4[1]["video"] == "ok" and "duration_used" not in st4[1] and st4[1]["qc_verdict"] == "pass")

# ── cost record: same numbers as the three old copies ───────────────────────
def old_block(job, scenes_redone, models, redo_video, redo_audio, chars, tier):   # verbatim old logic
    rc = ct.calculate_rework_cost(scenes_redone=scenes_redone, models_used=models, redo_video=redo_video,
                                  redo_audio=redo_audio, audio_chars=chars, model_tier=tier)
    job.setdefault("reworks", []).append(rc)
    raw = job.get("cost_actual_raw")
    if raw:
        job["cost_actual"] = ct.format_cost_display(raw, previous_reworks=job["reworks"])
    else:
        lt = (job.get("cost_actual") or {}).get("grand_total_eur", 0)
        job["cost_actual"] = ct.format_cost_display({"type": "actual", "total_eur": lt, "model_tier": tier}, previous_reworks=job["reworks"])
    return rc
def strip(rc): return {k: v for k, v in rc.items() if k != "calculated_at"}
for tier in ("luma", "premium", "standard", "eco"):
    for with_raw in (True, False):
        base = {"model_tier": tier}
        if with_raw: base["cost_actual_raw"] = {"type": "actual", "total_eur": 8.5, "video_eur": 7.0, "model_tier": tier, "scenes": 6}
        else: base["cost_actual"] = {"grand_total_eur": 8.5}
        a, b = copy.deepcopy(base), copy.deepcopy(base)
        redone = [{"duration": 6, "had_voiceover": False, "voiceover_chars": 0},
                  {"duration": 14, "had_voiceover": True, "voiceover_chars": 140}]
        ra = old_block(a, [{"duration": 6}, {"duration": 14}], [tier] * 2, True, True, 140, tier)
        rb = sr.record_rework_cost(b, redone, tier, True)
        check(f"C1 video rework cost identical to the old block ({tier}, raw={with_raw})", strip(ra) == strip(rb) and a["cost_actual"] == b["cost_actual"], (ra, rb))
        a, b = copy.deepcopy(base), copy.deepcopy(base)
        ra = old_block(a, [], [], False, True, 300, tier)
        rb = sr.record_rework_cost(b, [{"duration": 0, "had_voiceover": True, "voiceover_chars": 300}], tier, False)
        check(f"C2 audio-only / narration cost identical to the old block ({tier}, raw={with_raw})", strip(ra) == strip(rb) and a["cost_actual"] == b["cost_actual"], (ra, rb))
check("C3 nothing redone -> no cost record", sr.record_rework_cost({"reworks": []}, [], "luma", True) is None)

# ── the engine with fakes ───────────────────────────────────────────────────
class Fakes:
    def __init__(self, tts_ok=True, video_ok=None, audio_secs=3.0, wm_ok=True):
        self.calls = []; self.tts_ok = tts_ok; self.video_ok = video_ok or {}; self.audio_secs = audio_secs
        self.wm_ok = wm_ok; self.enh_args = None
        self.saved = 0; self.progress_log = []
    def deps(self):
        async def to_thread(fn, *a, **kw): return fn(*a, **kw)
        def gs(text, out, voice_id=None):
            self.calls.append(("tts", text, voice_id))
            if self.tts_ok: Path(out).write_bytes(b"mp3")
            return self.tts_ok
        def vid(img, secs, out, **kw):
            sid = Path(out).stem
            self.calls.append(("video", sid, secs, kw))
            ok = self.video_ok.get(sid, True)
            if ok: Path(out).write_bytes(b"mp4")
            return ok
        def enh(src, dst, do_lighting=True, do_upscale=True):
            self.calls.append(("enhance", Path(src).name)); self.enh_args = (Path(src).name, Path(dst).name, do_lighting, do_upscale)
            Path(dst).write_bytes(b"jpg")
        def rm(src, dst):
            self.calls.append(("watermark", Path(src).name))
            if self.wm_ok: Path(dst).write_bytes(b"dewm")
            return {"ok": self.wm_ok}
        return types.SimpleNamespace(generate_speech=gs, audio_seconds=lambda p: self.audio_secs, enhance=enh, remove_watermark=rm,
                                     generate_video=vid, to_thread=to_thread, save=lambda: setattr(self, "saved", self.saved + 1),
                                     progress=lambda pct, msg: self.progress_log.append((pct, msg)), log=log)
    def kinds(self): return [c[0] for c in self.calls]

def make_job(d, n=6, voiceovers=None, tier="luma"):
    jd = Path(d); (jd / "images").mkdir(exist_ok=True)
    cfg, sts = [], []
    for i in range(n):
        sid = f"sc_{i}"
        (jd / "images" / f"{sid}.jpg").write_bytes(b"i")
        cfg.append({"scene_id": sid, "caption": f"c{i}", "voiceover": (voiceovers or {}).get(i, ""), "duration": 5,
                    "space_type": "large", "pov_movement": "walk_in_explore"})
        sts.append({"index": i, "caption": f"c{i}", "video": "ok", "audio": "skipped", "qc_verdict": "reject" if i == 4 else "pass"})
    return {"scenes_config": cfg, "scenes": sts, "model_tier": tier, "voice_id": "VOICE1", "lighting": "bright_natural",
            "intensity": "natural_pace", "output_format": "landscape", "do_video_upscale": True}

def run(coro): return asyncio.run(coro)

with tempfile.TemporaryDirectory() as d:     # URL/Relinx job: no per-scene voiceover
    job = make_job(d); f = Fakes()
    r = run(sr.redo_scenes(job, d, ["sc_4"], f.deps()))
    check("E1 URL-style scene (no voiceover): no TTS call, enhance then one clip at the configured 5 s", f.kinds() == ["enhance", "video"] and f.calls[1][2] == 5, f.calls)
    check("E2 result lists the scene as redone with its duration", r["redone"] == [{"scene_id": "sc_4", "duration": 5, "had_voiceover": False, "voiceover_chars": 0}] and not r["failed"], r)
    check("E3 status: still 6 entries, scene 5 no longer 'reject', audio 'skipped'", len(job["scenes"]) == 6 and job["scenes"][4]["qc_verdict"] == "pass" and job["scenes"][4]["audio"] == "skipped" and job["scenes"][4]["scene_id"] == "sc_4")
    kw = f.calls[1][3]
    check("E4 job settings reach the clip call (tier, format, lighting, upscale)", kw["model_tier"] == "luma" and kw["output_format"] == "landscape" and kw["lighting"] == "bright_natural" and kw["do_video_upscale"] is True and kw["space_type"] == "large", kw)
    check("E5 clip file written under the scene id", (Path(d) / "clips" / "sc_4.mp4").exists())
    r = run(sr.redo_scenes(job, d, ["sc_4"], Fakes().deps()))
    check("E6 second rework of the same scene: still 6 status entries", len(job["scenes"]) == 6 and len(r["redone"]) == 1)

with tempfile.TemporaryDirectory() as d:     # manual job with voiceover
    job = make_job(d, voiceovers={1: "Una frase di prova lunga abbastanza."}); f = Fakes(audio_secs=12.0)
    r = run(sr.redo_scenes(job, d, ["sc_1"], f.deps()))
    check("E7 voiceover scene: TTS with the JOB voice, then a 14 s clip (12 s speech + buffer)", f.kinds() == ["tts", "enhance", "video"] and f.calls[0][2] == "VOICE1" and f.calls[2][2] == 14, f.calls)
    check("E8 voiceover scene status audio ok, duration_used 14", job["scenes"][1]["audio"] == "ok" and job["scenes"][1]["duration_used"] == 14)
    check("E9 redone record carries the voiceover characters (for the TTS cost)", r["redone"][0]["voiceover_chars"] == len("Una frase di prova lunga abbastanza.") and r["redone"][0]["had_voiceover"])

with tempfile.TemporaryDirectory() as d:     # TTS fails during a video rework -> keep going with the configured length
    job = make_job(d, voiceovers={1: "Frase."}); f = Fakes(tts_ok=False)
    r = run(sr.redo_scenes(job, d, ["sc_1"], f.deps()))
    check("E10 TTS failure in a video rework does not stop the clip (old behaviour kept)", f.kinds() == ["tts", "enhance", "video"] and f.calls[2][2] == 5 and len(r["redone"]) == 1)

with tempfile.TemporaryDirectory() as d:     # batch: partial failures
    job = make_job(d); f = Fakes(video_ok={"sc_2": False})
    (Path(d) / "images" / "sc_3.jpg").unlink()
    r = run(sr.redo_scenes(job, d, ["sc_1", "sc_2", "sc_3", "sc_nope"], f.deps()))
    check("E11 batch: failed clip and missing photo are reported as failed, unknown id as skipped, the rest done",
          [x["scene_id"] for x in r["redone"]] == ["sc_1"] and r["failed"] == ["sc_2", "sc_3"] and r["skipped"] == ["sc_nope"], r)
    check("E12 failed scenes keep their old status entry untouched", job["scenes"][2]["qc_verdict"] == "pass" and "scene_id" not in job["scenes"][2] and len(job["scenes"]) == 6)

with tempfile.TemporaryDirectory() as d:     # strict (adding a scene)
    job = make_job(d)
    try: run(sr.redo_scenes(job, d, ["sc_zz"], Fakes().deps(), strict=True)); ok = False
    except sr.RedoError as e: ok = "not found" in str(e)
    check("E13 strict: unknown scene raises", ok)
    try: run(sr.redo_scenes(job, d, ["sc_2"], Fakes(video_ok={"sc_2": False}).deps(), strict=True)); ok = False
    except sr.RedoError as e: ok = "Video generation failed" in str(e)
    check("E14 strict: failed clip raises (the job is marked failed by the caller)", ok)
    (Path(d) / "images" / "sc_3.jpg").unlink()
    try: run(sr.redo_scenes(job, d, ["sc_3"], Fakes().deps(), strict=True)); ok = False
    except sr.RedoError as e: ok = "No source image" in str(e)
    check("E15 strict: missing photo raises", ok)
    job2 = make_job(d); job2["scenes"] = job2["scenes"][:3]
    job2["scenes_config"].append({"scene_id": "sc_new", "caption": "n", "voiceover": "", "duration": 8})
    (Path(d) / "images" / "sc_new.jpg").write_bytes(b"i")
    run(sr.redo_scenes(job2, d, ["sc_new"], Fakes().deps(), strict=True))
    check("E16 added scene gets exactly one new status entry", len(job2["scenes"]) == 4 and job2["scenes"][3]["scene_id"] == "sc_new")

with tempfile.TemporaryDirectory() as d:     # audio-only
    job = make_job(d, voiceovers={0: "Prima frase.", 2: "Terza frase."}); f = Fakes()
    before = copy.deepcopy(job["scenes"])
    r = run(sr.redo_scenes(job, d, ["sc_0", "sc_1", "sc_2"], f.deps(), video=False, label="Rework audio"))
    check("E17 audio-only: only TTS calls, never enhance or video", f.kinds() == ["tts", "tts"], f.calls)
    check("E18 audio-only: scene without voiceover is skipped, two redone", r["skipped"] == ["sc_1"] and len(r["redone"]) == 2 and not r["failed"], r)
    check("E19 audio-only: video and duration fields untouched, audio ok", job["scenes"][0]["audio"] == "ok" and job["scenes"][0]["video"] == before[0]["video"] and "duration_used" not in job["scenes"][0] and len(job["scenes"]) == 6)
    check("E20 audio-only: no clip written", not (Path(d) / "clips").exists() or not list((Path(d) / "clips").glob("*.mp4")))
    f2 = Fakes(tts_ok=False)
    r = run(sr.redo_scenes(job, d, ["sc_0"], f2.deps(), video=False))
    check("E21 audio-only TTS failure: skipped, nothing recorded", r["skipped"] == ["sc_0"] and not r["redone"])

# ── 2026-10-29: rework prepares the photo like the first generation (watermark only if asked, the job's own flags) ──
check("F0 enhance_flags: job flags, both True when the job does not say",
      sr.enhance_flags({}) == (True, True) and sr.enhance_flags({"enhance_images": True, "upscale_images": False}) == (True, False)
      and sr.enhance_flags({"enhance_images": False, "upscale_images": False}) == (False, False))
with tempfile.TemporaryDirectory() as d:     # job made WITHOUT the 4x upscale: the rework must not put it back
    job = make_job(d); job["upscale_images"] = False; f = Fakes()
    run(sr.redo_scenes(job, d, ["sc_4"], f.deps()))
    check("F1 job with upscale_images=False: enhance called with (lighting True, upscale False)", f.enh_args and f.enh_args[2:] == (True, False), f.enh_args)
    check("F2 no watermark call on a scene without the flag (API / unchecked)", "watermark" not in f.kinds(), f.calls)
with tempfile.TemporaryDirectory() as d:     # both flags off: the photo goes through unchanged settings
    job = make_job(d); job["enhance_images"] = False; job["upscale_images"] = False; f = Fakes()
    run(sr.redo_scenes(job, d, ["sc_4"], f.deps()))
    check("F3 both flags off: enhance called with (False, False)", f.enh_args and f.enh_args[2:] == (False, False), f.enh_args)
with tempfile.TemporaryDirectory() as d:     # watermark requested: removal first, enhancement works on the dewatermarked photo
    job = make_job(d); job["scenes_config"][4]["remove_watermark"] = True; f = Fakes()
    r = run(sr.redo_scenes(job, d, ["sc_4"], f.deps()))
    check("F4 flagged scene: watermark removal, then enhance, then clip (in this order)", f.kinds() == ["watermark", "enhance", "video"], f.calls)
    check("F5 enhance works on the dewatermarked photo and writes the dewm-named file", f.enh_args[0] == sr.dewatermarked_name("sc_4") and "_dewm_" in f.enh_args[1], f.enh_args)
    check("F6 removal is done on the ORIGINAL photo of the scene", f.calls[0] == ("watermark", "sc_4.jpg"), f.calls)
    check("F7 clean run: no watermark_failed in the result", "watermark_failed" not in r and r["redone"], r)
    f2 = Fakes()
    run(sr.redo_scenes(job, d, ["sc_4"], f2.deps()))
    check("F8 second rework of the same scene reuses both files: no removal, no enhancement, only the clip", f2.kinds() == ["video"], f2.calls)
with tempfile.TemporaryDirectory() as d:     # removal fails: original photo used, scene still redone, failure reported
    job = make_job(d); job["scenes_config"][4]["remove_watermark"] = True; f = Fakes(wm_ok=False)
    r = run(sr.redo_scenes(job, d, ["sc_4"], f.deps()))
    check("F9 failed removal: original photo enhanced, clip made, scene reported in watermark_failed",
          f.enh_args[0] == "sc_4.jpg" and "_dewm_" not in f.enh_args[1] and r["watermark_failed"] == ["sc_4"] and len(r["redone"]) == 1, (f.enh_args, r))
with tempfile.TemporaryDirectory() as d:     # an old enhanced file made with other settings is never reused
    job = make_job(d); job["upscale_images"] = False
    (Path(d) / "enhanced").mkdir(); (Path(d) / "enhanced" / "sc_4_enhanced.jpg").write_bytes(b"old forced lighting+upscale")
    f = Fakes()
    run(sr.redo_scenes(job, d, ["sc_4"], f.deps()))
    check("F10 a stale sc_NN_enhanced.jpg from the old forced settings is ignored", "enhance" in f.kinds() and f.enh_args[1] == sr.enhanced_name("sc_4", False, True, False), f.enh_args)
check("F11 enhanced_name differs for every combination of flags and watermark",
      len({sr.enhanced_name("s", w, l, u) for w in (0, 1) for l in (0, 1) for u in (0, 1)}) == 8)

# ── call sites in api_server.py (it cannot be imported here: no fastapi) ─────
src = open("api_server.py").read()
def body(name):
    m = re.search(rf"^async def {name}\(.*?(?=^\S)", src, re.S | re.M)
    return m.group(0) if m else ""
for name, kw in (("run_redo_scene", "video=True, strict=True, policy=False"),
                 ("run_redo_scenes_batch", "video=True, strict=False, policy=True"),
                 ("run_redo_audio_only", "video=False, strict=False, policy=True")):
    b = body(name)
    check(f"A1 {name} is a thin wrapper over _run_redo ({kw})", "_run_redo(" in b and kw in b and len(b.splitlines()) <= 8, b[:200])
rb = body("_run_redo")
check("A2 _run_redo counts the rework budget only for policy + video", "if policy:" in rb and "_rwp.count(job, scene_ids)" in rb and "if video:" in rb)
check("A3 _run_redo reassembles exactly once, via run_reassemble_only", rb.count("run_reassemble_only(job_id)") == 1)
check("A4 _run_redo always releases the job lock", "finally:" in rb and "_release_job_lock(job_id)" in rb)
check("A5 failed scenes go to _rework_after only for video redo", "_rework_after(job_id, result[\"failed\"])" in rb)
check("A6 no second copy of the per-scene steps left in api_server.py",
      src.count("generate_video_single") == 4 and "Migrated legacy image" not in src and src.count("calculate_rework_cost") <= 1, (src.count("generate_video_single"), src.count("calculate_rework_cost")))
# 4 = import+call in the shared deps (rework) + import+call in the first-generation pipeline
check("A7 first-generation clip length uses the shared rule", "_sr.clip_seconds_for_audio(audio_secs, user_duration)" in src and "int(round(buffered / 2) * 2)" not in src)
check("A8 narration cost uses the shared cost record", "_sr.record_rework_cost(" in src and src.count("previous_reworks=job[\"reworks\"]") == 0)
check("A9 the clip sizes 4-8 rework rule is gone", "int(((buffered + 1.99) // 2) * 2)" not in src)

# ── undefined-name check of the rework wrappers (api_server.py cannot be imported without the server's packages) ──
import ast, builtins
def undefined_names(source, func_names):
    tree = ast.parse(source)
    glob = set(dir(builtins))
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): glob.add(n.name)
        for x in ast.walk(n):
            if isinstance(x, (ast.Import, ast.ImportFrom)):
                for a in x.names: glob.add((a.asname or a.name).split(".")[0])
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store): glob.add(x.id)
    bad = []
    for fn in tree.body:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in func_names:
            loc = set()
            for x in ast.walk(fn):
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    loc |= {a.arg for a in x.args.args + x.args.kwonlyargs}
                    if x.args.vararg: loc.add(x.args.vararg.arg)
                    if x.args.kwarg: loc.add(x.args.kwarg.arg)
                    if not isinstance(x, ast.Lambda): loc.add(x.name)
                if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)): loc.add(x.id)
                if isinstance(x, (ast.Import, ast.ImportFrom)):
                    for a in x.names: loc.add((a.asname or a.name).split(".")[0])
                if isinstance(x, ast.ExceptHandler) and x.name: loc.add(x.name)
            for x in ast.walk(fn):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id not in loc and x.id not in glob:
                    bad.append((fn.name, x.id, x.lineno))
    return bad
bad = undefined_names(src, {"_redo_deps", "_run_redo", "run_redo_scene", "run_redo_scenes_batch", "run_redo_audio_only"})
check("A10 no undefined name in the rework wrappers and runner", not bad, bad)
check("A11 the name check really catches an undefined name (self-test)", undefined_names("def f():\n    return nope_x\n", {"f"}) == [("f", "nope_x", 2)])

print()
print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
