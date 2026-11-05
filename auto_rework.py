"""First automatic rework on a MEASURED reject (2026-11-05).
Pure planning only: decides whether the QC gate may send scenes to the ONE shared
rework runner (_run_redo) instead of pausing for the operator. It never runs anything.
Scope (deliberately narrow): only jobs whose whole stop is made of enforced
geometry rejects (qc entry standard_enforced True). Any flagged / failed / other
reject keeps the normal pause, so no pending review can be bypassed.
One automatic rework per scene (job['auto_reworked']); if the reworked clip is
still rejected the shared rework QC gate parks the job for the operator."""
import os


def enabled():
    return os.getenv("PVS_AUTO_REWORK", "0").strip().lower() in ("1", "true", "yes", "on")


def plan(job, qc_results, rejected, flagged, failed, scenes_config, evaluate=None):
    """-> {"scene_ids": [...], "indexes": [...], "reason": str}. Empty scene_ids = do not auto-rework."""
    no = lambda r: {"scene_ids": [], "indexes": [], "reason": r}
    if not enabled():
        return no("switch off")
    if not rejected:
        return no("no reject")
    if flagged or failed:
        return no("flagged/failed scenes need the operator")
    done = set(job.get("auto_reworked") or [])
    ids, idxs = [], []
    for i in rejected:
        ent = next((q for q in (qc_results or []) if q.get("scene") == i and q.get("type") == "video"), None)
        if not ent or not ent.get("standard_enforced"):
            return no(f"scene {i}: reject not from the measured rule")
        if i >= len(scenes_config or []) or not (scenes_config[i] or {}).get("scene_id"):
            return no(f"scene {i}: no scene_id")
        sid = scenes_config[i]["scene_id"]
        if sid in done:
            return no(f"scene {sid}: already auto-reworked")
        ids.append(sid)
        idxs.append(i)
    if evaluate:
        res = evaluate(job, ids)
        if not res.get("allowed"):
            return no("rework budget: " + "; ".join(res.get("reasons") or []))
    return {"scene_ids": ids, "indexes": idxs, "reason": "measured reject only"}
