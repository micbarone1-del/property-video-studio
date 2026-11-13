"""release_rule.py - ONE rule for 'a finished Relinx job with nothing left for the operator to look at' (2026-11-13).
Used by the automatic release (release mode auto) AND by the 'ready to release' notice (release mode manual), so the two can never disagree.
Pure functions, no I/O: tested without the server."""


def _stops(j) -> bool:
    aw = j.get("awaiting_scenes")
    if isinstance(aw, dict):
        return any(aw.get(k) for k in ("rejected", "flagged", "failed"))
    return bool(aw)


def releasable(j) -> bool:
    return bool(j.get("source") == "relinx" and j.get("status") == "done" and not j.get("released")
                and not j.get("needs_operator") and not j.get("delivery_blocked") and not _stops(j))


def new_notices(jobs: dict, notified: set, baseline: bool) -> list:
    """Job ids to tell the operator about now. baseline=True (first look after a server start): every job that is ALREADY releasable is remembered
    silently, so a restart never floods the operator with old finished jobs. Later: each newly releasable job is reported once."""
    out = []
    for jid, j in list(jobs.items()):
        if jid in notified or not releasable(j):
            continue
        notified.add(jid)
        if not baseline:
            out.append(jid)
    return out
