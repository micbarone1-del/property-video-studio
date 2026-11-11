"""First automatic rework on a MEASURED reject (2026-11-05).
Pure planning only: decides whether the QC gate may send scenes to the ONE shared
rework runner (_run_redo) instead of pausing for the operator. It never runs anything.
Scope: every REJECTED scene (measured geometry rule OR the existing clip QC, e.g. invented structure).
Widened 2026-11-06: in production 7 of 9 rejects were confirmed by the operator's own redo (22% approved), and a rework costs ~1.1 EUR.
Flagged scenes are cleared first by auto_rework.approvable_flags (or keep the pause); failed (no clip) always keep it.
One automatic rework per scene (job['auto_reworked']); if the reworked clip is
still rejected the shared rework QC gate parks the job for the operator."""
import os
import re


def enabled():
    return os.getenv("PVS_AUTO_REWORK", "0").strip().lower() in ("1", "true", "yes", "on")


def approve_flags_enabled():
    return os.getenv("PVS_AUTO_APPROVE_FLAGS", "0").strip().lower() in ("1", "true", "yes", "on")


# 2026-11-06 (battery 360p: 3 of 5 auto-approved flags said "possible unclear human figure"): a person in a video is not a minor defect
# for an agency, so a flag whose own text speaks of a person / figure is never approved by the system, whatever the severity field says.
PERSON_RE = re.compile(r"figura|person|umano|umana|uomo|donna|bambin|people|human", re.I)


def approvable_flags(qc_results, flagged):
    """2026-11-05: flagged (not rejected) scenes the system may approve by itself: ALL of them or none.
    A flag is approvable only if its video QC says severity none/minor, no people, same space, no QC error.
    Returns the list of scene indexes (== flagged) or [] when the switch is off or any flag is not approvable."""
    if not approve_flags_enabled() or not flagged:
        return []
    for i in flagged:
        ent = next((q for q in (qc_results or []) if q.get("scene") == i and q.get("type") == "video"), None)
        if not ent or ent.get("error"):
            return []
        if str(ent.get("severity", "none")).lower() not in ("none", "minor"):
            return []
        if ent.get("people_detected") or ent.get("space_matches") is False:
            return []
        if PERSON_RE.search(" ".join(str(x) for x in (ent.get("issues") or []))):
            return []
    return list(flagged)


def review_record(qc_results, idxs):
    """What the operator sees later for auto-approved scenes."""
    out = []
    for i in idxs:
        ent = next((q for q in (qc_results or []) if q.get("scene") == i and q.get("type") == "video"), {}) or {}
        out.append({"scene": i, "severity": ent.get("severity"), "issues": list(ent.get("issues") or [])[:4]})
    return out


def plan(job, qc_results, rejected, flagged, failed, scenes_config, evaluate=None):
    """-> {"scene_ids": [...], "indexes": [...], "reason": str}. Empty scene_ids = do not auto-rework."""
    no = lambda r: {"scene_ids": [], "indexes": [], "reason": r}
    if not enabled():
        return no("switch off")
    if not rejected and not failed:
        return no("no reject")
    if flagged:
        return no("flagged scenes need the operator")
    done = set(job.get("auto_reworked") or [])
    ids, idxs = [], []
    for i in sorted(set(rejected) | set(failed or [])):
        ent = next((q for q in (qc_results or []) if q.get("scene") == i and q.get("type") == "video"), None)
        # 2026-11-11: a clip that was never generated has nothing to measure; it is redone once like a reject
        if i not in (failed or []) and (not ent or ent.get("verdict") != "reject"):
            return no(f"scene {i}: no reject entry in the clip QC")
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
