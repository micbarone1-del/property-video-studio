"""exp_volume.py - volume check of the FINAL Luma prompt configuration on NEW listings, 360p draft tier (2026-11-04, Michele: "Facciamo volume", "Vai veloce con batch").

The drafts are NOT created here: GIAL listings are read by relinx_pilot_check.py (the app's from-url path says "Site not yet supported: relinx.it"; the
Relinx drafts have always been made on the TEST instance, port 8002, jobs in /var/www/pvs_test_jobs). This script takes the ids of drafts that are ready.

For every scene of every draft it calls the REAL production function video_generation.generate_video_single (director -> description -> prompt assembly -> Luma)
with the production arguments of that scene; the only differences are PVS_LUMA_RESOLUTION=360p (about 0.06 USD per clip) and the ORIGINAL photo of the scene
(a draft has no lighting-corrected copy yet). So the prompt is exactly what production sends with the current defaults (B, N, N1).
Then it measures the camera speed of each clip (clip_speed_probe), flags the ones much faster than the rest of the SAME listing (PROVISIONAL threshold,
calibrated at 360p only) and writes one video per listing (clips in scene order, label with listing/scene/plan) into the scratch folder served at
http://<server>:8000/test-scratch/<file>. Own spend cap (every STARTED clip counts, failed ones too). Nothing is deleted; nothing is written into a job.

  python3 exp_volume.py ids LOG_FILE            prints the ids of the drafts that reached 'in_review' in a relinx_pilot_check.py log
  python3 exp_volume.py plan JOB1,JOB2,...      free: shows what would happen
  python3 exp_volume.py run  JOB1,JOB2,... [--cap 6] [--workers 3]
  PVS_JOBS_DIR = where the drafts are (test instance: /var/www/pvs_test_jobs); PVS_VOLUME_SCRATCH = where videos go (production scratch, so port 8000 serves them)
"""
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS_DIR = Path(os.environ.get("PVS_JOBS_DIR") or (HERE / "jobs"))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (JOBS_DIR / "_test_scratch"))
OUT = SCRATCH / "volume"
SPEND = OUT / "spend.json"
CLIP_USD = 0.06
DEFAULT_CAP = 6.0
FAST_REL = 1.5            # PROVISIONAL: a clip whose motion energy is 1.5x the median of its listing is flagged "da guardare"
LINK_BASE = os.environ.get("PVS_LINK_BASE", "http://187.77.196.94:8000/test-scratch")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_lock = threading.Lock()


def say(*a):
    print(*a, flush=True)


def spent() -> float:
    try:
        return float(json.loads(SPEND.read_text()).get("total_usd", 0.0))
    except Exception:
        return 0.0


def add_spend(usd: float, note: str):
    with _lock:
        OUT.mkdir(parents=True, exist_ok=True)
        try:
            d = json.loads(SPEND.read_text())
        except Exception:
            d = {"total_usd": 0.0, "runs": []}
        d["total_usd"] = round(d["total_usd"] + usd, 4)
        d["runs"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "usd": usd, "note": note})
        SPEND.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def parse_job_ids(log_text: str) -> list:
    """Ids of the drafts that reached partner status in_review in a relinx_pilot_check.py log ('  job 1a2b3c4d partner status in_review after 40s ...')."""
    import re
    return re.findall(r"\bjob ([0-9a-f]{8}) partner status in_review", log_text)


def listing_label(job: str) -> str:
    try:
        meta = json.loads((JOBS_DIR / job / "job_meta.json").read_text())
        return str(meta.get("property_name") or meta.get("external_ref") or job)[:40]
    except Exception:
        return job


def scene_args(job: str, i: int):
    """The production arguments of ONE scene (api_server stage 3): image, space_type, pov_movement, lighting, intensity, output_format + camera_plan.intent_kwargs."""
    import camera_plan
    import exp_luma
    sc = exp_luma.load_scene(job, i)
    meta = sc["meta"]
    scene = sc["scene"]
    kw = dict(space_type=scene.get("space_type", "large"), pov_movement=scene.get("pov_movement", "walk_in_explore"),
              lighting=meta.get("lighting", "bright_natural"), model_tier="luma", output_format=meta.get("output_format", "landscape"),
              **camera_plan.intent_kwargs(scene))
    if meta.get("intensity"):
        kw["intensity"] = meta["intensity"]
    return sc["image"], kw, scene


def probe(mp4):
    try:
        import clip_speed_probe as p
        return p.speed(mp4)
    except Exception as e:
        say("probe failed:", e); return {}


def label_clip(src: Path, dst: Path, text: str) -> bool:
    safe = re.sub(r"[^A-Za-z0-9 ._>-]", " ", text)      # drawtext is picky: letters, digits and a few signs only
    vf = f"scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,drawtext=fontfile={FONT}:text='{safe}':x=10:y=10:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6,fps=24"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-an", "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)], check=True, timeout=120)
        return True
    except Exception as e:
        say("label failed:", e); return False


def concat(parts, dst: Path) -> bool:
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dst)], check=True, timeout=300)
        return True
    except Exception as e:
        say("concat failed:", e); return False


def plan_text(clip: Path) -> str:
    try:
        import movement_director as md
        h = md.last_plan(str(clip))
        return f"{h.get('move')} -> {h.get('target')}" if h else "?"
    except Exception:
        return "?"


def generate_scene(job, i, run_dir, cap):
    import video_generation as vg
    img, kw, scene = scene_args(job, i)
    clip = run_dir / f"{job}_scene_{i:03d}.mp4"
    row = {"job": job, "scene": i, "category": scene.get("category") or scene.get("room") or "", "ok": False, "clip": str(clip)}
    if not img:
        row["why"] = "no photo found"; return row
    with _lock:
        if spent() + CLIP_USD > cap:
            row["why"] = "cap reached, not generated"; return row
    add_spend(CLIP_USD, f"{job} scene {i}")
    t0 = time.time()
    try:
        ok = vg.generate_video_single(str(img), 5, str(clip), **kw)
    except Exception as e:
        row["why"] = f"error {e}"; return row
    row["ok"] = bool(ok and clip.exists())
    row["secs"] = round(time.time() - t0)
    if row["ok"]:
        row["speed"] = probe(clip)
        row["plan"] = plan_text(clip)
        say(f"{job} scene {i}: ok ({row['secs']} s) plan: {row['plan']}")
    else:
        row["why"] = "generation failed"
        say(f"{job} scene {i}: FAILED")
    return row


def main(job_ids, cap, workers, go):
    if not go:
        for j in job_ids:
            say("would generate one 360p clip per scene of job", j, listing_label(j))
        say(f"(about {CLIP_USD} USD per clip, cap {cap} USD, already spent {spent():.2f}). Nothing done (no `run`).")
        return 0
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    os.environ["PVS_LUMA_RESOLUTION"] = "360p"
    import video_generation as vg
    vg.FAL_FALLBACK_ENABLED = False          # a failed Luma call must not silently become a pricier fal.ai clip in a test
    run_id = time.strftime("%m%d_%H%M%S")
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    say(f"RUN {run_id}: {len(job_ids)} draft(s), cap {cap} USD, drafts in {JOBS_DIR}, videos in {SCRATCH}")
    report = {}
    ready = {}
    for jid in job_ids:
        if not (JOBS_DIR / jid / "job_meta.json").exists():
            say(f"{jid}: no job_meta.json in {JOBS_DIR}: skipped"); report[jid] = {"status": "missing"}; continue
        ready[jid] = jid
    from concurrent.futures import ThreadPoolExecutor
    tasks = []
    for n, jid in ready.items():
        meta = json.loads((JOBS_DIR / jid / "job_meta.json").read_text())
        for i in range(len(meta.get("scenes_config") or [])):
            tasks.append((n, jid, i))
    say(f"{len(tasks)} scene clips to generate with {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(n, jid, i, ex.submit(generate_scene, jid, i, run_dir, cap)) for n, jid, i in tasks]
        rows = [(n, f.result()) for n, jid, i, f in futs]
    for n, jid in ready.items():
        mine = [r for m, r in rows if m == n]
        oks = [r for r in mine if r["ok"] and r.get("speed")]
        med = statistics.median([r["speed"]["e_all"] for r in oks]) if oks else 0
        parts = []
        for r in mine:
            if not r["ok"]:
                continue
            r["rel"] = round(r["speed"]["e_all"] / med, 2) if med and r.get("speed") else None
            r["flag"] = bool(r["rel"] and r["rel"] >= FAST_REL)
            lab = run_dir / f"lab_{jid}_{r['scene']:03d}.mp4"
            if label_clip(Path(r["clip"]), lab, f"{n} {listing_label(jid)[:14]} scena {r['scene']} {r['category']} {r['plan'][:36]} rel {r['rel']}"):
                parts.append(lab)
        name = f"vol_{run_id}_{n}.mp4"
        if parts and concat(parts, SCRATCH / name):
            report[n] = {"status": "ok", "job": jid, "video": f"{LINK_BASE}/{name}"}
        else:
            report[n] = {"status": "no video", "job": jid}
        report[n]["scenes"] = [{k: r.get(k) for k in ("scene", "category", "ok", "plan", "rel", "flag", "why")} for r in mine]
    (OUT / f"report_{run_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    say("=" * 30, "SUMMARY", run_id, f"spent total {spent():.2f} USD")
    for n, r in report.items():
        say(f"{n}: {r['status']} {r.get('video', r.get('why', ''))}")
        for sc in r.get("scenes", []):
            say(f"    scena {sc['scene']} {sc['category']}: ok={sc['ok']} rel={sc.get('rel')} {'DA GUARDARE' if sc.get('flag') else ''} plan={sc.get('plan')} {sc.get('why') or ''}")
    say("FINISHED. Watch the videos and tell me per listing/scene what you see (hallucination, direction, speed).")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ("ids", "plan", "run"):
        print(__doc__); sys.exit(1)
    if a[0] == "ids":
        print(" ".join(parse_job_ids(Path(a[1]).read_text(errors="replace")))); sys.exit(0)

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    sys.exit(main([u.strip() for u in a[1].split(",") if u.strip()], float(opt("--cap", DEFAULT_CAP)), int(opt("--workers", "3")), a[0] == "run"))
