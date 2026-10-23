"""Tests for scene_timing.plan_timeline (sentence-driven timeline, cross-fade aware) and
narration.assemble_narration(gaps_ms=...). Pure, no network. Run: python3 test_scene_timing.py"""
import sys, types, tempfile, os
import scene_timing as T
import narration as N

P = F = 0
def check(name, cond, info=""):
    global P, F
    if cond: P += 1; print(f"PASS {name}")
    else: F += 1; print(f"FAIL {name} {info}")

def mk(speech_secs, groups=None):
    ms = [int(s * 1000) for s in speech_secs]
    return T.plan_timeline(ms, groups or [1] * len(ms))

# --- constants: one definition each

src = open("video_assembly.py").read()
check("C1 video_assembly takes its cross-fade overlap FROM scene_timing (one value, 0.5)", "from scene_timing import TRANSITION_SECS as TRANSITION_DURATION" in src and "TRANSITION_DURATION = 0.5" not in src and T.TRANSITION_SECS == 0.5)
check("C2 base pause is the narration one", T.PAUSE_MS == N.SENTENCE_PAUSE_MS)

# --- normal case: six sentences of 4.5 s, one per scene
r = mk([4.5] * 6)
c = r["clips"]
check("N1 six clips, six sentences", len(c) == 6 and len(r["sentences"]) == 6)
check("N2 all in range, plan ok", r["ok"] and all(x["in_range"] for x in c), r["problems"])
check("N3 middle clip = speech + pause + full cross-fade (4.5+0.38+0.5)", abs(c[2]["duration"] - 5.38) < 0.01, c[2])
check("N4 first clip has only half a cross-fade (4.5+0.38+0.25)", abs(c[0]["duration"] - 5.13) < 0.01, c[0])
check("N5 last clip = speech + tail + half cross-fade (4.5+0.2+0.25)", abs(c[5]["duration"] - 4.95) < 0.01, c[5])
# the cut of scene j (middle of the overlap) is exactly where sentence j starts
ok = True
for j, s in enumerate(r["sentences"]):
    cl = c[s["clips"][0]]
    left = 0.25 if cl["index"] > 0 else 0.0
    ok = ok and abs((cl["start"] + left) - s["voice_start"]) < 0.002
check("N6 every sentence starts exactly on the cut of its scene (this is the sync)", ok)
# clip starts follow the cross-fade overlap: start_{i+1} = start_i + D_i - 0.5
ok = all(abs(c[i + 1]["start"] - (c[i]["start"] + c[i]["duration"] - 0.5)) < 0.002 for i in range(5))
check("N7 clip starts chain with the 0.5 s overlap (matches video_assembly)", ok)
check("N8 video length = sum of clips - 5 overlaps", abs(r["video_secs"] - (sum(x["duration"] for x in c) - 2.5)) < 0.002)
# voice timeline rebuilt from gaps equals the planned starts
t = 0.0; starts = []
for j, ms in enumerate([4500] * 6):
    t += r["gaps_ms"][j] / 1000.0
    starts.append(round(t, 2)); t += ms / 1000.0
check("N9 gaps_ms rebuild the planned voice starts", all(abs(a - b["voice_start"]) < 0.01 for a, b in zip(starts, r["sentences"])), (starts, [x["voice_start"] for x in r["sentences"]]))
check("N10 first gap is 0", r["gaps_ms"][0] == 0 and len(r["gaps_ms"]) == 6)

# --- the OLD error: with the 5 s grid the 6th sentence started at 25 s, really scene 6 is at 22.5 s
r2 = mk([5.0] * 6)
check("N11 real cut of scene 6 is NOT on the old 25 s grid", abs(r2["sentences"][5]["voice_start"] - 25.0) > 1.0, r2["sentences"][5])

# --- long sentence: pause shrinks (voice may run into the cross-fade)
r = mk([4.5, 5.5, 4.5, 4.5, 4.5, 4.5])
s1 = r["sentences"][1]
check("L1 5.5 s sentence: pause shrunk below 0.38 s to stay within 0.8x", s1["pause_after_secs"] < 0.38 and r["clips"][1]["in_range"], s1)
check("L2 ... but not below the minimum pause", s1["pause_after_secs"] >= T.MIN_PAUSE_MS / 1000.0 - 1e-6, s1)
check("L3 speed of that clip is >= 0.8", r["clips"][1]["speed"] >= 0.8 - 1e-3, r["clips"][1])

# --- too long: reported, plan stays exact (clip gets the length it needs)
r = mk([6.3, 4.5, 4.5, 4.5, 4.5, 4.5])
check("X1 6.3 s sentence cannot fit in one clip: reported", not r["ok"] and r["problems"][0]["kind"] == "too_slow" and r["problems"][0]["sentence"] == 0, r["problems"])
check("X2 the voice start of the NEXT sentence is still exact", abs(r["sentences"][1]["voice_start"] - (6.3 + 0.1)) < 0.02 or r["sentences"][1]["voice_start"] > 6.3, r["sentences"][1])
check("X3 the flagged clip is still given its true length (no silent drift)", r["clips"][0]["duration"] > 5.0 / 0.8 - 0.01, r["clips"][0])

# --- short sentence: extra silence so the clip is not sped up beyond 1.25x
r = mk([2.2, 4.5, 4.5, 4.5, 4.5, 4.5])
check("S1 2.2 s sentence: clip not sped up beyond 1.25x", r["clips"][0]["speed"] <= 1.25 + 1e-3 and r["clips"][0]["in_range"], r["clips"][0])
check("S2 ... by adding silence after the sentence", r["sentences"][0]["pause_after_secs"] > 0.38, r["sentences"][0])
check("S3 plan ok", r["ok"], r["problems"])

# --- one sentence over two scenes
r = mk([9.0, 4.5, 4.5, 4.5, 4.5], groups=[2, 1, 1, 1, 1])
check("P1 six clips from five sentences", len(r["clips"]) == 6 and r["sentences"][0]["clips"] == [0, 1])
check("P2 both clips of the pair in range and equal length", r["ok"] and abs(r["clips"][0]["duration"] - r["clips"][1]["duration"] + 0.25) < 0.3, r["clips"][:2])
check("P3 second clip of the pair starts mid-sentence, chained by the overlap", abs(r["clips"][1]["start"] - (r["clips"][0]["start"] + r["clips"][0]["duration"] - 0.5)) < 0.002)
check("P4 next sentence starts on the cut of clip 2", abs(r["clips"][2]["start"] + 0.25 - r["sentences"][1]["voice_start"]) < 0.002)

# --- real source lengths
r = T.plan_timeline([4500] * 6, [1] * 6, src_secs=[5.208333] * 6)
check("R1 real 5.208 s sources: speeds computed from the real length", abs(r["clips"][2]["speed"] - 5.208333 / r["clips"][2]["duration"]) < 0.001)

# --- validation
for bad, name in (((([], [])), "V1 empty"), (((([4000], [1, 1]))), "V2 length mismatch"), ((([4000], [0])), "V3 group 0")):
    try:
        T.plan_timeline(*bad); check(name + " rejected", False)
    except ValueError:
        check(name + " rejected", True)
try:
    T.plan_timeline([4000, 4000], [1, 1], src_secs=[5.0]); check("V4 wrong src_secs length rejected", False)
except ValueError:
    check("V4 wrong src_secs length rejected", True)

# --- narration.assemble_narration(gaps_ms=...)
try:
    from pydub import AudioSegment
    AUDIO = "real pydub"
except ModuleNotFoundError:
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
clips = [AudioSegment.silent(duration=d) for d in (4000, 3000, 5000)]
out = os.path.join(tempfile.mkdtemp(), "n.mp3")
res = N.assemble_narration(["a.", "b.", "c."], clips, out, gaps_ms=[0, 900, 150])
tm = res["sentence_timings"]
check("G1 gaps_ms used exactly: starts 0 / 4900 / 8050", [x["start_ms"] for x in tm] == [0, 4900, 8050], tm)
check("G2 total = sentences + gaps", abs(res["duration_secs"] - (12000 + 1050) / 1000.0) < 0.01, res["duration_secs"])
check("G3 no sync object in this mode (scene_timing owns the timeline)", res["sync"] is None)
try:
    N.assemble_narration(["a."], clips[:1], out, gaps_ms=[0, 1]); check("G4 wrong gaps_ms length rejected", False)
except ValueError:
    check("G4 wrong gaps_ms length rejected", True)
res = N.assemble_narration(["a.", "b.", "c."], clips, out)
check("G5 default behaviour unchanged (plain 380 ms pause)", [x["start_ms"] for x in res["sentence_timings"]] == [0, 4380, 7760])

print(f"RESULT: {'ALL PASS' if F == 0 else 'FAILURES'} ({P}/{P + F})")
sys.exit(1 if F else 0)
