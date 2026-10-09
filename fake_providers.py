"""
fake_providers.py -- single switch that replaces every paid/external provider
with a local fake (backlog 58a, 2026-10-09).

ON ONLY when the environment variable PVS_FAKE_PROVIDERS=1 is set at process
start. Default is OFF and then importing this module changes nothing.

Intended use: a SECOND instance (own port, own jobs folder via PVS_JOBS_DIR),
never the production instance. See start_fake.sh.

What it replaces (one place, transport level, so the real pipeline code runs):
  - fal_client.subscribe / upload_file   (video, vision/Florence, upscale, watermark removal)
  - requests to agents.lumalabs.ai       (Luma direct: create + poll)
  - requests to api.elevenlabs.io        (TTS + credit endpoints)
  - anthropic.Anthropic                  (narration, captions, ranking, classification)
  - smtplib.SMTP_SSL                     (email)
  - any other outbound HTTP host         (captured to the outbox, never sent)

Safety rules:
  - API keys in the environment are overwritten with dummy values.
  - Outbound HTTP to any host other than localhost/127.0.0.1 (or hosts listed in
    PVS_FAKE_ALLOW_HOSTS) is CAPTURED in the outbox and answered locally.
  - Everything that would have left the machine is written to
    <state dir>/outbox.jsonl so tests can assert on it.

Fault injection: <state dir>/faults.json, e.g.
  {"luma_direct": ["http_400"], "elevenlabs": ["ok", "http_500"], "veo": ["no_output"]}
Each key holds a list consumed one entry per call; when exhausted the call
succeeds. Editing the file starts a new scenario (counters reset).
Fault kinds: ok, http_400, http_422, http_429, http_500, timeout, failed
(Luma accepted then state=failed / fal raises), no_output, quota (ElevenLabs
quota exceeded), people (Florence mentions a person), slow:<secs>.
Keys: luma_direct, elevenlabs, anthropic, florence, veo, kling, luma_fal, lyra,
ltx, topaz, upscale_image, watermark, fal_other.
"""
import io
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

ENABLED = os.getenv("PVS_FAKE_PROVIDERS", "").strip() == "1"
FAKE_HOST = "fake.pvs.invalid"
STATE_DIR = Path(os.getenv("PVS_FAKE_DIR") or (Path(tempfile.gettempdir()) / "pvs_fake"))
_SPEECH_CHARS_PER_SEC = 15.0   # fake TTS: duration = len(text) / 15
_DEFAULT_DESCRIPTION = "A bright living room with a sofa and a large window, wooden floor and white walls."

_lock = threading.Lock()
_installed = False
_uploads = {}          # token -> local path
_luma_gens = {}        # id -> dict(image_url, dur, polls, fault)
_counters = {}         # fault key -> calls consumed
_faults_mtime = [None]


# ── helpers ──────────────────────────────────────────────────────────────────
def _state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def outbox(kind, **data):
    """Record something that would have left the machine."""
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind}
        rec.update(data)
        with _lock:
            with open(_state() / "outbox.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception as e:  # never break the pipeline because of bookkeeping
        log.warning(f"[Fake] outbox write failed: {e}")


def next_fault(key):
    """Returns the next scripted fault kind for this provider key ('ok' if none)."""
    p = _state() / "faults.json"
    try:
        mtime = p.stat().st_mtime if p.exists() else None
    except OSError:
        mtime = None
    with _lock:
        if mtime != _faults_mtime[0]:
            _faults_mtime[0] = mtime
            _counters.clear()
        if mtime is None:
            return "ok"
        try:
            spec = json.loads(p.read_text(encoding="utf-8")).get(key) or []
        except Exception:
            return "ok"
        i = _counters.get(key, 0)
        _counters[key] = i + 1
        return spec[i] if i < len(spec) else "ok"


def _apply_slow(kind):
    if kind.startswith("slow:"):
        try:
            time.sleep(float(kind.split(":", 1)[1]))
        except Exception:
            pass
        return "ok"
    return kind


def _ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-300:]}")


def _media_dir():
    d = _state() / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_video(token, secs, portrait=False):
    """A real playable mp4. If token maps to an uploaded photo, the clip shows that photo."""
    w, h = (1080, 1920) if portrait else (1920, 1080)
    out = _media_dir() / f"v_{token}_{int(secs)}_{w}x{h}.mp4"
    if out.exists():
        return out.read_bytes()
    src = _uploads.get(token)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    tmp = out.with_suffix(".tmp.mp4")
    if src and os.path.exists(src):
        _ffmpeg(["-loop", "1", "-framerate", "24", "-i", src, "-t", str(secs), "-vf", vf,
                 "-c:v", "libx264", "-preset", "ultrafast", "-r", "24", str(tmp)])
    else:
        _ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=24", "-t", str(secs),
                 "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(tmp)])
    tmp.replace(out)
    return out.read_bytes()


def _make_mp3(secs):
    secs = max(0.5, round(secs, 1))
    out = _media_dir() / f"a_{secs}.mp3"
    if out.exists():
        return out.read_bytes()
    tmp = out.with_suffix(".tmp.mp3")
    _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=220:duration={secs}", "-filter:a", "volume=0.2",
             "-c:a", "libmp3lame", "-q:a", "6", str(tmp)])
    tmp.replace(out)
    return out.read_bytes()


def _fake_url(kind, token, ext):
    return f"https://{FAKE_HOST}/{kind}/{token}{ext}"


def _dur_secs(arguments, default=5):
    d = str((arguments or {}).get("duration", default))
    m = re.search(r"\d+", d)
    return int(m.group(0)) if m else default


# ── fal_client fakes ─────────────────────────────────────────────────────────
def _fal_key(endpoint):
    e = (endpoint or "").lower()
    for sub, key in (("florence", "florence"), ("veo", "veo"), ("kling", "kling"),
                     ("luma", "luma_fal"), ("lyra", "lyra"), ("ltx", "ltx"),
                     ("topaz", "topaz"), ("aura-sr", "upscale_image"),
                     ("object-removal", "watermark")):
        if sub in e:
            return key
    return "fal_other"


def fake_upload_file(path, *a, **kw):
    import hashlib
    # The pipeline deletes its temp file right after upload (video_generation._upload_bytes),
    # so keep our own copy: the fake clip must show the real photo.
    data = open(path, "rb").read() if os.path.exists(path) else b""
    token = hashlib.sha1(data + str(path).encode()).hexdigest()[:12]
    keep = _media_dir() / f"up_{token}{os.path.splitext(str(path))[1] or '.bin'}"
    if data and not keep.exists():
        keep.write_bytes(data)
    _uploads[token] = str(keep)
    outbox("fal_upload", path=str(path))
    return _fake_url("file", token, os.path.splitext(str(path))[1] or ".bin")


def _token_of(url):
    m = re.search(r"/(?:file|video)/([0-9a-f]{12})", url or "")
    return m.group(1) if m else "none"


def fake_subscribe(endpoint, arguments=None, **kw):
    arguments = arguments or {}
    key = _fal_key(endpoint)
    fault = _apply_slow(next_fault(key))
    outbox("fal_subscribe", endpoint=endpoint, fault=fault)
    if fault == "timeout":
        raise TimeoutError(f"[fake] fal queue stalled on {endpoint}")
    if fault in ("failed", "http_500", "http_400", "http_422", "http_429", "quota"):
        raise RuntimeError(f"[fake] fal request failed ({fault}) on {endpoint}")
    if fault == "no_output":
        return {}
    img = arguments.get("image_url") or arguments.get("video_url") or ""
    tok = _token_of(img)
    secs = _dur_secs(arguments)
    if key == "florence":
        desc = _DEFAULT_DESCRIPTION
        if fault == "people":
            desc = "A man standing in a bright living room next to a sofa and a large window."
        return {"results": desc}
    out_img = img if img.startswith(f"https://{FAKE_HOST}/") else _fake_url("file", tok, ".jpg")
    portrait = str(arguments.get("aspect_ratio", "")) in ("9:16", "9:21", "3:4")
    vid = _fake_url("video", f"{tok}-{secs}{'p' if portrait else ''}", ".mp4")
    return {"video": {"url": vid}, "image": {"url": out_img}, "images": [{"url": out_img}],
            "depth_map": {"url": out_img}}


# ── HTTP routing (requests) ──────────────────────────────────────────────────
def _resp(request, status, body=b"", headers=None):
    import requests
    r = requests.Response()
    r.status_code = status
    r.headers.update(headers or {})
    r.url = request.url
    r.request = request
    r.encoding = "utf-8"
    r.raw = io.BytesIO(body if isinstance(body, bytes) else body.encode("utf-8"))
    return r


def _json_resp(request, status, obj):
    return _resp(request, status, json.dumps(obj).encode("utf-8"), {"Content-Type": "application/json"})


def _body_json(request):
    b = request.body
    if isinstance(b, bytes):
        b = b.decode("utf-8", "ignore")
    try:
        return json.loads(b) if b else {}
    except Exception:
        return {}


def _serve_fake_host(request):
    path = urlparse(request.url).path
    m = re.match(r"^/video/([0-9a-f]{12}|none)-(\d+)(p?)\.mp4$", path)
    if m:
        return _resp(request, 200, _make_video(m.group(1), int(m.group(2)), portrait=bool(m.group(3))),
                     {"Content-Type": "video/mp4"})
    m = re.match(r"^/file/([0-9a-f]{12}|none)\.\w+$", path)
    if m:
        src = _uploads.get(m.group(1))
        if src and os.path.exists(src):
            return _resp(request, 200, Path(src).read_bytes(), {"Content-Type": "application/octet-stream"})
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1920, 1080), (200, 190, 170)).save(buf, "JPEG")
        return _resp(request, 200, buf.getvalue(), {"Content-Type": "image/jpeg"})
    return _resp(request, 404, b"not found")


def _luma(request):
    if request.method == "POST":
        fault = _apply_slow(next_fault("luma_direct"))
        outbox("luma_create", fault=fault)
        if fault.startswith("http_"):
            return _json_resp(request, int(fault[5:]), {"error": f"[fake] {fault}"})
        if fault == "timeout":
            import requests
            raise requests.exceptions.Timeout("[fake] luma timeout")
        body = _body_json(request)
        start = ((body.get("video") or {}).get("start_frame") or {}).get("url", "")
        dur = _dur_secs(body.get("video") or {}, 5)
        gid = f"fakegen{len(_luma_gens) + 1:04d}"
        _luma_gens[gid] = {"image_url": start, "dur": dur, "polls": 0, "fault": fault,
                           "portrait": body.get("aspect_ratio") in ("9:16", "3:4")}
        return _json_resp(request, 201, {"id": gid, "state": "queued"})
    gid = urlparse(request.url).path.rsplit("/", 1)[-1]
    g = _luma_gens.get(gid)
    if not g:
        return _json_resp(request, 404, {"error": "unknown generation"})
    g["polls"] += 1
    if g["polls"] < 2:
        return _json_resp(request, 200, {"id": gid, "state": "processing"})
    if g["fault"] == "failed":
        return _json_resp(request, 200, {"id": gid, "state": "failed", "failure_reason": "[fake] generation failed"})
    vid = _fake_url("video", f"{_token_of(g['image_url'])}-{g['dur']}{'p' if g['portrait'] else ''}", ".mp4")
    return _json_resp(request, 200, {"id": gid, "state": "completed", "output": [{"url": vid}]})


def _elevenlabs(request):
    path = urlparse(request.url).path
    if "/text-to-speech/" in path and request.method == "POST":
        fault = _apply_slow(next_fault("elevenlabs"))
        text = _body_json(request).get("text", "")
        outbox("elevenlabs_tts", chars=len(text), fault=fault)
        if fault == "quota":
            return _json_resp(request, 401, {"detail": {"status": "quota_exceeded", "message": "[fake] quota exceeded"}})
        if fault.startswith("http_"):
            return _json_resp(request, int(fault[5:]), {"detail": f"[fake] {fault}"})
        if fault == "timeout":
            import requests
            raise requests.exceptions.Timeout("[fake] elevenlabs timeout")
        plain = re.sub(r"<[^>]+>", "", text)
        return _resp(request, 200, _make_mp3(len(plain) / _SPEECH_CHARS_PER_SEC), {"Content-Type": "audio/mpeg"})
    if path.endswith("/user/subscription") or path.endswith("/user"):
        return _json_resp(request, 200, {"character_count": 1000, "character_limit": 100000,
                                         "subscription": {"character_count": 1000, "character_limit": 100000},
                                         "next_character_count_reset_unix": int(time.time()) + 86400 * 20})
    return _json_resp(request, 200, {})


def _route(request):
    host = (urlparse(request.url).hostname or "").lower()
    if host == FAKE_HOST:
        return _serve_fake_host(request)
    if host.endswith("lumalabs.ai"):
        return _luma(request)
    if host.endswith("elevenlabs.io"):
        return _elevenlabs(request)
    return None


def _allowed_host(host):
    allow = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    allow |= {h.strip().lower() for h in os.getenv("PVS_FAKE_ALLOW_HOSTS", "").split(",") if h.strip()}
    return host in allow


def _patch_requests():
    import requests
    from requests.adapters import HTTPAdapter
    real_send = HTTPAdapter.send

    def send(self, request, **kw):
        host = (urlparse(request.url).hostname or "").lower()
        if _allowed_host(host):
            return real_send(self, request, **kw)
        resp = _route(request)
        if resp is not None:
            return resp
        # Anything else would leave the machine: capture it, never send it.
        b = request.body
        if isinstance(b, bytes):
            b = b.decode("utf-8", "ignore")
        outbox("http_blocked", method=request.method, url=request.url, body=(b or "")[:2000],
               headers={k: v for k, v in request.headers.items() if k.lower() not in ("authorization", "xi-api-key")})
        if request.method == "GET":
            return _resp(request, 404, b"[fake] external GET blocked")
        return _json_resp(request, 200, {"fake": True, "captured": True})

    HTTPAdapter.send = send


# ── anthropic fake ───────────────────────────────────────────────────────────
class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _Response:
    def __init__(self, text, i=900, o=None):
        self.content = [_Block(text)]
        self.usage = _Usage(i, o if o is not None else max(5, len(text) // 4))
        self.stop_reason = "end_turn"


def _prompt_text(messages):
    parts = []
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.extend(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return "\n".join(parts)


_SENTENCES = [
    "Benvenuti in questo appartamento luminoso, in una zona comoda e ben servita.",
    "Il soggiorno e' ampio, con una grande finestra che porta luce naturale tutto il giorno.",
    "La cucina e' funzionale e ben organizzata, ideale per la vita di ogni giorno.",
    "Le camere sono silenziose e confortevoli, con spazio per l'armadio.",
    "I bagni sono curati e in buono stato.",
    "Una soluzione pratica e pronta da vivere, vicino a negozi e trasporti.",
    "Contattate l'agenzia per organizzare una visita.",
]


def _speech_text(words):
    """Plain Italian-looking text with about `words` words (deterministic)."""
    out, n, i = [], 0, 0
    while n < words:
        sent = _SENTENCES[i % len(_SENTENCES)]
        out.append(sent)
        n += len(sent.split())
        i += 1
    return " ".join(" ".join(out).split()[:words])


def _fake_claude_text(prompt, max_tokens):
    if "Answer with ONLY the category word" in prompt:
        return "living"
    n = len(re.findall(r"Photo \d+:", prompt))
    if n:
        return "[" + ", ".join(str(i) for i in range(1, n + 1)) + "]"
    m = re.search(r"for each of these scenes/categories: ([^\n]+)", prompt)
    if m:
        cats = [c.strip() for c in m.group(1).split(",") if c.strip()]
        return json.dumps({c: f"{c.capitalize()} luminoso" for c in cats}, ensure_ascii=False)
    m = re.search(r"no more than (\d+) words", prompt)
    if m:
        return _speech_text(max(10, int(m.group(1)) - 5))
    m = re.search(r"about (\d+) more words", prompt)
    # ~62 words is about 28 s of fake speech (inside the 22-32 s band)
    return _speech_text(62 + (int(m.group(1)) if m else 0))


class _Messages:
    def create(self, model=None, max_tokens=1024, messages=None, **kw):
        fault = _apply_slow(next_fault("anthropic"))
        prompt = _prompt_text(messages)
        outbox("anthropic", model=model, max_tokens=max_tokens, fault=fault, prompt_chars=len(prompt))
        if fault != "ok":
            raise RuntimeError(f"[fake] anthropic call failed ({fault})")
        return _Response(_fake_claude_text(prompt, max_tokens), i=max(200, len(prompt) // 4))


class FakeAnthropic:
    def __init__(self, *a, **kw):
        self.messages = _Messages()


# ── smtp fake ────────────────────────────────────────────────────────────────
class FakeSMTP:
    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, *a, **kw): return (235, b"ok")
    def ehlo(self, *a, **kw): return (250, b"ok")
    def starttls(self, *a, **kw): return (220, b"ok")
    def quit(self): return (221, b"bye")

    def send_message(self, msg, *a, **kw):
        outbox("email", to=str(msg.get("To")), subject=str(msg.get("Subject")))
        return {}

    def sendmail(self, from_addr, to_addrs, msg, *a, **kw):
        outbox("email", to=str(to_addrs), subject=str(msg)[:200])
        return {}


# ── install ──────────────────────────────────────────────────────────────────
def install():
    """Idempotent. Call once, early, only when ENABLED."""
    global _installed
    if _installed:
        return
    for k in ("FAL_KEY", "LUMA_API_KEY", "ELEVENLABS_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_TTS_API_KEY"):
        os.environ[k] = "fake-key-not-real"
    import fal_client
    fal_client.subscribe = fake_subscribe
    fal_client.upload_file = fake_upload_file
    import anthropic
    anthropic.Anthropic = FakeAnthropic
    import smtplib
    smtplib.SMTP_SSL = FakeSMTP
    smtplib.SMTP = FakeSMTP
    _patch_requests()
    try:
        import video_generation as vg
        vg._LUMA_DIRECT_POLL_INTERVAL_SECS = float(os.getenv("PVS_FAKE_POLL_SECS", "0.05"))
    except Exception as e:
        log.warning(f"[Fake] could not shorten Luma poll interval: {e}")
    _installed = True
    log.warning("=" * 70)
    log.warning("[FAKE PROVIDERS] ON -- no paid API, no real email/push/webhook leaves this machine. "
                f"State dir: {STATE_DIR}")
    log.warning("=" * 70)


def install_if_enabled():
    if ENABLED:
        install()
    return ENABLED
