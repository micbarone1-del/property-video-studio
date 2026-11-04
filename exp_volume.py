"""exp_volume.py - volume check of the FINAL Luma prompt configuration on NEW listings, 360p draft tier (2026-11-04, Michele: "Facciamo volume", "Vai veloce con batch").

What it does (unattended; run inside `screen`; nothing under jobs/ is ever deleted):
  1. For every listing URL: creates a DRAFT job in the production app (POST /jobs/from-url, the same call the UI makes, under the GIAL agency) and waits until the
     draft is ready. A listing the app refuses (scope filter) is reported with the app's own reason and skipped. The app allows 5 new jobs per hour: on 429 it waits.
  2. For every scene of every draft: calls the REAL production function video_generation.generate_video_single (director -> description -> prompt assembly -> Luma),
     with the production arguments of that scene, the only differences being PVS_LUMA_RESOLUTION=360p (about 0.06 USD per clip) and the ORIGINAL photo of the
     scene (the draft has no lighting-corrected copy yet). So the prompt is exactly what production would send with the current defaults (B, N, N1).
  3. Measures the camera speed of each clip (clip_speed_probe), flags the ones much faster than the rest of the SAME listing (PROVISIONAL threshold, calibrated
     at 360p only), and writes one video per listing (clips in scene order, label with listing/scene/plan) into jobs/_test_scratch/ so it can be watched at
     http://<server>:8000/test-scratch/<file>.
Own spend cap (every STARTED clip counts, failed ones too); no generation above it.

  python3 exp_volume.py plan URL1,URL2,...      free: lists what would happen
  python3 exp_volume.py run  URL1,URL2,... [--cap 6] [--agency ag_xxx] [--workers 3]
"""
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS_DIR = Path(os.environ.get("PVS_JOBS_DIR") or (HERE / "jobs"))
SCRATCH = JOBS_DIR / "_test_scratch"
OUT = SCRATCH / "volume"
SPEND = OUT / "spend.json"
CLIP_USD = 0.06
DEFAULT_CAP = 6.0
DRAFT_WAIT_SECS = 20 * 60
RATE_WAIT_SECS = 600
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


def listing_number(url: str) -> str:
    import re
    m = re.search(r"-(\d{3,5})/?$", url.rstrip("/") + "/") or re.search(r"(\d{3,5})/?$", url)
    return m.group(1) if m else "x"


def create_draft(s, base, url, agency, attempts=6):
    """-> (job_id or None, why). Waits on 429 (5 new jobs per hour)."""
    for n in range(attempts):
        r = s.post(f"{base}/jobs/from-url", data={"url": url, "agency_id": agency or "", "model_tier": "luma", "property_name": "", "voice_id": ""}, timeout=60)
        if r.status_code == 429:
            say(f"{url[-30:]}: 429 (limit of new jobs per hour), waiting {RATE_WAIT_SECS // 60} min")
            time.sleep(RATE_WAIT_SECS)
            continue
        if r.status_code != 200:
            return None, f"create refused {r.status_code} {r.text[:200]}"
        return r.json()["job_id"], "created"
    return None, "still rate-limited after waiting"


def wait_draft(s, base, jid, max_wait=DRAFT_WAIT_SECS):
    """-> (ok, status, message)."""
    waited = 0
    while waited < max_wait:
        try:
            j = s.get(f"{base}/jobs/{jid}", timeout=30).json()
        except Exception as e:
            j = {"status": "preparing", "message": f"read failed {e}"}
        st = j.get("status")
        if st == "draft":
            return True, st, str(j.get("message") or "")
        if st != "preparing":
            return False, st, str(j.get("message") or j.get("error") or j)[:300]
        time.sleep(20); waited += 20
    return False, "timeout", "the draft was not ready in time"


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
    safe = text.replace(":", " ").replace("'", "").replace("%", "")
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


def main(urls, cap, agency, workers, go):
    if not go:
        for u in urls:
            say("would create a draft for", u)
        say(f"then one 360p clip per scene (about {CLIP_USD} USD each, cap {cap} USD, already spent {spent():.2f}). Nothing done (no `run`).")
        return 0
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    os.environ["PVS_LUMA_RESOLUTION"] = "360p"
    import gial_start
    import video_generation as vg
    vg.FAL_FALLBACK_ENABLED = False          # a failed Luma call must not silently become a pricier fal.ai clip in a test
    s, base = gial_start.session(), gial_start.BASE
    run_id = time.strftime("%m%d_%H%M%S")
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    say(f"RUN {run_id}: {len(urls)} listing(s), cap {cap} USD")
    jobs, report = {}, {}
    for u in urls:
        n = listing_number(u)
        jid, why = create_draft(s, base, u, agency)
        if not jid:
            say(f"{n}: not created - {why}"); report[n] = {"status": "not created", "why": why}; continue
        jobs[n] = jid
        say(f"{n}: draft requested (job {jid})")
    ready = {}
    for n, jid in jobs.items():
        ok, st, msg = wait_draft(s, base, jid)
        if ok:
            ready[n] = jid; say(f"{n}: draft ready (job {jid})")
        else:
            say(f"{n}: NOT a draft - {st}: {msg}"); report[n] = {"status": st, "why": msg, "job": jid}
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
            if label_clip(Path(r["clip"]), lab, f"{n} scena {r['scene']} {r['category']} {r['plan'][:40]} rel {r['rel']}"):
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
    if len(a) < 2 or a[0] not in ("plan", "run"):
        print(__doc__); sys.exit(1)

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    sys.exit(main([u.strip() for u in a[1].split(",") if u.strip()], float(opt("--cap", DEFAULT_CAP)), opt("--agency", "ag_abea5414"), int(opt("--workers", "3")), a[0] == "run"))
