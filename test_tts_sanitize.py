"""2026-10-12: text sent to TTS must be SSML-safe ('&' in an agency name broke every job of that agency)."""
import os, sys, types, tempfile, base64, json
import xml.etree.ElementTree as ET
sys.path.insert(0, os.getcwd())
try:
    import pydub  # noqa
except Exception:
    pd = types.ModuleType("pydub")
    class AudioSegment:
        @staticmethod
        def from_mp3(p): raise RuntimeError("stub")
        @staticmethod
        def silent(duration=0): return None
    pd.AudioSegment = AudioSegment; sys.modules["pydub"] = pd
os.chdir(tempfile.mkdtemp()); sys.path.insert(0, os.environ.get("PVS_SRC", ""))
import voice_generation as vg

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

sent = {}
class R:
    status_code = 200; content = b"abc"; text = ""
    def json(self): return {"audioContent": base64.b64encode(b"abc").decode()}
def fake_post(url, json=None, headers=None, **kw):
    sent["json"] = json; sent["url"] = url
    return R()
vg.requests.post = fake_post

TEXT = "Engel & Völkers Roma presenta un trilocale in vendita. Contattate Engel & Völkers per informazioni."

# Google (SSML)
vg.TTS_PROVIDER = "google"; os.environ["GOOGLE_TTS_API_KEY"] = "k"
ok = vg.generate_speech(TEXT, os.path.join(os.getcwd(), "o.mp3"), voice_id="it-IT-Chirp3-HD-Leda")
ssml = sent["json"]["input"]["ssml"]
try:
    ET.fromstring(ssml); valid = True
except Exception as e:
    valid = False
check("G1 google: request succeeds", ok is True)
check("G2 google: SSML is well-formed XML with '&' in the agency name", valid, ssml[:120])
check("G3 google: '&' spoken as 'e', accents kept", "Engel e Völkers Roma" in ssml and "&" not in ssml, ssml[:120])
check("G4 google: break tags still present", "<break" in ssml)
sent.clear()
vg.generate_speech("Prezzo <ottimo> & vista.\nSecondo paragrafo.", os.path.join(os.getcwd(), "o2.mp3"), voice_id="it-IT-Chirp3-HD-Leda")
try:
    ET.fromstring(sent["json"]["input"]["ssml"]); v2 = True
except Exception:
    v2 = False
check("G5 google: '<' '>' in the text do not break the SSML", v2, sent["json"]["input"]["ssml"][:150])

# ElevenLabs (text with break tags)
vg.TTS_PROVIDER = "elevenlabs"; os.environ["ELEVENLABS_API_KEY"] = "k"
sent.clear()
vg.generate_speech(TEXT, os.path.join(os.getcwd(), "o3.mp3"), voice_id="abc123")
t = sent["json"]["text"]
check("E1 elevenlabs: no '&', 'e' spoken, break tags kept", "&" not in t and "Engel e Völkers" in t and "<break" in t, t[:120])

# plain text is untouched
check("P1 plain text unchanged", vg.sanitize_for_tts("Appartamento di 80 mq, è luminoso. L'agenzia vi aspetta.") == "Appartamento di 80 mq, è luminoso. L'agenzia vi aspetta.")
check("P2 no double spaces, newlines kept", vg.sanitize_for_tts("A & B\nC  D") == "A e B\nC D", repr(vg.sanitize_for_tts("A & B\nC  D")))
check("P3 '&' glued to words", vg.sanitize_for_tts("Re/Max&Co") == "Re/Max e Co")

print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
