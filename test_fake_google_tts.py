"""test_fake_google_tts.py - the fake providers answer Google TTS (default voice since 2026-11-19). No network, zero cost."""
import os, sys, json, base64, tempfile, subprocess, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, REPO)
st = tempfile.mkdtemp(prefix="gtts_"); os.environ["PVS_FAKE_DIR"] = st
import requests
import fake_providers as fp
res = []
def check(n, ok, info=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + n + ("" if ok else f" -- {info}"))
URL = "https://texttospeech.googleapis.com/v1/text:synthesize?key=x"
def call(text="Ciao a tutti. Questa e' una prova."):
    return fp._route(requests.Request("POST", URL, json={"input": {"ssml": "<speak>" + text + "</speak>"}, "audioConfig": {"audioEncoding": "MP3"}}).prepare())
r = call()
check("G1 routed (not None) and HTTP 200", r is not None and r.status_code == 200, getattr(r, "status_code", None))
audio = base64.b64decode(r.json()["audioContent"])
check("G2 audioContent is a non-empty mp3", len(audio) > 500 and audio[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), audio[:4])
p = os.path.join(st, "t.mp3"); open(p, "wb").write(audio)
d = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p], capture_output=True, text=True).stdout)["format"]["duration"])
check("G3 duration follows the text length (~chars/15 s)", abs(d - len("Ciao a tutti. Questa e' una prova.") / 15.0) < 0.6, d)
ob = [json.loads(l) for l in open(os.path.join(st, "outbox.jsonl"))]
check("G4 outbox records one google_tts call", [o["kind"] for o in ob].count("google_tts") == 1, ob)
open(os.path.join(st, "faults.json"), "w").write(json.dumps({"google_tts": ["http_500", "ok"]})); t = time.time() + 5; os.utime(os.path.join(st, "faults.json"), (t, t))
r1, r2 = call(), call()
check("G5 fault http_500 then ok", r1.status_code == 500 and r2.status_code == 200, (r1.status_code, r2.status_code))
check("G6 other google paths do not crash", fp._route(requests.Request("GET", "https://texttospeech.googleapis.com/v1/voices").prepare()).status_code == 200)
check("G7 elevenlabs still routed", fp._route(requests.Request("GET", "https://api.elevenlabs.io/v1/user").prepare()).status_code == 200)
print(f"{sum(res)} PASS / {len(res) - sum(res)} FAIL"); sys.exit(0 if all(res) else 1)
