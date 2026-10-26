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

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES: ' + str(fails)} ({ok_n}/{ok_n + len(fails)})")
sys.exit(1 if fails else 0)
