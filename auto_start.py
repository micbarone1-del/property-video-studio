"""Automatic start of partner drafts (2026-11-06). Pure decision logic only: it never starts anything itself.
A draft (source relinx, status draft) is started by the system when ALL of these hold:
  1. the draft passes draft_check (the ONE draft criterion also used by the pilot tests): no FAIL;
  2. fewer than MAX_ACTIVE jobs are generating;
  3. money spent in the last 24 h + the estimate for this video stays under the daily cap.
Anything else: refused (operator told once, job stays draft) or waiting (re-evaluated later). Switch PVS_AUTO_START, default off."""
import os
from datetime import datetime, timedelta

EST_VIDEO_EUR = 8.7          # measured average per video (video 6.62 + Claude + infrastructure)
DEFAULT_CAP_EUR = 30.0
DEFAULT_MAX_ACTIVE = 2


def enabled():
    return os.getenv("PVS_AUTO_START", "0").strip().lower() in ("1", "true", "yes", "on")


def _num(name, default):
    try:
        return float(os.getenv(name, "").strip())
    except ValueError:
        return default


def cap_eur():
    return _num("PVS_AUTO_START_CAP_EUR", DEFAULT_CAP_EUR)


def max_active():
    return int(_num("PVS_AUTO_START_MAX_ACTIVE", DEFAULT_MAX_ACTIVE))


def not_before():
    """Optional PVS_AUTO_START_NOT_BEFORE (ISO time): drafts created BEFORE it are never auto-started (drafts left over from earlier tests)."""
    return os.getenv("PVS_AUTO_START_NOT_BEFORE", "").strip()


def job_cost_eur(job):
    c = job.get("cost_actual")
    if isinstance(c, dict) and isinstance(c.get("grand_total_eur"), (int, float)):
        return float(c["grand_total_eur"])
    return None


def spent_24h(jobs, now, est=EST_VIDEO_EUR):
    """Money committed in the last 24 h: the real cost where known, the estimate for generating jobs without one. Drafts, failed and
    interrupted jobs count only what they really cost."""
    cutoff = now - timedelta(hours=24)
    total = 0.0
    for j in jobs.values():
        try:
            created = datetime.fromisoformat(j.get("created_at") or "")
        except ValueError:
            continue
        if created < cutoff:
            continue
        real = job_cost_eur(j)
        if real is not None:
            total += real
        elif j.get("status") in ("running", "queued") and (j.get("auto_start") or {}).get("state") == "started":
            total += est
        elif j.get("status") in ("running", "queued", "awaiting_approval", "done"):
            total += est
    return total


def active_count(jobs):
    """Jobs that are generating now. A partner job still 'queued' while its draft is being built is NOT generating."""
    n = 0
    for j in jobs.values():
        if j.get("status") == "running":
            n += 1
        elif j.get("status") == "queued" and (j.get("auto_start") or {}).get("state") == "started":
            n += 1
    return n


def decide(jobs, now, check, cap=None, max_act=None, est=EST_VIDEO_EUR):
    """jobs: {job_id: job dict}; check(job_id) -> [(level, id, message)] (draft_check results).
    Returns a list of {"job_id", "action": "start" | "refuse" | "wait", "reason", "checks"?}, oldest draft first."""
    cap = cap_eur() if cap is None else cap
    max_act = max_active() if max_act is None else max_act
    spent = spent_24h(jobs, now, est)
    active = active_count(jobs)
    nb = not_before()
    cands = sorted(((jid, j) for jid, j in jobs.items()
                    if j.get("source") == "relinx" and j.get("status") == "draft"
                    and not (nb and (j.get("created_at") or "") < nb)
                    and (j.get("auto_start") or {}).get("state") not in ("refused", "started")),
                   key=lambda kv: kv[1].get("created_at") or "")
    out = []
    for jid, j in cands:
        results = check(jid)
        fails = [f"{i}: {m}" for lvl, i, m in results if lvl == "FAIL"]
        if fails:
            out.append({"job_id": jid, "action": "refuse", "reason": "; ".join(fails)[:400]})
            continue
        if active >= max_act:
            out.append({"job_id": jid, "action": "wait", "reason": f"{active} jobs already generating (limit {max_act})"})
            continue
        if spent + est > cap:
            out.append({"job_id": jid, "action": "wait", "reason": f"daily cap: {spent:.1f} EUR committed + {est:.1f} > {cap:.0f} EUR"})
            continue
        out.append({"job_id": jid, "action": "start", "reason": "draft ok, within limits"})
        active += 1
        spent += est
    return out
