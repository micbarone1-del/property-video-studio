"""Tests of the light preview copies (preview_proxy.py, 2026-10-26). Real ffmpeg on a synthetic 1080p clip; no network, no jobs/ touched
(everything in a temp dir). The key promise: the preview is lighter, the ORIGINAL is untouched and is what downloads serve."""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.getcwd())
import preview_proxy as pp

ok_n, fails = 0, []


def check(name, cond, extra=""):
    global ok_n
    if cond:
        ok_n += 1
        print(f"PASS {name}")
    else:
        fails.append(name)
        print(f"FAIL {name} {extra}")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


tmp = Path(tempfile.mkdtemp())
src = tmp / "final.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=24:duration=3",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-b:v", "8M", "-c:a", "aac", "-shortest", str(src)], check=True)
before = sha(src)
cache = tmp / "preview_cache"

light = pp.light_copy(src, cache)
check("P1 a light copy is built in the cache dir, not the original", light != src and light.parent == cache and light.exists())
check("P2 it is lighter than the original", light.stat().st_size < src.stat().st_size / 2, (light.stat().st_size, src.stat().st_size))
i = pp.info(light)
check("P3 height is 540, width even", i.get("height") == 540 and i.get("width") % 2 == 0, i)
check("P4 the original is byte-for-byte untouched", sha(src) == before)
io = pp.info(src)
check("P5 info of the original reports 1920x1080 and a size", io.get("width") == 1920 and io.get("height") == 1080 and io.get("size_mb") is not None, io)
m1 = light.stat().st_mtime_ns
check("P6 second call reuses the cache (same file, not rebuilt)", pp.light_copy(src, cache) == light and light.stat().st_mtime_ns == m1)
check("P7 name never looks like a scene clip and no .tmp is left", light.name.startswith("prev_") and not list(cache.glob("*.tmp")))
a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(light)], capture_output=True, text=True).stdout
check("P8 audio kept", "aac" in a, a)
bad = tmp / "broken.mp4"
bad.write_bytes(b"not a video")
check("P9 fail-open: a broken file returns the ORIGINAL path, no exception, no leftovers", pp.light_copy(bad, cache) == bad and not list(cache.glob("*broken*")))
check("P10 missing file fail-open", pp.light_copy(tmp / "nope.mp4", cache) == tmp / "nope.mp4")
os.utime(src, (1, 1))   # a re-assembled video (new mtime) must get a new preview
check("P11 changed original -> new cache name", pp.cache_path(src, cache) != light)

src_code = open("preview_proxy.py").read()
check("P12 ffmpeg/ffprobe never read the terminal (-nostdin + stdin=DEVNULL): real server smoke test hung with 0 bytes on 2026-10-26", "-nostdin" in src_code and src_code.count("stdin=subprocess.DEVNULL") == 2)
# the build must work with stdin closed, as under screen/uvicorn
import subprocess as _sp
_r = _sp.run([sys.executable, "-c", "import preview_proxy as p,sys;from pathlib import Path;print(p.light_copy(Path(sys.argv[1]),Path(sys.argv[2])).name)", str(tmp / "final2.mp4"), str(tmp / "c2")], stdin=_sp.DEVNULL, capture_output=True, text=True, cwd=os.getcwd()) if (tmp / "final2.mp4").write_bytes(src.read_bytes()) else None
check("P13 builds a preview in a child process with stdin closed", _r is not None and _r.stdout.strip().startswith("prev_"), _r and (_r.stdout, _r.stderr[-200:]))

# wiring checks in the real files (no server in the sandbox)
api = open("api_server.py").read()
ui = open("ui.html").read()
check("W1 preview endpoints exist", '"/jobs/{job_id}/preview"' in api and '"/jobs/{job_id}/clip/{scene_index}/preview"' in api and '"/jobs/{job_id}/video-info"' in api)
dl = api[api.index('@app.get("/jobs/{job_id}/download")'):]
dl = dl[:dl.index("# ── QC approval gate")]
check("W2 the download endpoint never touches the preview", "preview" not in dl and "FileResponse" in dl)
check("W3 /preview exempt from the header like /download (a <video> tag cannot send it); video-info is NOT exempt", 'path.endswith("/preview")' in api and "video-info" not in api[api.index("async def"):api.index("path.endswith(\"/preview\")")] )
check("W4 UI players use previews", ui.count("/preview") >= 4 and '/jobs/${jobId}/download" download' in ui)
check("W5 UI download links still point at /download", 'href="/jobs/${jobId}/download" download' in ui and "document.getElementById('download-link').href   = dlUrl" in ui)
check("W6 no video tag plays /download any more", 'src="/jobs/${jobId}/download"' not in ui and "video-preview').src    = dlUrl" not in ui)
check("W7 one resolver for the clip file", api.count("def _resolve_clip_path") == 1 and api.count("_resolve_clip_path(job_id, scene_index)") == 2)

# 2026-10-27: warm-up in the background so the preview opens at once
import time
src2 = tmp / "clip2.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=24:duration=2", "-c:v", "libx264", "-b:v", "6M", str(src2)], check=True, stdin=subprocess.DEVNULL)
before2 = sha(src2)
cache2 = tmp / "warm_cache"
t0 = time.time(); pp.warm([src2, tmp / "does_not_exist.mp4", None], cache2); returned_in = time.time() - t0
check("M1 warm() returns at once (background thread), never raises on a missing file or None", returned_in < 1.0, returned_in)
for _ in range(100):
    if cache2.exists() and any(cache2.glob("prev_clip2_*.mp4")): break
    time.sleep(0.2)
built = list(cache2.glob("prev_clip2_*.mp4"))
check("M2 the light copy appears in the cache without any request", len(built) == 1 and built[0].stat().st_size > 0)
check("M3 the original is untouched and no tmp file is left", sha(src2) == before2 and not list(cache2.glob("*.tmp")))
check("M4 the later request finds the copy already built (same path, no rebuild)", pp.light_copy(src2, cache2) == built[0])
check("M5 wiring: api_server warms previews when QC waits and when the video is done, via one helper", api.count("_warm_previews(job_id)") + api.count("_warm_previews(job_id, include_final=True)") == 2 and api.count("def _warm_previews") == 1)

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES: ' + str(fails)} ({ok_n}/{ok_n + len(fails)})")
sys.exit(1 if fails else 0)
