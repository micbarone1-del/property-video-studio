"""operator_inbox.py - every notification the operator gets (mail + push) is also kept here, so the dashboard shows it. 2026-11-20.

ONE writer: maintenance_scheduler.send_notification calls add() for every alert (job alerts, maintenance alerts, 401 alerts), so nothing
can reach the operator by mail or push without also being on the dashboard. The file is <PVS_DATA_DIR>/operator_inbox.json (outside jobs/,
ignored by git); the web server and the cron maintenance run are different processes, so every change is read-modify-write under a file lock.

  level "action"  something the operator may have to do: shown OPEN at the top of the dashboard until "Fatto" or until it resolves by itself
  level "info"    for information only (a new job arrived): shown in a closed section below
  kind "cap_wait" resolves by itself when the job is no longer waiting for the daily cap; any other entry tied to a job resolves when that
                  job is released or rejected by the operator, or no longer exists. Entries with no job stay open until "Fatto".
Never raises: a problem here must never block a mail or a push.
"""
import fcntl
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

MAX_ENTRIES = 300
INFO_SHOWN = 30
_tlock = threading.Lock()


def _path():
    return Path(os.environ.get("PVS_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))) / "operator_inbox.json"


def _plain(text):
    t = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", t).strip()[:400]


def _locked_update(fn):
    """Run fn(entries) -> (new_entries, result) under the thread lock and the file lock; write the file atomically."""
    p = _path()
    with _tlock:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(str(p) + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                try:
                    entries = json.loads(p.read_text(encoding="utf-8"))
                    if not isinstance(entries, list):
                        entries = []
                except Exception:
                    entries = []
                entries, result = fn(entries)
                tmp = str(p) + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(entries, f, ensure_ascii=False)
                os.replace(tmp, str(p))
                return result
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)


def add(subject, text, job_id=None, level="action", kind=None):
    """Record one notification. Returns its id, or None if it could not be written (never raises)."""
    try:
        eid = uuid.uuid4().hex[:10]
        entry = {"id": eid, "at": datetime.utcnow().isoformat(timespec="seconds"), "subject": str(subject or "")[:200], "text": _plain(text),
                 "job_id": job_id, "level": "info" if level == "info" else "action", "kind": kind, "done": False}

        def fn(entries):
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:   # drop the oldest finished ones first, then the oldest of all
                keep = [e for e in entries if not e.get("done")]
                entries = (keep if len(keep) >= MAX_ENTRIES // 2 else entries)[-MAX_ENTRIES:]
            return entries, eid
        return _locked_update(fn)
    except Exception:
        return None


def is_resolved(entry, job):
    """True when the thing the entry was about no longer needs the operator. job: the job dict, or None if it no longer exists."""
    if not entry.get("job_id"):
        return False
    if job is None:
        return True
    if entry.get("kind") == "cap_wait":
        return job.get("status") != "draft" or (job.get("auto_start") or {}).get("state") != "waiting"
    return bool(job.get("released")) or job.get("failure_code") == "rejected_by_operator"


def snapshot(jobs):
    """For the dashboard: {"actions": open items, newest first, "info": last INFO_SHOWN not yet closed, newest first}. Never raises."""
    try:
        entries = json.loads(_path().read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            entries = []
    except Exception:
        entries = []
    actions, info = [], []
    for e in reversed(entries):
        if not isinstance(e, dict) or e.get("done"):
            continue
        jid = e.get("job_id")
        j = (jobs or {}).get(jid) if jid else None
        row = {k: e.get(k) for k in ("id", "at", "subject", "text", "job_id", "level", "kind")}
        row["job_name"] = (j or {}).get("property_name") if j else None
        if e.get("level") == "info":
            if len(info) < INFO_SHOWN:
                info.append(row)
        elif not is_resolved(e, j):
            actions.append(row)
    return {"actions": actions, "info": info}


def mark_done(entry_id):
    def fn(entries):
        hit = False
        for e in entries:
            if isinstance(e, dict) and e.get("id") == entry_id and not e.get("done"):
                e["done"] = True
                e["done_at"] = datetime.utcnow().isoformat(timespec="seconds")
                hit = True
        return entries, hit
    try:
        return _locked_update(fn)
    except Exception:
        return False


def mark_all_info_done():
    def fn(entries):
        n = 0
        for e in entries:
            if isinstance(e, dict) and e.get("level") == "info" and not e.get("done"):
                e["done"] = True
                e["done_at"] = datetime.utcnow().isoformat(timespec="seconds")
                n += 1
        return entries, n
    try:
        return _locked_update(fn)
    except Exception:
        return 0
