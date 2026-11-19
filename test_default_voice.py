"""test_default_voice.py - PVS_DEFAULT_VOICE: the default Google voice is a knob; an unknown id never breaks the TTS (2026-11-19). No network."""
import os, sys, importlib
from unittest import mock
sys.modules["pydub"] = mock.MagicMock()
sys.path.insert(0, os.getcwd())
os.environ["TTS_PROVIDER"] = "google"
fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)
def load(value):
    if value is None: os.environ.pop("PVS_DEFAULT_VOICE", None)
    else: os.environ["PVS_DEFAULT_VOICE"] = value
    import voice_generation as vg
    return importlib.reload(vg)
LEDA, AOEDE = "it-IT-Chirp3-HD-Leda", "it-IT-Chirp3-HD-Aoede"
v = load(None)
check("DV1 no knob -> Leda, as before", v.DEFAULT_VOICE_ID == LEDA and v.TTS_LANGUAGES["it-IT"]["default_voice"] == LEDA)
v = load(AOEDE)
check("DV2 knob = Aoede -> the default of the code, of the registry and of the menu", v.DEFAULT_VOICE_ID == AOEDE and v.TTS_LANGUAGES["it-IT"]["default_voice"] == AOEDE)
check("DV3 an empty voice field resolves to the new default; an explicit voice is kept", v.resolve_voice("") == AOEDE and v.resolve_voice(None) == AOEDE and v.resolve_voice("it-IT-Chirp3-HD-Kore") == "it-IT-Chirp3-HD-Kore")
check("DV4 a stray value in the voice field still gives the default", v.resolve_voice("https://x.y/z") == AOEDE)
v = load("it-IT-Chirp3-HD-Nonexistent")
check("DV5 an unknown id in the knob falls back to Leda, never broken", v.DEFAULT_VOICE_ID == LEDA and v.resolve_voice("") == LEDA)
v = load("   ")
check("DV6 a blank knob = no knob", v.DEFAULT_VOICE_ID == LEDA)
check("DV7 the six voices are still in the registry, once", [x["id"].split("-")[-1] for x in v.TTS_LANGUAGES["it-IT"]["voices"]] == ["Leda", "Aoede", "Kore", "Charon", "Puck", "Orus"])
load(None)
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
raise SystemExit(1 if fails else 0)
