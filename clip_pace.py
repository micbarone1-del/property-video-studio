"""clip_pace.py - PROPORTIONAL slowdown of a clip that is too fast (2026-11-09, Michele: a measured value must give a proportional fix, never two levels).
The measure comes from the clip QC (clip_standard.measures, the tracked-feature transforms already computed for the geometry rule): `motion_peak` = the apparent camera speed in the
fastest second of the clip, in % of the frame width per second (zoom, pan and curved paths all count). If it is above the limit, factor = limit / motion_peak (never below
MIN_FACTOR): the first `factor` share of the clip is kept and stretched back to its original length, so the scene stays 5 s and every later step (narration timing, assembly,
rework, reassemble) simply sees a normal clip - no second speed mechanism. After the fix the fastest second is about at the limit; cutting the end also removes the stretch where the
camera rushes / runs into a wall / invents.
The original is kept as <clip>.pre_pace (never deleted); <clip>.pace.json marks a clip as done. Nothing runs unless BOTH are set: PVS_PACE_FIX=1 and PVS_PACE_LIMIT=<number>
(the limit is calibrated on Michele's judgments with `calibrate`; there is deliberately no default). Never raises.
  python3 clip_pace.py scan                       every clip of production + test: measures (of the ORIGINAL when a .pre_pace exists)
  python3 clip_pace.py calibrate                  Michele's labelled clips sorted by motion_peak (clip_pace_labels.json) + how well a limit separates them
  python3 clip_pace.py review LIMIT              before/after copies of the labelled clips that LIMIT would slow, in <test jobs>/_test_scratch (page /clip-review?pace=1)
  python3 clip_pace.py apply JOB:SCENE LIMIT [redo]   slows that clip now, ignoring the switches ('redo' restarts from the kept original)"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MIN_FACTOR = 0.6          # slower than 0.6x would look like a still
MIN_SECS = 3.0
FPS = 24
HERE = Path(__file__).resolve().parent


def enabled() -> bool:
    return os.getenv("PVS_PACE_FIX", "0").strip().lower() in ("1", "true", "yes", "on")


def limit_from_env():
    try:
        v = float(os.getenv("PVS_PACE_LIMIT", ""))
        return v if v > 0 else None
    except ValueError:
        return None


def factor_for(motion_peak, limit):
    """Pure: None = no fix needed / possible; else the playback factor in [MIN_FACTOR, 1)."""
    if not motion_peak or not limit or motion_peak <= limit:
        return None
    return max(MIN_FACTOR, limit / motion_peak)


def _duration(p) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True, timeout=60).stdout
    return float(out.strip())


def marker(clip_path) -> Path:
    return Path(str(clip_path) + ".pace.json")


def backup(clip_path) -> Path:
    return Path(str(clip_path) + ".pre_pace")


def measure_file(path) -> dict:
    import clip_standard as cs
    frames, fps = cs.read_frames(path)
    return cs.measures(frames, fps) if frames else {"ok": False, "why": "clip not readable"}


def render(src, dst, orig, keep):
    """The ONE ffmpeg step: the first `keep` seconds of src stretched to `orig` seconds, written to dst. (ok, error text)."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-t", f"{keep:.3f}", "-i", str(src), "-an",
                        "-vf", f"setpts=PTS*{orig / keep:.5f},minterpolate=fps={FPS}:mi_mode=blend", "-t", f"{orig:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                        "-pix_fmt", "yuv420p", "-f", "mp4", str(dst)], stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    if r.returncode != 0 or not Path(dst).exists() or Path(dst).stat().st_size == 0:
        return False, r.stderr[-200:].decode("utf-8", "replace")
    return True, ""


def apply(clip_path, geo, force=False, redo=False, limit=None) -> dict:
    """geo = the measures dict of the QC (clip_standard.measures, or the whole evaluate() result with its "geo"). {"applied": bool, ...}. Never raises."""
    try:
        if isinstance(geo, dict) and "geo" in geo:
            geo = geo["geo"]
        limit = limit or limit_from_env()
        if not force and not enabled():
            return {"applied": False, "reason": "switch off"}
        if not limit:
            return {"applied": False, "reason": "no limit set (PVS_PACE_LIMIT)"}
        if not geo or not geo.get("ok"):
            return {"applied": False, "reason": "speed not measured"}
        peak = geo.get("motion_peak")
        f = factor_for(peak, limit)
        if f is None:
            return {"applied": False, "reason": "within limit", "motion_peak": peak}
        src = Path(clip_path)
        if marker(src).exists() and not redo:
            return {"applied": False, "reason": "already slowed"}
        if redo and backup(src).exists():          # start again from the ORIGINAL clip (kept as .pre_pace), nothing is deleted
            shutil.copy2(backup(src), src)
        orig = _duration(src)
        if orig < MIN_SECS + 0.5:
            return {"applied": False, "reason": "clip too short to slow", "orig_secs": round(orig, 2)}
        keep = max(MIN_SECS, orig * f)
        tmp = Path(str(src) + ".pace_tmp.mp4")
        ok, err = render(src, tmp, orig, keep)
        if not ok:
            return {"applied": False, "reason": "ffmpeg failed: " + err}
        new = _duration(tmp)
        if abs(new - orig) > 0.25:
            tmp.unlink()
            return {"applied": False, "reason": f"length check failed ({new:.2f}s vs {orig:.2f}s)"}
        if not backup(src).exists():
            shutil.copy2(src, backup(src))
        os.replace(tmp, src)
        info = {"applied": True, "motion_peak": peak, "limit": limit, "keep_secs": round(keep, 2), "factor": round(keep / orig, 3), "orig_secs": round(orig, 2),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        marker(src).write_text(json.dumps(info), encoding="utf-8")
        return info
    except Exception as e:
        return {"applied": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}


# ── command line: scan / calibrate / apply ──────────────────────────────────────────────
def _roots():
    return [HERE / "jobs", Path(os.environ.get("PVS_TEST_JOBS_DIR") or "/var/www/pvs_test_jobs")]


def _clips_of(job_dir):
    import clip_provenance
    meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
    for i, s in enumerate(meta.get("scenes_config") or []):
        mp4 = clip_provenance.clip_file_for_scene(job_dir, i, s.get("scene_id"))
        if mp4:
            yield i + 1, s, mp4


def _original(mp4) -> Path:
    return backup(mp4) if backup(mp4).exists() else Path(mp4)


def _find_job(job):
    return next((r / job for r in _roots() if (r / job / "job_meta.json").exists()), None)


def _line(job, n, s, g):
    return (f"{job}:{n} {str(s.get('category')):<10} prof={str(s.get('depth')):<7} motion_peak={g.get('motion_peak')} motion_mean={g.get('motion_mean')} "
            f"zoom_net={g.get('zoom_net')} zoom_rate={g.get('zoom_rate')}") if g.get("ok") else f"{job}:{n} {s.get('category')} non misurabile ({g.get('why')})"


def cmd_scan():
    seen = set()
    for root in _roots():
        for d in sorted(Path(root).glob("*/")):
            if d.name in seen or d.name.startswith("_") or not (d / "job_meta.json").exists():
                continue
            seen.add(d.name)
            try:
                for n, s, mp4 in _clips_of(d):
                    print(_line(d.name, n, s, measure_file(_original(mp4))))
            except Exception as e:
                print(d.name, "errore", e)
    return 0


def cmd_calibrate():
    labels = {k: v for k, v in json.loads((HERE / "clip_pace_labels.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    rows = []
    for key, lab in labels.items():
        job, _, sc = key.partition(":")
        d = _find_job(job)
        if d is None:
            print(key, "job non trovato")
            continue
        for n, s, mp4 in _clips_of(d):
            if n == int(sc):
                g = measure_file(_original(mp4))
                rows.append((g.get("motion_peak") if g.get("ok") else None, key, lab, s, g))
    for peak, key, lab, s, g in sorted(rows, key=lambda r: (r[0] is None, r[0] or 0)):
        print(f"{lab:<12} {_line(*key.split(':')[:1], int(key.split(':')[1]), s, g)}")
    order = {"lento": 0, "giusto": 1, "veloce": 2, "moltoveloce": 3}
    ok = [(p, order[l]) for p, _, l, _, _ in rows if p is not None]
    print("--- limite candidato: quanti 'giusto/lento' sopra il limite (falsi allarmi) e quanti 'veloce/moltoveloce' sotto (mancati)")
    for lim in sorted({p for p, _ in ok}):
        fa = sum(1 for p, o in ok if p > lim and o <= 1)
        miss = sum(1 for p, o in ok if p <= lim and o >= 2)
        print(f"limite {lim:>6}: falsi allarmi {fa}, mancati {miss}")
    return 0


def _plan_of(mp4):
    """(planned end scale, move) from the camera director's sidecar, or (None, None) - the anchor/depth-aware target of the clip, when there is one."""
    try:
        import movement_director
        pl = movement_director.last_plan(mp4)
        return (float(pl["scale"]), pl.get("move")) if pl and pl.get("scale") else (None, None)
    except Exception:
        return (None, None)


def _all_clips(skip):
    seen = set()
    for root in _roots():
        for d in sorted(Path(root).glob("*/")):
            if d.name in seen or d.name.startswith("_") or not (d / "job_meta.json").exists():
                continue
            seen.add(d.name)
            try:
                for n, s, mp4 in _clips_of(d):
                    if f"{d.name}:{n}" not in skip:
                        yield d.name, n, s, mp4
            except Exception:
                continue


def cmd_review(argv):
    """Before/after copies for Michele to watch, written ONLY into <test jobs>/_test_scratch/ (never touches a job).
    review LIMIT            the labelled clips that LIMIT would slow
    review LIMIT N          the same + N UNLABELLED clips from the doubtful zone (peak 6..40), spread evenly over that zone, so Michele's judgment can settle it"""
    import math
    limit = float(argv[0])
    extra = int(argv[1]) if len(argv) > 1 else 0
    out = _roots()[1] / "_test_scratch"
    out.mkdir(parents=True, exist_ok=True)
    labels = {k: v for k, v in json.loads((HERE / "clip_pace_labels.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    todo = []                                              # (key, label or "?", scene dict, mp4)
    for key, lab in labels.items():
        job, _, sc = key.partition(":")
        d = _find_job(job)
        for n, s, mp4 in (_clips_of(d) if d else []):
            if n == int(sc):
                todo.append((key, lab, s, mp4))
    if extra:
        pool = []
        for job, n, s, mp4 in _all_clips(set(labels)):
            g = measure_file(_original(mp4))
            if g.get("ok") and 6 <= g["motion_peak"] <= 40:
                pool.append((g["motion_peak"], f"{job}:{n}", s, mp4))
        pool.sort(key=lambda r: r[0])
        step = max(1, len(pool) // extra)
        for peak, key, s, mp4 in pool[::step][:extra]:
            todo.append((key, "?", s, mp4))
    index = []
    for key, lab, s, mp4 in todo:
        src = _original(mp4)
        g = measure_file(src)
        pk = g.get("motion_peak") if g.get("ok") else None
        f = factor_for(pk, limit)
        if f is None:
            print(key, lab, "non rallentato (picco", pk, ")")
            continue
        job, _, n = key.partition(":")
        name = f"pace_{job}_{n}"
        orig = _duration(src)
        keep = max(MIN_SECS, orig * f)
        shutil.copy2(src, out / f"{name}_prima.mp4")
        ok, err = render(src, out / f"{name}_dopo.mp4", orig, keep)
        ps, move = _plan_of(mp4)
        over = round(math.log(g["zoom_net"]) / math.log(ps), 2) if ps and ps > 1 and g.get("zoom_net", 0) > 1 else None
        print(key, lab, "picco", pk, "fattore", round(keep / orig, 3), "piano", ps, "sforamento", over, "ok" if ok else "ERRORE " + err)
        if ok:
            index.append({"key": key, "label": lab, "peak": pk, "factor": round(keep / orig, 3), "cat": s.get("category"), "depth": s.get("depth"), "plan": ps, "over": over,
                          "prima": f"{name}_prima.mp4", "dopo": f"{name}_dopo.mp4"})
    (out / "pace_review.json").write_text(json.dumps({"limit": limit, "items": index}), encoding="utf-8")
    print("pagina: /clip-review?pace=1  (porta 8002), clip:", len(index))
    return 0


def cmd_apply(argv):
    job, _, sc = argv[0].partition(":")
    d = _find_job(job)
    if d is None:
        print("job non trovato")
        return 1
    for n, s, mp4 in _clips_of(d):
        if n == int(sc):
            g = measure_file(_original(mp4))
            print(argv[0], mp4.name, apply(mp4, g, force=True, redo=(len(argv) > 2 and argv[2] == "redo"), limit=float(argv[1])))
            return 0
    print("clip non trovato")
    return 1


def main(argv) -> int:
    if len(argv) >= 2 and argv[1] == "scan":
        return cmd_scan()
    if len(argv) >= 2 and argv[1] == "calibrate":
        return cmd_calibrate()
    if len(argv) >= 3 and argv[1] == "review":
        return cmd_review(argv[2:])
    if len(argv) >= 4 and argv[1] == "apply" and ":" in argv[2]:
        return cmd_apply(argv[2:])
    print(__doc__.split("\n")[-4:])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
