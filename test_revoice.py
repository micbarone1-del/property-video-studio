"""2026-11-17: revoice_blocks (anchored narration recorded again from stored text). Fake TTS (silence of set lengths), real planner/assembly.
Run: python3 test_revoice.py"""
import os, sys, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls
import scene_timing as st

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

TEXT = ("Questo trilocale a Marino ha un ampio soggiorno. La cucina e' abitabile. "
        "Le camere sono tranquille. I bagni sono recenti. Fuori c'e' un giardino. Il posto e' comodo. Contatta GIAL Immobiliare.")
calls = []
class Seg:
    def __init__(self, ms): self.ms = ms
    def __len__(self): return self.ms
def fake_syn(text, voice_id=None):
    calls.append(text)
    segs = [Seg(3800), Seg(3800)]
    return {"ok": True, "clips": segs, "sentence_secs": [3.8, 3.8]}
ls._synthesize_block = fake_syn
_p = {}
def fake_block_segment(clips, rate, offset=None):
    return Seg(int(sum(len(c) for c in clips) / rate) + 300)
def fake_assemble(segs, rates, starts):
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False); f.write(b"x"); f.close()
    return {"ok": True, "audio_path": f.name, "duration_secs": starts[-1] + len(segs[-1]) / 1000.0, "starts_secs": list(starts)}
ls._block_segment = fake_block_segment
ls._assemble_block_audio = fake_assemble
r = ls.revoice_blocks(TEXT, None, 6)
check("R1 ok with 3 blocks recorded", r["ok"] and len(calls) == 3, r.get("reason"))
if r["ok"]:
    tl = r["timeline"]
    check("R2 timeline anchored/blocks with 6 targets", tl["mode"] == "anchored" and tl["method"] == "blocks" and len(tl["targets"]) == 6, tl.get("targets"))
    check("R3 revoiced flag and room words not verified", tl.get("revoiced") and tl["word_check"]["checked"] is False)
    check("R4 audio file exists and speech_secs > 20", os.path.exists(r["audio_path"]) and r["speech_secs"] > 20, r["speech_secs"])
    check("R5 last block text carries the closing sentence (3 sentences)", "GIAL" in calls[2] and calls[2].count(".") == 3, calls[2])
bad = ls.revoice_blocks("Una frase sola.", None, 6)
check("R6 wrong shape refused without TTS", (not bad["ok"]) and bad["tts_calls"] == 0, bad)
bad2 = ls.revoice_blocks(TEXT, None, 5)
check("R7 scene count not multiple of 3 refused", not bad2["ok"], bad2)
ls._synthesize_block = lambda t, v=None: {"ok": False, "error": "x"}
check("R8 TTS failure reported, nothing raised", not ls.revoice_blocks(TEXT, None, 6)["ok"])
print("\nALL PASS" if not fails else f"\n{len(fails)} FAIL of {total}: {fails}")
