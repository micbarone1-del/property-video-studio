"""Tests for plan_sentence_sync / evaluate_fixed_durations / generate_narration_audio(scene_secs=...). Run: python3 test_narration_sync.py"""
import sys, types, tempfile, os
import narration as N

P = F = 0
def check(name, cond, info=""):
    global P, F
    if cond: P += 1; print(f"PASS {name}")
    else: F += 1; print(f"FAIL {name} {info}")

S = [5] * 12

# 1. sentence that would start 1.0 s before a cut is delayed to the cut
r = N.plan_sentence_sync([4000, 4000, 4000], S, 380)
rows = r["rows"]
check("1 first sentence starts at 0", rows[0]["start_secs"] == 0.0)
# s0 0-4.0, pause .38 -> s1 would start 4.38 (cut at 5 is 0.62 later) -> delayed to 5.0
check("2 second sentence snapped to cut 5.0", rows[1]["start_secs"] == 5.0 and rows[1]["extra_pause_secs"] == 0.62, rows[1])
check("3 second sentence is scene 1 offset 0", rows[1]["scene"] == 1 and rows[1]["offset_in_scene_secs"] == 0.0)

# 2. never moves earlier / never delays beyond window
r = N.plan_sentence_sync([1000, 1000], S, 380)   # s1 would start 1.38, cut is 3.62 away > 2.0
check("4 far from cut: no extra pause", r["rows"][1]["extra_pause_secs"] == 0 and r["rows"][1]["start_secs"] == 1.38, r["rows"][1])
r = N.plan_sentence_sync([5200, 1000], S, 380)   # s1 would start 5.58, just after cut 5: stays
check("5 just after a cut: not moved earlier", r["rows"][1]["start_secs"] == 5.58 and r["rows"][1]["extra_pause_secs"] == 0, r["rows"][1])

# 3. pauses accumulate: later cuts still reached
r = N.plan_sentence_sync([4000] * 12, S, 380)
check("6 every sentence starts on a cut", all(abs(x["offset_in_scene_secs"]) < 0.01 for x in r["rows"]), [x["offset_in_scene_secs"] for x in r["rows"]])
check("7 scene k for sentence k", [x["scene"] for x in r["rows"]] == list(range(12)))
check("8 12 sentences of 4 s fit exactly: no overflow", r["overflow_secs"] == 0 and not r["too_long"])

# 4. overflow handling
r = N.plan_sentence_sync([5000] * 12, S, 380)   # each 5 s + .38 pause -> drifts
check("9 drift measured as overflow", r["overflow_secs"] > 2.0 and r["too_long"], r["overflow_secs"])
r = N.plan_sentence_sync([4600] * 12, S, 380)
check("10 sentences of 4.6 s: snapped to every cut, no overflow", r["overflow_secs"] == 0 and all(abs(x["offset_in_scene_secs"]) < 0.01 for x in r["rows"]), r["overflow_secs"])
r = N.plan_sentence_sync([4900] * 12, S, 380)   # 4.9 + .38 pause lands after the cut: cannot be moved earlier, drift accumulates
check("10b sentences of 4.9 s cannot be pulled earlier: drift reported, not hidden", r["overflow_secs"] > 2.0 and r["too_long"], r["overflow_secs"])

# 5. warning for a sentence that opens a scene and spills long into the next
r = N.plan_sentence_sync([9000, 3000], S, 380)
check("11 spill warning", len(r["warnings"]) == 1 and "frase 1" in r["warnings"][0], r["warnings"])

# 6. evaluate_fixed_durations
sync = N.plan_sentence_sync([4000] * 12, S, 380)
ev = N.evaluate_fixed_durations(60.0, S, sync)
check("12 fixed: durations unchanged, never extended", ev["new_scene_durations"] == S and not ev["needs_extension"] and ev["fixed_durations"])
check("13 fixed: ok message", "sincronizzata" in ev["message"] and not ev["too_long"] and not ev["too_short"], ev["message"])
sync = N.plan_sentence_sync([5000] * 12, S, 380)
ev = N.evaluate_fixed_durations(sync["speech_end_secs"], S, sync)
check("14 fixed: too long -> shorten message", ev["too_long"] and "Accorcia" in ev["message"], ev["message"])
sync = N.plan_sentence_sync([2000] * 4, S, 380)
ev = N.evaluate_fixed_durations(sync["speech_end_secs"], S, sync)
check("15 fixed: very short -> silence warning", ev["too_short"] and not ev["too_long"], ev["message"])

# 7. real-world case from the villa test: 61.6 s of speech over 12 x 5 s scenes
ev = N.evaluate_fixed_durations(61.6, S, {"rows": [], "overflow_secs": 1.6, "too_long": False, "warnings": []})
check("16 61.6 s over 60 s is accepted (1.6 s absorbed by buffer)", not ev["too_long"] and not ev["needs_extension"])

# 8. tier map: Luma fixed at 5, nothing else fixed
check("17 only luma is fixed, at 5 s", N.FIXED_SCENE_SECS_BY_TIER == {"luma": 5})

# 9. audio assembly with fake TTS: gaps equal pause + extra, timings consistent
try:
    from pydub import AudioSegment
    AUDIO = "real pydub"
except ModuleNotFoundError:
    # minimal stand-in so the gap/offset logic can be exercised where pydub is not installed;
    # on the server (pydub installed) the real library is used and the label below says so
    AUDIO = "STUB pydub (not the real library)"
    class AudioSegment:
        def __init__(self, ms): self.ms = ms
        def __len__(self): return self.ms
        def __add__(self, o): return AudioSegment(self.ms + o.ms)
        @staticmethod
        def silent(duration): return AudioSegment(duration)
        @staticmethod
        def from_file(p): return AudioSegment(int(open(p).read()))
        def export(self, path, format=None): open(path, "w").write(str(self.ms)); return self
    pydub_mod = types.ModuleType("pydub"); pydub_mod.AudioSegment = AudioSegment; sys.modules["pydub"] = pydub_mod
print("audio tests use:", AUDIO)
fake = types.ModuleType("voice_generation")
LENS = {"A": 4000, "B": 4000, "C": 4000}
def gen(text, path, voice_id=None):
    AudioSegment.silent(duration=LENS[text[0]]).export(path, format="wav"); return True
fake.generate_speech = gen
sys.modules["voice_generation"] = fake
orig_split = N.split_into_sentences
N.split_into_sentences = lambda t: ["A.", "B.", "C."]
d = tempfile.mkdtemp()
out = os.path.join(d, "n.wav")
res = N.generate_narration_audio("x", out, None, 380, S)
N.split_into_sentences = orig_split
check("18 audio ok with sync", res["ok"] and res["sync"] is not None, res)
st = [t["start_ms"] for t in res["sentence_timings"]]
check("19 sentence starts on cuts 0/5000/10000 ms", st == [0, 5000, 10000], st)
check("20 total = 10 s + 4 s", abs(res["duration_secs"] - 14.0) < 0.05, res["duration_secs"])
N.split_into_sentences = lambda t: ["A.", "B.", "C."]
res2 = N.generate_narration_audio("x", os.path.join(d, "m.wav"), None, 380)
N.split_into_sentences = orig_split
st2 = [t["start_ms"] for t in res2["sentence_timings"]]
check("21 without scene_secs: plain pauses (4000/8380...)", st2 == [0, 4380, 8760] and res2["sync"] is None, st2)

print(f"RESULT: {'ALL PASS' if F == 0 else 'FAILURES'} ({P}/{P+F})")
sys.exit(1 if F else 0)
