"""Retention of old job folders (2026-11-02). ONE place for the rule, used by the cleanup in api_server (/diagnostics) AND by the check in
maintenance_scheduler, so the two can never disagree again (before: a hard-coded "7 days" lived in both).

Why it changed: every job folder with no activity for 7 days was deleted whatever the free space, and videos that could be reused later
(GIAL) vanished. Now NOTHING is deleted while the disk is below HIGH_PCT. Above it, the job folders idle for the longest time go first, one by
one, until the projected usage is back at LOW_PCT. Never touched, whatever the disk says:
  - a job with "keep": true (the operator's "tieni" button in the library)
  - a job with activity in the last MIN_AGE_DAYS days
  - a job that is running or queued
The folder _test_scratch has its own, separate cleanup (maintenance_scheduler.clean_test_scratch).
Values are PROPOSALS to revisit when the daily video volume is known; each can be changed with an environment variable without touching code.
"""
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def _num(name, default):
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)


HIGH_PCT = _num("PVS_RETENTION_HIGH_PCT", 80)       # start deleting only at or above this disk usage
LOW_PCT = _num("PVS_RETENTION_LOW_PCT", 65)         # stop when the projected usage is back at or below this
MIN_AGE_DAYS = _num("PVS_RETENTION_MIN_DAYS", 14)   # a job touched more recently than this is never deleted
BUSY_STATUSES = ("running", "queued")


def last_activity(job_dir: Path) -> datetime:
    """job_meta.json's own mtime (rewritten on every real state change); the folder's mtime when there is no meta (orphan folder)."""
    meta = Path(job_dir) / "job_meta.json"
    ts = meta.stat().st_mtime if meta.exists() else Path(job_dir).stat().st_mtime
    return datetime.utcfromtimestamp(ts)


def dir_size_bytes(job_dir: Path) -> int:
    return sum(f.stat().st_size for f in Path(job_dir).rglob("*") if f.is_file())


def disk_usage(path):
    u = shutil.disk_usage(str(path))
    return u.total, u.used


def is_protected(job_dir: Path, status=None, keep=None, now=None) -> bool:
    """True = never delete automatically. `keep` and `status` come from the in-memory job when known, else from job_meta.json."""
    now = now or datetime.utcnow()
    job_dir = Path(job_dir)
    if keep is None or status is None:
        try:
            import json
            m = json.load(open(job_dir / "job_meta.json"))
            keep = m.get("keep") if keep is None else keep
            status = m.get("status") if status is None else status
        except Exception:
            pass
    if keep:
        return True
    if status in BUSY_STATUSES:
        return True
    try:
        return last_activity(job_dir) >= now - timedelta(days=MIN_AGE_DAYS)
    except Exception:
        return True          # cannot read it: do not delete it


def select_for_eviction(jobs_dir, jobs=None, now=None, usage=None, high=None, low=None):
    """Job folder NAMES to delete now, oldest activity first. [] while the disk is below `high`.
    jobs: the in-memory JOBS dict (optional); usage: (total, used) bytes, default the real disk of jobs_dir."""
    high = HIGH_PCT if high is None else high
    low = LOW_PCT if low is None else low
    jobs_dir = Path(jobs_dir)
    now = now or datetime.utcnow()
    total, used = usage if usage else disk_usage(jobs_dir)
    if not total or used / total * 100 < high:
        return []
    cands = []
    for d in jobs_dir.iterdir():
        if not d.is_dir() or d.name == "_test_scratch":
            continue
        j = (jobs or {}).get(d.name) or {}
        if is_protected(d, status=j.get("status"), keep=j.get("keep"), now=now):
            continue
        try:
            cands.append((last_activity(d), d))
        except Exception:
            continue
    cands.sort(key=lambda t: t[0])
    chosen, projected = [], used
    for _, d in cands:
        if projected / total * 100 <= low:
            break
        chosen.append(d.name)
        projected -= dir_size_bytes(d)
    return chosen
