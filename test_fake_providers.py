import os, sys, json, types, subprocess, threading, http.server, tempfile, shutil, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
st = tempfile.mkdtemp(prefix="pvsfake_")
os.environ["PVS_FAKE_DIR"] = st
res = []
def check(name, ok, info=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + name + (" -- " + str(info) if info and not ok else ""))

# stand-ins for packages not installable in the sandbox
fc = types.ModuleType("fal_client"); fc.subscribe = lambda *a, **k: "REAL"; fc.upload_file = lambda *a, **k: "REAL"
an = types.ModuleType("anthropic"); an.Anthropic = lambda *a, **k: "REAL"
sys.modules["fal_client"] = fc; sys.modules["anthropic"] = an
import smtplib; real_smtp = smtplib.SMTP_SSL
import requests
from requests.adapters import HTTPAdapter
real_send = HTTPAdapter.send

# T1 default OFF
os.environ.pop("PVS_FAKE_PROVIDERS", None)
import importlib, fake_providers as fp
importlib.reload(fp)
check("T1 default OFF: ENABLED False", fp.ENABLED is False)
check("T1 install_if_enabled does nothing", fp.install_if_enabled() is False and fc.subscribe() == "REAL" and HTTPAdapter.send is real_send and smtplib.SMTP_SSL is real_smtp)

# T2 ON
os.environ["PVS_FAKE_PROVIDERS"] = "1"; os.environ["ANTHROPIC_API_KEY"] = "sk-REAL"
importlib.reload(fp)
check("T2 ON: install patches", fp.install_if_enabled() is True and fc.subscribe is fp.fake_subscribe and HTTPAdapter.send is not real_send)
check("T2 keys overwritten", os.environ["ANTHROPIC_API_KEY"] == "fake-key-not-real")

def probe(path_or_bytes):
    if isinstance(path_or_bytes, bytes):
        p = os.path.join(st, "probe.bin"); open(p, "wb").write(path_or_bytes)
    else: p = path_or_bytes
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type", "-of", "json", p], capture_output=True, text=True)
    return json.loads(o.stdout or "{}")

# T3 fal upload + veo -> real mp4 that shows the photo
from PIL import Image
img = os.path.join(st, "room.jpg"); Image.new("RGB", (1600, 1200), (120, 160, 200)).save(img)
url = fc.upload_file(img)
r = fc.subscribe("fal-ai/veo3.1/image-to-video", arguments={"image_url": url, "duration": "8s", "aspect_ratio": "16:9"})
vurl = r["video"]["url"]; resp = requests.get(vurl, stream=True, timeout=5)
data = b"".join(resp.iter_content(8192)); info = probe(data)
dur = float(info["format"]["duration"]); wh = [(s["width"], s["height"]) for s in info["streams"] if s["codec_type"] == "video"]
check("T3 veo fake -> 200 playable mp4 8s 1920x1080", resp.status_code == 200 and abs(dur - 8) < 0.5 and wh == [(1920, 1080)], (resp.status_code, dur, wh))
r2 = fc.subscribe("fal-ai/aura-sr", arguments={"image_url": url}); b = requests.get(r2["image"]["url"], stream=True).content
check("T3b upscale fake returns the uploaded photo bytes", b == open(img, "rb").read())
check("T3c florence deterministic", fc.subscribe("fal-ai/florence-2-large/more-detailed-caption", arguments={"image_url": url})["results"] == fc.subscribe("fal-ai/florence-2-large/more-detailed-caption", arguments={"image_url": url})["results"])

# T4 faults file: sequence consumed then ok; changes reset
def setfaults(d):
    open(os.path.join(st, "faults.json"), "w").write(json.dumps(d)); os.utime(os.path.join(st, "faults.json"), (time.time() + setfaults.n, time.time() + setfaults.n)); setfaults.n += 1
setfaults.n = 1
setfaults({"veo": ["no_output", "timeout"]})
a = fc.subscribe("fal-ai/veo3.1/image-to-video", arguments={"image_url": url})
try: fc.subscribe("fal-ai/veo3.1/image-to-video", arguments={"image_url": url}); t = False
except TimeoutError: t = True
c = fc.subscribe("fal-ai/veo3.1/image-to-video", arguments={"image_url": url})
check("T4 fault sequence no_output -> timeout -> ok", a == {} and t and "video" in c)
setfaults({"veo": ["failed"]})
try: fc.subscribe("fal-ai/veo3.1/image-to-video", arguments={"image_url": url}); f = False
except RuntimeError: f = True
check("T4b editing faults.json resets counters", f)
setfaults({"florence": ["people"]})
check("T4c florence people fault", "man" in fc.subscribe("fal-ai/florence-2-large/more-detailed-caption", arguments={"image_url": url})["results"])
setfaults({})

# T5 Luma direct: ok path (poll twice), 400, failed-after-accept
H = {"Authorization": "Bearer x"}
LU = "https://agents.lumalabs.ai/v1/generations"
body = {"model": "ray-3.2", "aspect_ratio": "16:9", "video": {"duration": "5s", "start_frame": {"url": url}}}
g = requests.post(LU, headers=H, json=body, timeout=5); gid = g.json()["id"]
p1 = requests.get(f"{LU}/{gid}").json(); p2 = requests.get(f"{LU}/{gid}").json()
check("T5 luma ok: 201, processing then completed with url", g.status_code == 201 and p1["state"] == "processing" and p2["state"] == "completed" and p2["output"][0]["url"].startswith("https://fake.pvs.invalid/video/"), (g.status_code, p1, p2))
setfaults({"luma_direct": ["http_400", "failed"]})
g = requests.post(LU, headers=H, json=body); check("T5b luma fault http_400", g.status_code == 400)
g = requests.post(LU, headers=H, json=body); gid = g.json()["id"]; requests.get(f"{LU}/{gid}"); st2 = requests.get(f"{LU}/{gid}").json()["state"]
check("T5c luma accepted then failed", g.status_code == 201 and st2 == "failed")
setfaults({})

# T6 ElevenLabs: duration ~ chars/15 ; quota ; 500
text = "Questa e' una frase di prova per la voce. " * 10
e = requests.post("https://api.elevenlabs.io/v1/text-to-speech/abc", json={"text": text}, headers={"xi-api-key": "k"})
d = float(probe(e.content)["format"]["duration"])
check("T6 elevenlabs fake mp3 duration ~ chars/15", e.status_code == 200 and abs(d - len(text) / 15) < 0.4, (e.status_code, d, len(text) / 15))
setfaults({"elevenlabs": ["quota", "http_500"]})
q = requests.post("https://api.elevenlabs.io/v1/text-to-speech/abc", json={"text": "x"}); s5 = requests.post("https://api.elevenlabs.io/v1/text-to-speech/abc", json={"text": "x"})
check("T6b elevenlabs quota 401 / http_500", q.status_code == 401 and "quota_exceeded" in q.text and s5.status_code == 500)
setfaults({})
sub = requests.get("https://api.elevenlabs.io/v1/user/subscription").json()
check("T6c elevenlabs credit endpoint", sub["character_limit"] > sub["character_count"])

# T7 anthropic dispatch
cl = an.Anthropic(api_key="x")
cat = cl.messages.create(model="m", max_tokens=20, messages=[{"role": "user", "content": [{"type": "text", "text": "Answer with ONLY the category word, nothing else."}, {"type": "image", "source": {}}]}])
rk = cl.messages.create(model="m", max_tokens=200, messages=[{"role": "user", "content": [{"type": "text", "text": "rank"}, {"type": "text", "text": "Photo 1:"}, {"type": "text", "text": "Photo 2:"}, {"type": "text", "text": "Photo 3:"}]}])
cp = cl.messages.create(model="m", max_tokens=1024, messages=[{"role": "user", "content": "Write ... for each of these scenes/categories: exterior, living, kitchen\n\nStay"}])
nr = cl.messages.create(model="m", max_tokens=2048, messages=[{"role": "user", "content": "Write the voiceover"}])
sh = cl.messages.create(model="m", max_tokens=2048, messages=[{"role": "user", "content": "Rewrite it at no more than 40 words. This is"}])
secs = len(nr.content[0].text) / 15
check("T7 claude fake: category/ranking/captions", cat.content[0].text == "living" and rk.content[0].text == "[1, 2, 3]" and set(json.loads(cp.content[0].text)) == {"exterior", "living", "kitchen"})
check("T7b narration lands in 22-32 s fake speech band", 22 <= secs <= 32, secs)
check("T7c shorten respects word ceiling + usage tracked", len(sh.content[0].text.split()) <= 40 and nr.usage.input_tokens > 0 and nr.usage.output_tokens > 0 and nr.stop_reason == "end_turn")
setfaults({"anthropic": ["http_500"]})
try: cl.messages.create(model="m", max_tokens=5, messages=[{"role": "user", "content": "x"}]); an_f = False
except RuntimeError: an_f = True
check("T7d claude fault raises", an_f); setfaults({})

# T8 outbound safety: webhook + ntfy captured, never sent; external GET blocked; localhost passes through
w = requests.post("https://realestate.centroscs.it/crm/webhook/?t=1", data='{"status":"completed"}', headers={"Authorization": "Bearer SECRET"})
n = requests.post("https://ntfy.sh/mytopic", data="push")
gx = requests.get("https://example.com/photo.jpg")
class Hd(http.server.BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"LOCAL-OK")
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), Hd); threading.Thread(target=srv.serve_forever, daemon=True).start()
lg = requests.get(f"http://127.0.0.1:{srv.server_address[1]}/x"); srv.shutdown()
ob = [json.loads(l) for l in open(os.path.join(st, "outbox.jsonl"))]
blocked = [o for o in ob if o["kind"] == "http_blocked"]
check("T8 webhook/ntfy answered locally (200) and captured", w.status_code == 200 and n.status_code == 200 and len(blocked) >= 3)
check("T8b external GET blocked (404), secrets not stored", gx.status_code == 404 and "SECRET" not in open(os.path.join(st, "outbox.jsonl")).read())
check("T8c localhost passes through to real network", lg.text == "LOCAL-OK")

# T9 smtp captured
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login("a", "b")
    from email.message import EmailMessage
    m = EmailMessage(); m["To"] = "x@y.z"; m["Subject"] = "hi"; s.send_message(m)
check("T9 email captured in outbox", any(json.loads(l)["kind"] == "email" for l in open(os.path.join(st, "outbox.jsonl"))))
print("RESULT:", "ALL PASS" if all(res) else "FAILURES", f"({sum(res)}/{len(res)})")
shutil.rmtree(st, ignore_errors=True)
sys.exit(0 if all(res) else 1)
