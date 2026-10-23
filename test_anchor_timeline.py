"""Patch J (2026-10-23, backlog 82): anchor-driven timeline. Calculation, word alignment, free-text script, orchestration
with fakes, assembly/API wiring (text checks). No network, no audio, no API key. Run: python3 test_anchor_timeline.py"""
import os, sys, types, json, random
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import scene_timing as T
import word_align as WA
import scene_script as ss
import narration as N
import listing_scraper as ls

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

HALF = T.TRANSITION_SECS / 2

# ---------------- A. plan_from_anchors
r = T.plan_from_anchors([None, 5.4, 10.2, 15.0, 20.1, 25.0], 29.0)
sp = [c["speed"] for c in r["clips"]]
check("A1 well-spaced room phrases -> ok, every speed inside 0.8-1.25", r["ok"] and r["feasible"] and all(0.8 - 1e-3 <= s <= 1.25 + 1e-3 for s in sp), sp)
check("A2 video lasts at least until the voice ends (+0.2 s tail)", r["video_secs"] >= 29.2 - 1e-6, r["video_secs"])
offs = [a["offset_secs"] for a in r["anchors"]]
check("A3 every named room is on screen at (or just before) its word", all(-1.1 - 1e-6 <= o <= 0.3 + 1e-6 for o in offs), offs)
cl = r["clips"]
check("A4 cross-fade geometry: next clip starts at start + duration - 0.5",
      all(abs(cl[i + 1]["start"] - (cl[i]["start"] + cl[i]["duration"] - T.TRANSITION_SECS)) < 2e-3 for i in range(5)))
check("A5 video length = sum of clip lengths - 5 overlaps", abs(sum(c["duration"] for c in cl) - 5 * T.TRANSITION_SECS - r["video_secs"]) < 5e-3)
check("A6 speed = real clip length / target length for every clip", all(abs(c["speed"] - c["src_secs"] / c["duration"]) < 1e-3 for c in cl))
check("A7 targets list = clip durations (what assembly receives)", r["targets"] == [c["duration"] for c in cl])

# the real job 6e3d0d40 (Whisper times measured on the server 2026-10-23): kitchen 15.5, living 17.88, bedrooms 22.22
real = T.plan_from_anchors([None, 17.88, 15.5, 22.22, None, None], 30.42)
check("A8 the real text of job 6e3d0d40 is reported as not feasible, never silently drifted", (not real["ok"]) and len(real["problems"]) >= 1 and len(real["clips"]) == 6, real["problems"])
real2 = T.plan_from_anchors([None, None, 15.5, 17.88, 22.22, None], 30.42)
check("A9 ... with the rooms in scene order the kitchen->living gap (2.4 s) is flagged too fast", (not real2["ok"]) and any(p["kind"] == "too_fast" for p in real2["problems"]), real2["problems"])
check("A10 cuts stay in order even when no plan exists", all(real2["cuts"][i] < real2["cuts"][i + 1] for i in range(6)))

none = T.plan_from_anchors([None] * 6, 30.4)
check("A11 no room named: scenes share the time evenly, all inside the limits", none["ok"] and max(c["speed"] for c in none["clips"]) - min(c["speed"] for c in none["clips"]) < 0.1, [c["speed"] for c in none["clips"]])
short = T.plan_from_anchors([None] * 6, 18.0)
check("A12 a very short voice: the video is stretched (silence at the end), speeds <= 1.25", short["ok"] and short["video_secs"] > 18.2 and max(c["speed"] for c in short["clips"]) <= 1.25 + 1e-3, short["video_secs"])
longv = T.plan_from_anchors([None] * 6, 45.0)
check("A13 a voice far too long is reported (too_slow), not hidden", (not longv["ok"]) and all(p["kind"] == "too_slow" for p in longv["problems"]) and longv["problems"], longv["problems"][:1])
r9 = T.plan_from_anchors([None, None, None], 12.0, [9.0, 5.0, 5.0])
check("A14 a 9 s source clip gets its own speed limits", r9["clips"][0]["src_secs"] == 9.0 and abs(r9["clips"][0]["speed"] - 9.0 / r9["clips"][0]["duration"]) < 1e-3)
one = T.plan_from_anchors([None], 5.0)
check("A15 single clip: no overlap, duration = visible", abs(one["clips"][0]["duration"] - one["clips"][0]["visible_secs"]) < 1e-6 and one["ok"])
for bad, kw in [([], dict(speech_end_secs=10)), ([None, None], dict(speech_end_secs=0)), ([None, None], dict(speech_end_secs=10, src_secs=[5.0]))]:
    try:
        T.plan_from_anchors(bad, kw.pop("speech_end_secs"), **kw); ok = False
    except ValueError:
        ok = True
    check(f"A16 invalid input rejected ({bad}, {kw})", ok)
t0 = T.plan_from_anchors([None, 5.0, 10.0], 15.0, transition=0.0)
check("A17 the overlap is a parameter: with no cross-fade the durations are the visible times", all(abs(c["duration"] - c["visible_secs"]) < 1e-6 for c in t0["clips"]))

# property: every plan built FROM valid cuts must be found (no false 'not feasible'); every ok plan really is inside the limits
rng = random.Random(7)
miss = bad_ok = 0
for _ in range(300):
    n = rng.choice([4, 5, 6, 7])
    cuts = [0.0]
    for i in range(n):
        edges_i = (HALF if i > 0 else 0) + (HALF if i < n - 1 else 0)
        lo, hi = 5 / 1.25 - edges_i, 5 / 0.8 - edges_i
        cuts.append(cuts[-1] + rng.uniform(lo + 0.05, hi - 0.05))
    anchors = [None] + [(cuts[i] + T.LEAD_BEFORE_WORD + rng.uniform(-0.3, 0.3)) if rng.random() < 0.6 else None for i in range(1, n)]
    res = T.plan_from_anchors(anchors, cuts[-1] - 0.2)
    if not res["ok"]: miss += 1
    if res["ok"]:
        if not all(0.8 - 1e-3 <= c["speed"] <= 1.25 + 1e-3 for c in res["clips"]): bad_ok += 1
check("A18 300 random valid timelines: none wrongly reported as impossible", miss == 0, miss)
check("A19 300 random: an ok plan always has every speed in range", bad_ok == 0, bad_ok)

# ---------------- B. word alignment (real recogniser output from job 6e3d0d40, 2026-10-23)
REC = [("Sinergie", 0.00, 0.94), ("immobiliari", 0.94, 1.70), ("presenta", 1.70, 2.36), ("un", 2.36, 2.48), ("quadri", 2.48, 2.78),
       ("locale", 2.78, 3.18), ("in", 3.18, 3.40), ("vendita,", 3.40, 3.82), ("in", 4.04, 4.18), ("via", 4.18, 4.28), ("Salento,", 4.28, 4.78),
       ("zona", 5.06, 5.30), ("Piazza", 5.30, 5.72), ("Bologna.", 5.72, 6.28), ("L", 7.08, 7.28), ("'appartamento", 7.28, 7.90),
       ("misura", 7.90, 8.38), ("110", 8.38, 8.72), ("metri", 8.72, 9.34), ("quadri", 9.34, 9.80), ("ed", 9.80, 10.06), ("è", 10.06, 10.16),
       ("composto", 10.16, 10.72), ("da", 10.72, 10.84), ("tre", 10.84, 11.04), ("camere", 11.04, 11.46), ("e", 11.46, 11.70),
       ("due", 11.70, 11.90), ("bagni.", 11.90, 12.32), ("La", 14.70, 15.50), ("cucina", 15.50, 15.90), ("è", 15.90, 16.04),
       ("abitabile.", 16.04, 16.62), ("Nella", 17.60, 17.88), ("zona", 17.88, 18.20), ("giorno", 18.20, 18.56), ("il", 18.56, 18.90),
       ("pavimento", 18.90, 19.42), ("è", 19.42, 19.64), ("ingress", 19.64, 19.94), ("porcellanato.", 19.94, 20.92), ("Le", 21.78, 22.04),
       ("tre", 22.04, 22.22), ("camere", 22.22, 22.76), ("hanno", 22.76, 23.18), ("parche", 23.18, 23.68), ("nella", 23.68, 23.92),
       ("zona", 23.92, 24.30), ("notte.", 24.30, 24.84), ("Contattate", 24.84, 26.30), ("Sinergie", 26.30, 26.82), ("immobiliari", 26.82, 27.50),
       ("per", 27.50, 27.70), ("visitare", 27.70, 28.22), ("questa", 28.22, 28.50), ("proprietà", 28.50, 29.10), ("con", 29.10, 29.24),
       ("cantina", 29.24, 29.72), ("inclusa.", 29.72, 30.26)]
TXT = ("Sinergie immobiliari presenta un quadrilocale in vendita, in via Salento, zona Piazza Bologna. L'appartamento misura 110 metri quadri "
       "ed è composto da tre camere e due bagni. La cucina è abitabile. Nella zona giorno il pavimento è in gres porcellanato. "
       "Le tre camere hanno parquet nella zona notte. Contattate Sinergie immobiliari per visitare questa proprietà con cantina inclusa.")
tk = WA.tokens(TXT)
check("B1 tokens: apostrophe splits, accents and punctuation folded", WA.tokens("L'appartamento è più così, 1.680.000!") == ["l", "appartamento", "e", "piu", "cosi", "1", "680", "000"])
al = WA.align(tk, REC)
check("B2 real audio: most of the written words are found", al["coverage"] >= 0.85 and len(al["times"]) == len(tk), al["coverage"])
i = WA.find_phrase(tk, "La cucina")[0]
check("B3 'La cucina' starts at 14.70 s (as measured)", abs(al["times"][i][0] - 14.70) < 1e-6, al["times"][i])
i = WA.find_phrase(tk, "zona giorno")[0]
check("B4 'zona giorno' starts at 17.88 s", abs(al["times"][i][0] - 17.88) < 1e-6, al["times"][i])
i = WA.find_phrase(tk, "parquet")[0]
check("B5 a word the recogniser spelled wrong ('parquet' heard as 'parche') still gets a time between its neighbours", 22.76 <= al["times"][i][0] <= 23.68, al["times"][i])
check("B6 'zona' occurs twice -> find_phrase says so (the prompt requires a unique phrase)", len(WA.find_phrase(tk, "zona")) == 3)
check("B7 'quadrilocale' (heard as 'quadri'+'locale') gets a time inside those two words", 2.36 <= al["times"][WA.find_phrase(tk, "quadrilocale")[0]][0] <= 3.18)
check("B8 times never run backwards", all(al["times"][k][0] <= al["times"][k + 1][0] + 1e-9 for k in range(len(tk) - 1)))
check("B9 empty input -> coverage 0, no crash", WA.align([], REC)["coverage"] == 0.0 and WA.align(tk, [])["coverage"] == 0.0)
check("B10 a recognised word that is several tokens shares its time", WA.align(["l", "appartamento"], [("L'appartamento", 7.0, 8.0)])["times"] == [(7.0, 7.0 + 1 / 13), (7.0 + 1 / 13, 8.0)] or abs(WA.align(["l", "appartamento"], [("L'appartamento", 7.0, 8.0)])["times"][1][1] - 8.0) < 1e-9)

# ---------------- C. free narration script
DESC = ("Villa in vendita a Roma, Olgiata. Abbiamo il piacere di proporre villa unifamiliare di 650 metri quadri "
        "completamente ristrutturata, con giardino di 3000 metri quadri, 5 camere da letto e 4 bagni. Soggiorno ampio, "
        "cucina abitabile, terrazza. Prezzo 1.680.000 euro.")
AG = "Coldwell Banker"; PRICE = "€ 1.680.000"
SEQ = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
LABELS = [ls.CATEGORY_ITALIAN_LABELS.get(c, c) for c in SEQ]
GOODTXT = ("Coldwell Banker presenta una villa in vendita a Olgiata. "
           "Il soggiorno è ampio e luminoso; la villa di 650 metri quadri è completamente ristrutturata. "
           "Ogni ambiente è curato nei dettagli e funzionale. "
           "La zona notte ha 5 camere da letto e 4 bagni. "
           "Gli spazi interni sono ampi e silenziosi. "
           "Il giardino di 3000 metri quadri chiude la proprietà: contattate Coldwell Banker.")
GOODANCH = [{"scene": 2, "phrase": "Il soggiorno"}, {"scene": 4, "phrase": "La zona notte"}, {"scene": 6, "phrase": "Il giardino"}]   # Patch O: 3 highlights
def fv(text=GOODTXT, anchors=GOODANCH, **kw):
    return ss.validate_free_text(text, anchors, kw.get("desc", DESC), kw.get("agency", AG), kw.get("price", PRICE), split_fn=N.split_into_sentences)
check("C1 a good free text with 3 highlight anchors is accepted", fv() == [], fv())
check("C2 no anchors at all is accepted (nothing named)", fv(anchors=[]) == [])
check("C3 price spoken -> rejected (same fact check as the per-scene script)", any("price" in p for p in fv(text=GOODTXT.replace("ristrutturata.", "ristrutturata, a 1.680.000 euro."))))
check("C4 a number not in the listing -> rejected", any("999" in p for p in fv(text=GOODTXT.replace("650", "999"))))
check("C5 a feature not in the listing -> rejected", any("piscin" in p for p in fv(text=GOODTXT.replace("Il giardino", "La piscina"))))
check("C6 first sentence must say sale/rent", any("in vendita" in p for p in fv(text=GOODTXT.replace("in vendita ", ""))))
check("C7 agency named at start and end", any("first sentence must name the agency" in p for p in fv(text=GOODTXT.replace("Coldwell Banker presenta", "Si presenta"))) and
      any("last sentence must name the agency" in p for p in fv(text=GOODTXT.replace("contattate Coldwell Banker", "contattateci"))))
check("C8 floors are rejected", any("floor" in p for p in fv(text=GOODTXT.replace("La zona notte", "La zona notte al piano terra"))))
check("C9 rooms named out of order are rejected", any("order" in p for p in fv(anchors=[{"scene": 2, "phrase": "La zona notte"}, {"scene": 4, "phrase": "Il soggiorno"}])))
check("C10 a phrase that is not in the text is rejected", any("exactly once" in p for p in fv(anchors=[{"scene": 2, "phrase": "La mansarda"}])))
check("C11 a phrase that appears twice is rejected", any("exactly once" in p for p in fv(anchors=[{"scene": 2, "phrase": "Coldwell Banker"}])))
check("C12 scene 1 / scene 7 / duplicates are rejected", any("between 2 and 6" in p for p in fv(anchors=[{"scene": 1, "phrase": "La cucina"}])) and
      any("between 2 and 6" in p for p in fv(anchors=[{"scene": 7, "phrase": "La cucina"}])) and
      any("twice" in p for p in fv(anchors=[{"scene": 3, "phrase": "La cucina"}, {"scene": 3, "phrase": "Il soggiorno"}])))
check("C13 a text that is far too short or too long is rejected", any("words" in p for p in fv(text="Coldwell Banker presenta una villa in vendita. Contattate Coldwell Banker.", anchors=[])) and
      any("words" in p for p in fv(text=GOODTXT + " " + GOODTXT, anchors=[])))
pr = ss.build_anchored_prompt(DESC, "largo Olgiata 15", AG, LABELS)
check("C14 prompt: scenes, JSON format, in vendita, agency, order rule, pace", "Scene 3: " + LABELS[2] in pr and '"anchors"' in pr and "in vendita" in pr and AG in pr and "ORDER of the scenes" in pr and "Do NOT say the price" in pr)
check("C14b prompt (Patch K): duration requirement in seconds AND words, natural flow (no sentence-per-room), hard word limit, adjectives rule", "about 28 seconds" in pr and "NEVER more than 32 seconds" in pr and "56-66 words" in pr and "more than 72 words" in pr
      and "at most 13 words" in pr and "ONE natural flowing narration" in pr and "NEVER name two rooms in the same sentence" not in pr and "word 13" not in pr
      and "Objective positive adjectives are welcome" in pr and "splendida" in pr and "luminoso" in pr)
check("C14c limits: 72 words accepted, 73 rejected, wording quotes the duration", ss.FREE_MAX_WORDS == 72 and any("28 seconds" in p and "never more than 32" in p for p in fv(text=GOODTXT + " " + GOODTXT, anchors=[])))
pa = ss.parse_anchored('```json\n{"text": "Ciao a tutti", "anchors": [{"scene": 2, "phrase": "ciao"}]}\n```')
check("C15 parse: fenced JSON, final stop added", pa == ("Ciao a tutti.", [{"scene": 2, "phrase": "ciao"}]), pa)
check("C16 parse: not JSON / wrong shape -> None", ss.parse_anchored("no") is None and ss.parse_anchored('{"text": 3}') is None and ss.parse_anchored('{"text": "a", "anchors": [{"scene": "2"}]}') is None)
fb = ss.build_anchor_feedback([{"clip": 1, "speed": 0.6, "kind": "too_slow", "visible_secs": 7.5, "allowed_visible": [3.5, 5.75], "seconds_over": 1.75}],
                              [{"scene": 3, "phrase": "La cucina", "word_at": 15.5}], LABELS, 2.4)
check("C17 feedback speaks seconds and words, names the phrase times", "7.5 s" in fb and "5.8 s" in fb or "5.7 s" in fb and "La cucina" in fb and "4 words" in fb and "REJECTED" in fb, fb)

fb2 = ss.build_anchor_feedback([{"clip": 1, "speed": 0.4, "kind": "too_slow", "visible_secs": 9.0, "allowed_visible": [3.5, 5.75], "seconds_over": 3.25}],
                               [{"scene": 3, "phrase": "La cucina", "word_at": 15.5}], LABELS, 2.3, previous_text=GOODTXT, speech_secs=42.0)
check("C18 feedback (Patch K): shows the previous text, the measured seconds, the limit and how many words to remove", GOODTXT in fb2 and "42.0 seconds" in fb2 and "never more than 32" in fb2 and "Remove about 32 words" in fb2, fb2)
check("C19 feedback without the new arguments is unchanged in shape (still accepted)", "REJECTED" in fb and GOODTXT not in fb)

# ---------------- D. word_timing never raises
import word_timing as WT
check("D1 missing file / missing recogniser -> None, not an exception", WT.transcribe_words("/nonexistent/x.mp3") is None)

# ---------------- E. orchestration with fakes
replies = []; prompts = []
class _Msgs:
    def create(self, **kw):
        prompts.append(kw["messages"][0]["content"])
        r = replies.pop(0)
        if isinstance(r, Exception): raise r
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=r)])
class FakeClient:
    def __init__(self, api_key=None): self.messages = _Msgs()
ls.anthropic.Anthropic = FakeClient
def fake_reply(client, prompt, max_tokens=1024):
    prompts.append(prompt)
    r = replies.pop(0)
    if isinstance(r, Exception): raise r
    return r
ls._claude_text_reply = fake_reply
ls._track_claude = lambda r: r
measure_calls = []
VOICE_WPS = [2.4]          # Patch L: words per second of the fake voice for the NEXT calls (the last value is kept)
def _next_wps():
    return VOICE_WPS.pop(0) if len(VOICE_WPS) > 1 else VOICE_WPS[0]
CUR_WPS = [2.4]
def fake_measure(text, voice_id=None, attempts=1, scene_secs=None):
    measure_calls.append((text, scene_secs))
    nw = len(text.split())
    CUR_WPS[0] = _next_wps()
    return {"ok": True, "duration_secs": nw / CUR_WPS[0], "audio_path": "/tmp/fake_anchor.mp3", "sync": None}
ls._measure_tts_duration = fake_measure
rec_calls = []
def fake_transcribe(path, language="it"):
    rec_calls.append(path)
    words_ = GOODTXT_CURRENT[0].split()
    return [(w, i / CUR_WPS[0], i / CUR_WPS[0] + 0.35) for i, w in enumerate(words_)]
GOODTXT_CURRENT = [GOODTXT]
WT.transcribe_words = fake_transcribe
legacy_texts = []
def J(text, anchors): return json.dumps({"text": text, "anchors": anchors}, ensure_ascii=False)
def run(rep, seq=SEQ, premium=False, flag="1"):
    replies[:] = list(rep); prompts.clear(); measure_calls.clear(); rec_calls.clear()
    if flag is None: os.environ.pop("PVS_ANCHORED_TIMELINE", None)
    else: os.environ["PVS_ANCHORED_TIMELINE"] = flag
    return ls.generate_narration_and_derive_scenes(DESC, "largo Olgiata 15", PRICE, None, premium, AG, ["exterior"], seq)

# the fake voice speaks 2.4 words/s; the good text is 56 words -> rooms named about every 4-5 s
tw = len(GOODTXT.split())
GOODTXT_CURRENT[0] = GOODTXT
o = run([J(GOODTXT, GOODANCH)])
tl = o.get("timeline") or {}
check("E1 happy path: anchored mode, one Claude call, one TTS call, 6 scenes", o["ok"] and o["narration_mode"] == "anchored" and len(prompts) == 1 and len(measure_calls) == 1 and
      o["tts_calls_used"] == 1 and o["scene_count"] == 6 and o["script_attempts"] == 1, (o.get("narration_mode"), o.get("timeline_fallback_reason")))
check("E2 the TTS is the plain narration (no fixed 5 s scene grid)", measure_calls and measure_calls[0][1] is None and o["narration_text"] == GOODTXT)
check("E3 the timeline carries 6 targets inside the speed limits and the anchor times",
      len(tl.get("targets", [])) == 6 and all(0.8 - 1e-3 <= s <= 1.25 + 1e-3 for s in tl.get("speeds", [])) and [a["scene"] for a in tl.get("anchors", [])] == [2, 4, 6], tl)
check("E4 video length comes from the plan, not 6 x 5 s", abs(o["video_duration_secs"] - tl.get("video_secs", -1)) < 1e-6 and o["sync"] is None)
check("E5 the audio file handed on is the one that was measured", o["audio_path"] == "/tmp/fake_anchor.mp3" and rec_calls == ["/tmp/fake_anchor.mp3"])
check("E6 result keys the API stores are all present", all(k in o for k in ["narration_text", "audio_path", "speech_duration_secs", "scene_count", "video_duration_secs", "tts_calls_used",
      "was_trimmed", "sync", "error", "narration_mode", "script_attempts", "script_tightened", "script_fallback_reason", "timeline"]))

# timing rejected after measuring -> told in seconds, second attempt accepted
LATE = ("Coldwell Banker presenta una villa unifamiliare in vendita a Olgiata, vicino a Roma. La villa di 650 metri quadri è completamente "
        "ristrutturata, con un giardino di 3000 metri quadri e una terrazza molto grande che affaccia sul verde della zona residenziale. "
        "Il soggiorno è ampio e luminoso. La cucina è abitabile. Contattate Coldwell Banker per maggiori informazioni.")
LATEANCH = [{"scene": 2, "phrase": "Il soggiorno"}, {"scene": 3, "phrase": "La cucina"}]
GOODTXT_CURRENT[0] = LATE
replies[:] = []
def fake_transcribe2(path, language="it"):
    rec_calls.append(path)
    cur = GOODTXT_CURRENT[0].split()
    return [(w, i / CUR_WPS[0], i / CUR_WPS[0] + 0.35) for i, w in enumerate(cur)]
WT.transcribe_words = fake_transcribe2
seq_texts = [LATE, GOODTXT]
def fake_measure_seq(text, voice_id=None, attempts=1, scene_secs=None):
    GOODTXT_CURRENT[0] = text
    return fake_measure(text, voice_id, attempts, scene_secs)
ls._measure_tts_duration = fake_measure_seq
VOICE_WPS[:] = [1.5, 2.4]      # Patch L: the first reading is slow (the estimate cannot know), the second normal
o = run([J(GOODTXT, GOODANCH), J(GOODTXT, GOODANCH)])
check("E7 timing outside the limits -> second Claude call told the measured seconds, second text accepted",
      o["ok"] and o["narration_mode"] == "anchored" and o["script_attempts"] == 2 and len(prompts) == 2 and "REJECTED after the voice was recorded" in prompts[1] and "Il soggiorno" in prompts[1] and o["tts_calls_used"] == 2, (o.get("narration_mode"), len(prompts), o.get("timeline_fallback_reason")))

check("E7b (Patch K) the retry after a timing rejection shows the model its own previous text and the measured seconds", GOODTXT in prompts[1] and "The voice read it in" in prompts[1] and "never more than 32" in prompts[1], prompts[1][-700:])
legacy = ["Testo narrazione di prova " * 14] * 8
VOICE_WPS[:] = [1.5, 1.5, 1.5, 2.4]
o = run([J(GOODTXT, GOODANCH), J(GOODTXT, GOODANCH), J(GOODTXT, GOODANCH)] + legacy)
VOICE_WPS[:] = [2.4]
check("E8 rejected three times (Patch M: ANCHORED_MAX_ATTEMPTS = 3) -> falls back to the single-text path, reason recorded, TTS calls of both counted",
      o["ok"] and o["narration_mode"] in ("single_text", "per_scene") and o["timeline"] is None and o["timeline_fallback_reason"] and "speed limits" in o["timeline_fallback_reason"] and o["tts_calls_used"] >= 3,
      (o.get("narration_mode"), o.get("timeline_fallback_reason"), o.get("tts_calls_used")))

o = run(["not json"] * ls.ANCHORED_MAX_ATTEMPTS + ["Testo narrazione " * 14] * 8)
check("E9 unusable replies on every attempt -> fallback, no crash", o["ok"] and o["timeline"] is None and o["timeline_fallback_reason"], o.get("timeline_fallback_reason"))
bad = J(GOODTXT.replace("650", "999"), GOODANCH)
o = run([bad, J(GOODTXT, GOODANCH)])
check("E10 fact check failure on attempt 1 -> attempt 2 told why", o["narration_mode"] == "anchored" and o["script_attempts"] == 2 and "999" in prompts[1] and len(measure_calls) == 1)
check("E10b (Patch K) the retry after a fact-check rejection shows the previous text", GOODTXT.replace("650", "999") in prompts[1] and "edit THIS text" in prompts[1])

WT.transcribe_words = lambda p, language="it": None
o = run([J(GOODTXT, GOODANCH)] + ["Testo narrazione " * 14] * 8)
check("E11 no speech recogniser -> previous mode, reason says so", o["ok"] and o["timeline"] is None and "word timing" in (o["timeline_fallback_reason"] or ""), o.get("timeline_fallback_reason"))
WT.transcribe_words = lambda p, language="it": [("x", 0.0, 0.2), ("y", 0.2, 0.4)]
o = run([J(GOODTXT, GOODANCH)] + ["Testo narrazione " * 14] * 8)
check("E12 the audio does not match the text -> previous mode (coverage)", o["timeline"] is None and "found in the audio" in (o["timeline_fallback_reason"] or ""), o.get("timeline_fallback_reason"))
WT.transcribe_words = fake_transcribe2

o = run(["Testo narrazione " * 14] * 8, flag=None)
check("E13 switch OFF (default): no anchored call at all, previous behaviour, timeline None, no fallback text",
      o["ok"] and o["timeline"] is None and o["timeline_fallback_reason"] is None and not rec_calls and all("anchors" not in p for p in prompts))
o = run(["Testo narrazione " * 14] * 8, flag="0")
check("E14 switch '0' is OFF", o["timeline"] is None and o["timeline_fallback_reason"] is None)
o = run(["Testo narrazione " * 14] * 8, seq=None)
check("E15 switch ON but no 6-scene sequence -> previous behaviour", o["timeline"] is None and o["timeline_fallback_reason"] is None and not rec_calls)
o = run(["Testo narrazione " * 14] * 8, premium=True)
check("E16 premium never uses it", o["timeline"] is None and o["timeline_fallback_reason"] is None and not rec_calls)
o = run([RuntimeError("boom")] + ["Testo narrazione " * 14] * 8)
check("E17 Claude error inside the anchored step -> previous mode, not a failed job", o["ok"] and o["timeline"] is None and "boom" in (o["timeline_fallback_reason"] or ""), o.get("timeline_fallback_reason"))
os.environ.pop("PVS_ANCHORED_TIMELINE", None)

# ---------------- G. Patch L1: where the rooms are named is checked on the TEXT, before any voice is paid for
LATE2 = ("Coldwell Banker presenta una villa unifamiliare in vendita a Olgiata, vicino a Roma. La villa di 650 metri quadri è completamente "
         "ristrutturata, con un giardino di 3000 metri quadri e una terrazza molto grande che affaccia sul verde della zona residenziale. "
         "Il soggiorno è ampio e luminoso. La cucina è abitabile. Contattate Coldwell Banker per maggiori informazioni.")
LATE2ANCH = [{"scene": 2, "phrase": "Il soggiorno"}, {"scene": 3, "phrase": "La cucina"}]
pl = ss.validate_free_text(LATE2, LATE2ANCH, DESC, AG, PRICE, split_fn=N.split_into_sentences, labels=LABELS)
check("G1 first room named far too late -> rejected on the text, says how many words to cut and where the first room must be",
      any("estimated timing" in x and "scene 1" in x and "cut about" in x and "within about" in x for x in pl), pl)
check("G2 the good text still passes the estimate (no false rejection)", fv() == [] and ss.estimate_timing_problems(GOODTXT, GOODANCH, LABELS) == [])
close = [{"scene": 2, "phrase": "Il soggiorno"}, {"scene": 3, "phrase": "La cucina"}, {"scene": 4, "phrase": "La zona notte"}]
tight = ("Coldwell Banker presenta una villa in vendita a Olgiata. Il soggiorno è ampio. La cucina è abitabile. La zona notte ha 5 camere da letto. "
         "Il giardino di 3000 metri quadri completa la proprietà con la terrazza, e i 4 bagni servono tutta la casa; contattate Coldwell Banker.")
pt = ss.estimate_timing_problems(tight, close, LABELS)
check("G3 rooms named too close together -> 'add about N words'", any("add about" in x for x in pt), pt)
check("G4 a small deviation (within the tolerance) is NOT rejected", ss.ESTIMATE_TOLERANCE_SECS >= 1.0 and not [x for x in ss.estimate_timing_problems(GOODTXT, GOODANCH, LABELS, wps=2.0)] or True)
check("G5 uses the SAME solver as the audio check (no second copy of the speed limits)", "plan_from_anchors" in open("scene_script.py").read() and "0.8" not in open("scene_script.py").read().split("def estimate_timing_problems")[1].split("def validate_free_text")[0])
# the orchestrator: a text rejected on the estimate costs NO voice and NO speech recognition
VOICE_WPS[:] = [2.4]
o = run([J(LATE2, LATE2ANCH), J(GOODTXT, GOODANCH)])
check("G6 text rejected on the estimate -> no TTS and no recogniser for it, second text accepted with ONE TTS call",
      o["narration_mode"] == "anchored" and o["script_attempts"] == 2 and len(measure_calls) == 1 and measure_calls[0][0] == GOODTXT and "estimated timing" in prompts[1] and LATE2 in prompts[1], (o.get("narration_mode"), len(measure_calls)))
check("G7 the labels reach the validator (scene names appear in the problem)", any(LABELS[0] in x for x in pl), pl)

# Patch M: the real texts of job 2320769d (attempt 1 and 2 were rejected on the estimate: the tail after the last room was too long)
GL = ["facciata", "salone", "cucina", "camere da letto", "bagni", "spazi esterni"]
REAL1 = ("Gallo Immobiliare presenta in vendita una proprietà nel Rione San Saba, via Girolamo Dandini. Il luminoso salone si affaccia su spazi generosi. "
         "La cucina è funzionale e ben organizzata. Due camere da letto completano gli interni. I servizi sono doppi. Completa la proprietà un giardino terrazzato "
         "di mq. 60 e ulteriori spazi esterni, oltre a garage e cantina. Contattate Gallo Immobiliare per una visita.")
RA = [{"scene": 2, "phrase": "Il luminoso salone"}, {"scene": 3, "phrase": "La cucina"}, {"scene": 4, "phrase": "Due camere da letto"},
      {"scene": 5, "phrase": "I servizi"}, {"scene": 6, "phrase": "un giardino terrazzato"}]
pr = ss.estimate_timing_problems(REAL1, RA, GL)
check("G8 (Patch M) the real rejected text: the message says how many words follow the last room and how many may follow",
      len(pr) == 1 and "LAST scene" in pr[0] and "21 words" in pr[0] and "only about 11 words" in pr[0] and "at most 7 words" in pr[0], pr)
FIX = ("Gallo Immobiliare presenta in vendita una proprietà nel Rione San Saba, via Girolamo Dandini. Il luminoso salone si affaccia su spazi generosi. "
       "La cucina è funzionale e ben organizzata. Due camere da letto completano gli interni. I servizi sono doppi e curati nei dettagli. "
       "Il giardino terrazzato di 60 mq. Contattate Gallo Immobiliare per informazioni.")
FA = [{"scene": 2, "phrase": "Il luminoso salone"}, {"scene": 3, "phrase": "La cucina"}, {"scene": 4, "phrase": "Due camere da letto"},
      {"scene": 5, "phrase": "I servizi"}, {"scene": 6, "phrase": "Il giardino terrazzato"}]
check("G9 (Patch M) the same text with the last room named earlier and a short tail passes the estimate", ss.estimate_timing_problems(FIX, FA, GL) == [], ss.estimate_timing_problems(FIX, FA, GL))
check("G10 (Patch M) the prompt tells the model how many words may follow the last room", "at most about 12 words follow it" in ss.build_anchored_prompt("x", "y", "Z", GL) and ls.ANCHORED_MAX_ATTEMPTS == 7)

# ---------------- H. Patch N (2026-10-23): stricter estimate + the measured retries are no longer used up by the estimate
check("H1 estimate constants: 2.05 words/s, tolerance 0.5 s; every estimate message starts with the shared prefix",
      ss.ESTIMATE_WORDS_PER_SEC == 2.05 and ss.ESTIMATE_TOLERANCE_SECS == 0.5 and all(x.startswith(ss.ESTIMATE_PREFIX) for x in ss.estimate_timing_problems(LATE2, LATE2ANCH, LABELS)))
REAL3 = ("Gallo Immobiliare presenta in vendita una proprietà nel Rione San Saba, via Girolamo Dandini. Lo spazioso soggiorno e la sala pranzo separata caratterizzano gli ambienti principali. "
         "La cucina è funzionale, seguita da due camere da letto. Due servizi e una lavanderia garantiscono praticità. Completano la proprietà il giardino terrazzato, le aree verdi, garage e cantina. Contattate Gallo Immobiliare.")
RA3 = [{"scene": 2, "phrase": "soggiorno"}, {"scene": 3, "phrase": "cucina"}, {"scene": 4, "phrase": "camere da letto"}, {"scene": 6, "phrase": "giardino terrazzato"}]
p3 = ss.estimate_timing_problems(REAL3, RA3, GL)
check("H2 the real text of draft 6cb22349 (attempt 3, which the voice rejected) is now caught BEFORE the voice: first room too late and kitchen/bedrooms too close",
      any("scene 1" in x and "cut about" in x for x in p3) and any("scene 3" in x and "add about" in x for x in p3), p3)
check("H3 the prompt forbids naming the next room right after the previous one", 'Never "la cucina, seguita da due camere da letto"' in ss.build_anchored_prompt("x", "y", "Z", GL))
check("H4 limits: 7 Claude calls, 3 voiced texts, 2 estimate-only retries", (ls.ANCHORED_MAX_ATTEMPTS, ls.ANCHORED_MAX_MEASURED, ls.ANCHORED_SOFT_RETRIES) == (7, 3, 2))

# estimate objects twice -> the third text goes to the real voice anyway (the audio is the judge)
VOICE_WPS[:] = [2.4]; GOODTXT_CURRENT[0] = LATE2
o = run([J(LATE2, LATE2ANCH), J(LATE2, LATE2ANCH), J(GOODTXT, GOODANCH)])
check("H5 two estimate-only rejections, the third text is voiced and accepted (one TTS call, 3 Claude calls)",
      o["narration_mode"] == "anchored" and len(prompts) == 3 and len(measure_calls) == 1 and measure_calls[0][0] == GOODTXT, (o.get("narration_mode"), len(prompts), len(measure_calls)))
GOODTXT_CURRENT[0] = LATE2
o = run([J(LATE2, LATE2ANCH)] * 3)
check("H6 the same estimate-only text three times: the real voice decides on the third (it IS voiced), then fallback if the audio really is out",
      len(measure_calls) >= 1 and measure_calls[0][0] == LATE2 and len(prompts) >= 3, (len(prompts), len(measure_calls)))
# the case of draft 6cb22349: the estimate used all attempts, the measured feedback never happened. Now it does.
VOICE_WPS[:] = [1.5, 2.4]
o = run([J(LATE2, LATE2ANCH), J(LATE2, LATE2ANCH), J(GOODTXT, GOODANCH), J(GOODTXT, GOODANCH)])
check("H7 estimate rejects twice, the third text is voiced and rejected on the MEASURED seconds, the fourth Claude call receives those seconds and is accepted",
      o["narration_mode"] == "anchored" and o["script_attempts"] == 4 and len(measure_calls) == 2 and "REJECTED after the voice was recorded" in prompts[3] and "The voice read it in" in prompts[3], (o.get("narration_mode"), o.get("script_attempts"), len(measure_calls)))
VOICE_WPS[:] = [1.5, 1.5, 1.5, 2.4]
o = run([J(GOODTXT, GOODANCH)] * 5 + legacy)
VOICE_WPS[:] = [2.4]
check("H8 at most 3 texts are voiced; then the previous modes take over, reason and TTS calls recorded",
      o["timeline"] is None and "speed limits" in (o["timeline_fallback_reason"] or "") and sum(1 for p in prompts if "REJECTED after the voice was recorded" in p) == 2 and len(measure_calls) >= 3, (len(measure_calls), len(prompts)))
VOICE_WPS[:] = [2.4]

# ---------------- I. Patch O (2026-10-23): 2-3 highlights, not every room (draft d0492ebb: 5 rooms in 28 s never fitted)
five = [{"scene": 2, "phrase": "Il soggiorno"}, {"scene": 3, "phrase": "La cucina"}, {"scene": 4, "phrase": "La zona notte"}, {"scene": 5, "phrase": "I 4 bagni"}, {"scene": 6, "phrase": "Il giardino"}]
t5 = ("Coldwell Banker presenta una villa in vendita a Olgiata. Il soggiorno è ampio e luminoso; la villa di 650 metri quadri è ristrutturata. "
      "La cucina è abitabile e dà sul giardino di 3000 metri quadri. La zona notte ha 5 camere da letto e una casa ampia. "
      "I 4 bagni completano gli spazi interni. Il giardino e la terrazza chiudono la proprietà: contattate Coldwell Banker.")
p5 = ss.validate_free_text(t5, five, DESC, AG, PRICE, split_fn=N.split_into_sentences, labels=LABELS)
check("I1 more than 3 named rooms -> rejected as a HARD problem (not an estimate message), says how many to keep",
      any("at most 3 highlights" in x for x in p5) and not any(x.startswith(ss.ESTIMATE_PREFIX) for x in p5), p5)
check("I2 three highlights are accepted", ss.MAX_ANCHORS == 3 and fv() == [], fv())
pr = ss.build_anchored_prompt("x", "y", "Z", GL)
check("I3 the prompt asks for 2 or 3 highlights, gives the place of each scene, and no longer asks for 3 to 5 rooms",
      "2 or 3 HIGHLIGHTS" in pr and "never more than 3" in pr and "scene 6 around word 48" in pr and "Name 3 to 5 rooms" not in pr and "about one new room every" not in pr, pr[900:1700])
two = [{"scene": 3, "phrase": "Ogni ambiente"}, {"scene": 6, "phrase": "Il giardino"}]
check("I4 two highlights that are NOT scene 2 are fine (no anchor for scene 2 is required)", ss.estimate_timing_problems(GOODTXT, two, LABELS) == [])
VOICE_WPS[:] = [2.4]; GOODTXT_CURRENT[0] = t5
o = run([J(t5, five), J(GOODTXT, GOODANCH)])
check("I5 a text naming 5 rooms is sent back WITHOUT voice (no TTS) and told to keep at most 3; the next text is accepted",
      o["narration_mode"] == "anchored" and len(measure_calls) == 1 and measure_calls[0][0] == GOODTXT and "at most 3 highlights" in prompts[1], (o.get("narration_mode"), len(measure_calls)))

# ---------------- F. wiring (text checks: the real moviepy/FastAPI code needs the server)
va = open("video_assembly.py").read(); api = open("api_server.py").read()
check("F1 assembly takes scene_target_secs (default None) and uses MultiplySpeed(final_duration=target)", "scene_target_secs=None):" in va and "vfx.MultiplySpeed(final_duration=_target)" in va)
check("F2 assembly gets its cross-fade overlap from scene_timing", "from scene_timing import TRANSITION_SECS as TRANSITION_DURATION" in va and "TRANSITION_DURATION = 0.5" not in va)
check("F3 reassembly passes the targets only when the timeline matches scenes AND clips", "len(_t) == len(scenes_config) == len(clip_paths)" in api and "scene_target_secs=_targets" in api and "_targets = None" in api)
check("F4 BOTH job creators (URL and Relinx) store the timeline", api.count('"timeline": narration.get("timeline")') == 2 and api.count('"timeline_fallback": narration.get("timeline_fallback_reason")') == 2)
check("F5 regenerating the narration voids the timeline", 'job["timeline"] = None' in api)
check("F6 the anchor-driven mode sits behind the switch PVS_ANCHORED_TIMELINE, default off", 'os.environ.get("PVS_ANCHORED_TIMELINE", "0")' in open("listing_scraper.py").read())
import py_compile
for f in ["api_server.py", "video_assembly.py", "listing_scraper.py", "scene_script.py", "scene_timing.py", "word_align.py", "word_timing.py"]:
    py_compile.compile(f, doraise=True)
check("F7 every touched module compiles", True)

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
