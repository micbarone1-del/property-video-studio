"""status_log.py - 2026-11-24 (KPI dashboard): the moment of every job status change, kept INSIDE the job record.
ONE function, called from the single place that saves a job (api_server._save_job). It only WRITES two extra keys
("status_log": [{"s": status, "t": iso time}], "status_last") and never reads them to decide anything.
Old jobs (no status_last): the current status is recorded as "already known" WITHOUT a time, so an old job never gets a made-up
time; only the changes after the deploy are logged. A job created within NEW_JOB_SECS gets its first status logged with the time."""
from datetime import datetime

NEW_JOB_SECS = 120
MAX_ENTRIES = 40


def note_status(job: dict, now: datetime = None) -> bool:
    """Returns True when the job record was changed (nothing is raised: a failure here must never block saving the job)."""
    try:
        st = job.get("status")
        if not st:
            return False
        now = now or datetime.utcnow()
        last = job.get("status_last")
        if last == st:
            return False
        log = job.setdefault("status_log", [])
        if last is None and not log:
            try:
                age = (now - datetime.fromisoformat(job.get("created_at") or "")).total_seconds()
            except ValueError:
                age = None
            if age is None or age > NEW_JOB_SECS:
                job["status_last"] = st      # an old job: current status known, its time is not
                return True
        log.append({"s": st, "t": now.isoformat()})
        del log[:-MAX_ENTRIES]
        job["status_last"] = st
        return True
    except Exception:
        return False


def first_time(job: dict, *statuses):
    """The time (iso) of the FIRST entry whose status is one of `statuses`, or None."""
    for e in job.get("status_log") or []:
        if e.get("s") in statuses:
            return e.get("t")
    return None


def last_time(job: dict, *statuses):
    for e in reversed(job.get("status_log") or []):
        if e.get("s") in statuses:
            return e.get("t")
    return None
