import base64, json, os, sys, tempfile, types
os.environ["TTS_PROVIDER"] = "google"; os.environ["GOOGLE_TTS_API_KEY"] = "test"
sys.modules.setdefault("pydub", types.ModuleType("pydub")); sys.modules["pydub"].AudioSegment = object
import voice_generation as vg
ok = True
def chk(n, c):
    global ok; print(("PASS" if c else "FAIL"), n); ok &= bool(c)
S = "ˈ"
rules = {"THRINAKIE": "[[trina" + S + "kie|Thrinakie]]", "Thrinakie": "[[trina" + S + "kie|Thrinakie]]", "Buildingcase": "Bilding [[" + S + "kaze|Case]]", "GROUP": "Group"}
tmp = tempfile.mkdtemp(); vg._PRON_PATH = os.path.join(tmp, "p.json"); open(vg._PRON_PATH, "w", encoding="utf-8").write(json.dumps(rules, ensure_ascii=False))
tag = lambda ph, w: '<phoneme alphabet="ipa" ph="' + ph + '">' + w + '</phoneme>'
chk("IP1 segment becomes a phoneme tag for Google", vg.expand_ipa(vg._protect_ipa("[[ab" + S + "c|Word]] x")) == tag("ab" + S + "c", "Word") + " x")
chk("IP2 other providers get the plain word", vg.expand_ipa(vg._protect_ipa("[[abc|Word]]"), ssml=False) == "Word")
chk("IP3 unsafe segments fall back to the word (full stop, quote, ampersand, empty)",
    vg.expand_ipa(vg._protect_ipa("[[a.b|W1]] [[a\"b|W2]] [[ab|W&3]]")) == "W1 W2 W&3")
t = vg.expand_ipa(vg.sanitize_for_tts(vg.apply_pronunciation_fixes("THRINAKIE GROUP presenta")))
chk("IP4 rule value -> exact phoneme, GROUP rule still applies", t == tag("trina" + S + "kie", "Thrinakie") + " Group presenta")
t = vg.expand_ipa(vg.sanitize_for_tts(vg.apply_pronunciation_fixes("Thrinakie e THRINAKIE")))
chk("IP5 two keys, no double wrapping (each name wrapped once)", t.count("<phoneme") == 2 and "[[" not in t and "" not in t)
t = vg.expand_ipa(vg.sanitize_for_tts(vg.apply_pronunciation_fixes("Buildingcase Bologna & Roma")))
chk("IP6 a name with a plain part and an IPA part; '&' still spoken 'e'", t == "Bilding " + tag(S + "kaze", "Case") + " Bologna e Roma")
sent = {}
class R:
    status_code = 200
    def json(self): return {"audioContent": base64.b64encode(b"x").decode()}
def fake_post(url, json=None, headers=None, **k):
    sent["ssml"] = json["input"]["ssml"]; return R()
vg.requests.post = fake_post
vg.AudioSegment = object
os.chdir(tmp)
res = vg.generate_speech("Titolo\nTHRINAKIE GROUP presenta. Seconda frase.", os.path.join(tmp, "o.mp3"), voice_id="it-IT-Chirp3-HD-Aoede")
s = sent.get("ssml", "")
chk("IP7 end to end: the SSML sent to Google carries the phoneme tag, intact, no pause inside it",
    res and tag("trina" + S + "kie", "Thrinakie") + " Group presenta. <break" in s and s.startswith("<speak>Titolo"))
chk("IP8 ElevenLabs path: no phoneme markup would be sent", "<phoneme" not in vg.expand_ipa(vg.sanitize_for_tts(vg.apply_pronunciation_fixes("THRINAKIE")), ssml=False))
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
