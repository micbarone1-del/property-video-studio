"""Light preview copies of videos (2026-10-26, Michele: the preview of the finished video was too heavy to load quickly).

RULE: a preview is only a viewing copy. The DOWNLOAD endpoints never use it - they serve the original file byte for byte - so what
is downloaded or shared is always the full-quality video. The copy is built once with ffmpeg and cached in <job>/preview_cache/
(outside clips/, never named scene_*), keyed by the original's size and modification time so a re-assembled video gets a new preview.
Fail-open: if ffmpeg fails or is missing the caller gets the ORIGINAL path (heavier, but it plays). Nothing is ever deleted here:
a half-written file is a *.tmp that is replaced atomically with os.replace, stale previews are simply left (small).
"""
import json
import os
import subprocess
import threading
from pathlib import Path

PREVIEW_HEIGHT = 540          # light enough to start at once on a phone, sharp enough to judge a clip
CRF = "30"
_LOCK = threading.Lock()      # one build at a time: ffmpeg is heavy and two requests for the same file must not both encode


def _key(src: Path) -> str:
    st = src.stat()
    return f"prev_{src.stem}_{st.st_size}_{int(st.st_mtime)}.mp4"


def cache_path(src: Path, cache_dir: Path) -> Path:
    return Path(cache_dir) / _key(Path(src))


def build(src: Path, dst: Path, timeout: int = 300) -> bool:
    """Encode src -> dst (atomically). Never raises; False on any problem."""
    tmp = Path(str(dst) + ".tmp")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
               "-vf", f"scale=-2:'min({PREVIEW_HEIGHT},ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF,
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", "-f", "mp4", str(tmp)]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            print(f"[Preview] ffmpeg failed for {src.name}: {r.stderr[-300:]!r}")
            return False
        os.replace(tmp, dst)
        return True
    except Exception as e:
        print(f"[Preview] could not build preview of {src.name}: {e}")
        return False


def light_copy(src, cache_dir) -> Path:
    """Path of the light copy of src (built on first use); the ORIGINAL src if the copy cannot be made."""
    src = Path(src)
    try:
        dst = cache_path(src, cache_dir)
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        with _LOCK:
            if dst.exists() and dst.stat().st_size > 0:
                return dst
            return dst if build(src, dst) else src
    except Exception as e:
        print(f"[Preview] fail-open for {src}: {e}")
        return src


def info(path) -> dict:
    """{'width','height','size_mb'} of a video file, or {} if it cannot be read."""
    path = Path(path)
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "json", str(path)], capture_output=True, timeout=30)
        st = (json.loads(r.stdout or b"{}").get("streams") or [{}])[0]
        return {"width": st.get("width"), "height": st.get("height"), "size_mb": round(path.stat().st_size / 1048576, 1)}
    except Exception:
        return {}
