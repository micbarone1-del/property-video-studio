"""Alternative photo after the SECOND rejection of the same scene (point 3, Michele 2026-11-12).
Pure planning + the photo swap on disk; every outside call is injected (pick / fetch / evaluate), so it is testable with fakes.
When it applies: a scene was rejected by the clip QC with its own photo, was reworked once automatically (job['auto_reworked']),
and the reworked clip is rejected again. Instead of parking the job, the best OTHER photo of the same room (listing_scraper.pick_alternative_photo,
the shared selection step) replaces the scene's photo and the scene goes through the ONE rework runner (_run_redo) once more, with the same clip QC.
Accepted (no reject, no flag) -> the job goes on by itself. Rejected or flagged again -> the job parks for the operator, as before.
Never tried: switch off, any flagged scene in the stop, scene not rejected twice, alternative already tried for the scene (ONE per scene),
no other photo, photo not downloadable, rework budget used up. Nothing is ever deleted: the replaced files are MOVED to <job>/rejected_photos/."""
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def enabled():
    return os.getenv("PVS_AUTO_ALT_PHOTO", "0").strip().lower() in ("1", "true", "yes", "on")


def _park(job, reason):
    return {"scene_ids": [], "reason": reason}


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _park_files(job_dir: Path, sid: str):
    """Moves the scene's current photo and every file derived from it (enhanced / dewatermarked) out of the way, and copies its current clip.
    The old clip is only copied: the regeneration overwrites clips/<sid>.mp4 as in any rework. Returns the list of names parked."""
    rej = job_dir / "rejected_photos"
    rej.mkdir(exist_ok=True)
    parked = []
    img_dir = job_dir / "images"
    for ext in IMAGE_EXTS:
        f = img_dir / f"{sid}{ext}"
        if f.exists():
            t = _unique(rej / f"{sid}__old{ext}")
            shutil.move(str(f), str(t))
            parked.append(t.name)
    enh = job_dir / "enhanced"
    pat = re.compile("^" + re.escape(sid) + r"(_dewm)?_L\dU\d_enhanced\.jpg$|^" + re.escape(sid) + r"_dewatermarked\.jpg$")
    if enh.is_dir():
        for f in sorted(enh.iterdir()):
            if pat.match(f.name):
                t = _unique(rej / f"{sid}__old_{f.name}")
                shutil.move(str(f), str(t))
                parked.append(t.name)
    clip = job_dir / "clips" / f"{sid}.mp4"
    if clip.exists():
        t = _unique(rej / f"{sid}__old.mp4")
        shutil.copy2(str(clip), str(t))
        parked.append(t.name)
    return parked


def prepare(job, job_dir, rejected, flagged, deps):
    """-> {"scene_ids": [...], "reason": str}. Empty scene_ids = do not try (the caller parks the job as before).
    deps: pick(selection_report, category, exclude_urls)->{"photo": {...}|None, "reason": str}; fetch(url)->bytes|None; evaluate(job, scene_ids)->{"allowed", "reasons"}."""
    if not enabled():
        return _park(job, "switch off")
    if not rejected:
        return _park(job, "no reject")
    if flagged:
        return _park(job, "flagged scenes need the operator")
    cfg = job.get("scenes_config") or []
    auto = set(job.get("auto_reworked") or [])
    tried = job.setdefault("alt_photo", {})
    plan = []
    for i in rejected:
        sc = cfg[i] if isinstance(i, int) and 0 <= i < len(cfg) else None
        sid = (sc or {}).get("scene_id")
        if not sid:
            return _park(job, f"scene {i}: no scene_id")
        if sid not in auto:
            return _park(job, f"scene {sid}: not rejected twice yet")
        if sid in tried:
            return _park(job, f"scene {sid}: alternative photo already tried")
        if not (sc or {}).get("category"):
            return _park(job, f"scene {sid}: no category")
        plan.append((sid, sc["category"]))
    ids = [sid for sid, _ in plan]
    ev = deps.evaluate(job, ids)
    if not ev.get("allowed"):
        return _park(job, "rework budget: " + "; ".join(ev.get("reasons") or []))
    exclude = [e.get("new_url") for e in tried.values() if e.get("new_url")]
    chosen = []
    for sid, cat in plan:
        out = deps.pick(job.get("selection_report") or {}, cat, exclude)
        photo = (out or {}).get("photo")
        if not photo:
            tried[sid] = {"status": "none", "category": cat, "reason": (out or {}).get("reason"), "at": datetime.utcnow().isoformat()}
            return _park(job, f"scene {sid}: {(out or {}).get('reason')}")
        data = deps.fetch(photo["url"])
        if not data:
            tried[sid] = {"status": "none", "category": cat, "reason": "photo not downloadable", "new_url": photo["url"], "at": datetime.utcnow().isoformat()}
            return _park(job, f"scene {sid}: alternative photo not downloadable")
        exclude.append(photo["url"])
        chosen.append((sid, cat, photo, data))
    job_dir = Path(job_dir)
    (job_dir / "images").mkdir(exist_ok=True)
    for sid, cat, photo, data in chosen:
        parked = _park_files(job_dir, sid)
        (job_dir / "images" / f"{sid}.jpg").write_bytes(data)
        tried[sid] = {"status": "generating", "category": cat, "new_url": photo["url"], "rank_status": photo.get("rank_status"),
                      "feature_visible": photo.get("feature_visible"), "quality": photo.get("quality"), "parked": parked,
                      "at": datetime.utcnow().isoformat()}
    return {"scene_ids": ids, "reason": "alternative photo"}


def record_outcome(job, redone_ids, failed_ids, rejected, flagged):
    """After the QC of the clips made with an alternative photo: accepted / rejected_again / failed. Returns {scene_id: status} for the ones changed."""
    cfg = job.get("scenes_config") or []
    bad = {(cfg[i] or {}).get("scene_id") for i in list(rejected or []) + list(flagged or []) if isinstance(i, int) and 0 <= i < len(cfg)}
    changed = {}
    for sid, e in (job.get("alt_photo") or {}).items():
        if e.get("status") != "generating":
            continue
        if sid in (failed_ids or []):
            e["status"] = "failed"
        elif sid in (redone_ids or []):
            e["status"] = "rejected_again" if sid in bad else "accepted"
        else:
            continue
        e["decided_at"] = datetime.utcnow().isoformat()
        changed[sid] = e["status"]
    return changed
