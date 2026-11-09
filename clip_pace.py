"""clip_pace.py - slows a clip the QC judge called too fast (2026-11-09, Michele).
The judge (clip_standard, ONE call per clip, already asking for speed) answers static | slow | fast | very_fast. For fast / very_fast the clip is rebuilt BEFORE anything else
uses it: only the first part of the clip is kept and stretched back to its original length, so the scene stays 5 s and every later step (narration timing, assembly, rework,
reassemble) simply sees a normal clip, with no second speed mechanism. Cutting the end also removes the stretch where the camera rushes / runs into a wall / invents.
  fast       keeps the first 4.0 s of a 5 s clip -> played at 0.8x
  very_fast  keeps the first 3.0 s of a 5 s clip -> played at 0.6x   (the floor; slower than that would look like a still)
The original file is kept next to it as <clip>.pre_pace (never deleted); <clip>.pace.json marks a clip as done, so it is never slowed twice.
Switch: PVS_PACE_FIX=1 (default OFF). Never raises. Fake providers / tests: not applied.
  python3 clip_pace.py JOB:SCENE fast|very_fast     slows that one existing clip now (scene 1-based), ignoring the switch; then reassemble the job"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

KEEP_FRACTION = {"fast": 0.8, "very_fast": 0.6}      # share of the clip that is kept = playback speed after the fix
MIN_SECS = 3.0
FPS = 24


def enabled() -> bool:
    return os.getenv("PVS_PACE_FIX", "0").strip().lower() in ("1", "true", "yes", "on")


def _duration(p) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True, timeout=60).stdout
    return float(out.strip())


def marker(clip_path) -> Path:
    return Path(str(clip_path) + ".pace.json")


def backup(clip_path) -> Path:
    return Path(str(clip_path) + ".pre_pace")


def apply(clip_path, speed_word, force=False) -> dict:
    """{"applied": bool, "reason"/"keep_secs"/"factor"/"orig_secs"}. Never raises."""
    try:
        frac = KEEP_FRACTION.get(str(speed_word or "").strip().lower())
        if frac is None:
            return {"applied": False, "reason": "speed not fast"}
        if not force and not enabled():
            return {"applied": False, "reason": "switch off"}
        src = Path(clip_path)
        if marker(src).exists():
            return {"applied": False, "reason": "already slowed"}
        orig = _duration(src)
        keep = max(MIN_SECS, orig * frac)
        if orig < MIN_SECS + 0.5:
            return {"applied": False, "reason": "clip too short to slow", "orig_secs": round(orig, 2)}
        tmp = Path(str(src) + ".pace_tmp.mp4")
        k = orig / keep
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-t", f"{keep:.3f}", "-i", str(src), "-an",
                            "-vf", f"setpts=PTS*{k:.5f},minterpolate=fps={FPS}:mi_mode=blend", "-t", f"{orig:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                            "-pix_fmt", "yuv420p", "-f", "mp4", str(tmp)], stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            return {"applied": False, "reason": "ffmpeg failed: " + r.stderr[-200:].decode("utf-8", "replace")}
        new = _duration(tmp)
        if abs(new - orig) > 0.25:
            tmp.unlink()
            return {"applied": False, "reason": f"length check failed ({new:.2f}s vs {orig:.2f}s)"}
        if not backup(src).exists():
            shutil.copy2(src, backup(src))
        os.replace(tmp, src)
        info = {"applied": True, "speed": speed_word, "keep_secs": round(keep, 2), "factor": round(keep / orig, 3), "orig_secs": round(orig, 2), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        marker(src).write_text(json.dumps(info), encoding="utf-8")
        return info
    except Exception as e:
        return {"applied": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}


def main(argv) -> int:
    import clip_provenance
    if len(argv) != 3 or ":" not in argv[1]:
        print(__doc__.split("\n")[-1])
        return 2
    job, _, sc = argv[1].partition(":")
    here = Path(__file__).resolve().parent
    roots = [here / "jobs", Path(os.environ.get("PVS_TEST_JOBS_DIR") or "/var/www/pvs_test_jobs")]
    d = next((r / job for r in roots if (r / job / "job_meta.json").exists()), None)
    if d is None:
        print("job non trovato")
        return 1
    scenes = json.loads((d / "job_meta.json").read_text(encoding="utf-8")).get("scenes_config") or []
    i = int(sc) - 1
    mp4 = clip_provenance.clip_file_for_scene(d, i, scenes[i].get("scene_id")) if 0 <= i < len(scenes) else None
    if not mp4:
        print("clip non trovato")
        return 1
    print(argv[1], mp4.name, apply(mp4, argv[2], force=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
