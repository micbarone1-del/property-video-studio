"""Rework caps, operator escalation and interrupted-rework marker.

2026-10-09 (task 4, stage 4). Pure functions on the job dict so they can be
tested without the server. api_server.py and job_recovery.py both use this
module; no limit or rule is re-implemented anywhere else.

Limits (env vars, read at call time, so a restart is enough to change them):
  PVS_REWORK_MAX_PER_SCENE  default 2  - times the same scene may be regenerated
  PVS_REWORK_MAX_ROUNDS     default 3  - rework rounds (batches) per job
  PVS_REWORK_MAX_COST_EUR   default 0  - 0 = off; total rework spend per job
A limit <= 0 switches that limit off.
"""
import os
from datetime import datetime


def _env_num(name, default, cast):
    try:
        return cast(os.environ.get(name, default))
    except (TypeError, ValueError):
        return cast(default)


def limits():
    return {
        "per_scene": _env_num("PVS_REWORK_MAX_PER_SCENE", 2, int),
        "rounds":    _env_num("PVS_REWORK_MAX_ROUNDS", 3, int),
        "cost_eur":  _env_num("PVS_REWORK_MAX_COST_EUR", 0, float),
    }


def spent_eur(job):
    total = 0.0
    for r in job.get("reworks") or []:
        if isinstance(r, dict):
            try:
                total += float(r.get("total_eur") or 0)
            except (TypeError, ValueError):
                pass
    return total


def evaluate(job, scene_ids):
    """Decides whether a rework of scene_ids may start. Never mutates job."""
    lim = limits()
    counts = job.get("rework_counts") or {}
    reasons, blocked = [], []
    if lim["per_scene"] > 0:
        blocked = [s for s in scene_ids if int(counts.get(s, 0)) >= lim["per_scene"]]
        if blocked:
            reasons.append(f"scene {', '.join(blocked)} gia' rifatte {lim['per_scene']} volte")
    if lim["rounds"] > 0 and int(job.get("rework_rounds", 0)) >= lim["rounds"]:
        reasons.append(f"gia' {lim['rounds']} cicli di rework su questo job")
    if lim["cost_eur"] > 0 and spent_eur(job) >= lim["cost_eur"]:
        reasons.append(f"spesa rework {spent_eur(job):.2f} EUR >= tetto {lim['cost_eur']:.2f} EUR")
    return {"allowed": not reasons, "reasons": reasons, "blocked_scene_ids": blocked}


def count(job, scene_ids):
    """Registers one rework round. Called when the rework actually starts."""
    counts = job.setdefault("rework_counts", {})
    for s in scene_ids:
        counts[s] = int(counts.get(s, 0)) + 1
    job["rework_rounds"] = int(job.get("rework_rounds", 0)) + 1


def begin(job, scene_ids, kind):
    job["rework_in_progress"] = {
        "scene_ids": list(scene_ids), "kind": kind,
        "started_at": datetime.utcnow().isoformat(),
    }


def end(job):
    """Clears the in-progress marker. True if there was one (caller saves)."""
    if not job:
        return False
    return job.pop("rework_in_progress", None) is not None


def flag(job, reason, kind):
    """Sets needs_operator. True only the FIRST time (caller notifies once)."""
    if job.get("needs_operator"):
        return False
    job["needs_operator"] = {"reason": reason, "kind": kind,
                             "since": datetime.utcnow().isoformat()}
    return True


def reset_budget(job, note=""):
    """Operator decision: start over with a fresh budget and clear the flag."""
    job.setdefault("rework_budget_resets", []).append({
        "at": datetime.utcnow().isoformat(), "note": note,
        "counts_before": dict(job.get("rework_counts") or {}),
        "rounds_before": int(job.get("rework_rounds", 0)),
    })
    job["rework_counts"] = {}
    job["rework_rounds"] = 0
    job.pop("needs_operator", None)
    job.pop("rework_failed_scenes", None)


def recovery_mark(job):
    """For startup recovery. If a rework was interrupted, converts the marker
    into rework_incomplete + needs_operator, gives the interrupted round back
    (it did not complete, it must not eat the budget) and returns the scene
    ids; otherwise returns None."""
    m = job.pop("rework_in_progress", None)
    if not m:
        return None
    ids = list(m.get("scene_ids") or [])
    job["rework_incomplete"] = m
    counts = job.get("rework_counts") or {}
    for s in ids:
        if int(counts.get(s, 0)) > 0:
            counts[s] = int(counts[s]) - 1
    if int(job.get("rework_rounds", 0)) > 0:
        job["rework_rounds"] = int(job["rework_rounds"]) - 1
    flag(job, f"Rework interrotto dal riavvio (scene: {', '.join(ids) or '?'}). "
              "Il video mostrato e' la versione precedente.", "rework_interrupted")
    return ids
