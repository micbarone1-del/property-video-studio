"""health_kpi.py - the ONE place that measures disk trend, backups and the maintenance heartbeat, and that builds the "Salute del sistema" card of the operator dashboard. 2026-11-23.
Why: on 2026-11-23 the disk was at 86% with a 7 GB backup added every night; the maintenance check saw "warn" but only red (90%) sent anything, and nobody looked at the trend.
The THRESHOLDS stay in maintenance_scheduler.py (they already lived there); this module only measures. The dashboard shows the results the maintenance checks already computed
(maintenance_status.json), so there is no second calculation of the same thing. Every function here never raises."""
import json
import os
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HISTORY_DAYS = 14          # disk samples older than this are dropped
MIN_SPAN_DAYS = 2.0        # no forecast before the history covers this many days
MIN_SAMPLES = 4
MAX_SAMPLES = 800
MIN_GAP_S = 600            # at most one sample per 10 minutes
HEARTBEAT_WARN_MIN = 12    # the cron runs every 5 minutes
HEARTBEAT_RED_MIN = 20
LABELS = (("disk_usage", "Disco"), ("backup_health", "Backup"), ("service_status", "Servizio"), ("credits", "Crediti API"), ("stuck_jobs", "Job fermi"))
SHOW_DETAIL = ("credits",)  # these show the check's detail even when ok


def _data_dir() -> Path:
    return Path(os.environ.get("PVS_DATA_DIR") or BASE_DIR)


def history_file() -> Path:
    return _data_dir() / "disk_history.json"


def backup_dir() -> Path:
    return Path(os.environ.get("PVS_BACKUP_DIR") or "/var/backups/pvs_jobs")


def _load_history(path=None) -> list:
    try:
        d = json.loads(Path(path or history_file()).read_text())
        return [s for s in d if isinstance(s, dict) and "t" in s and "u" in s] if isinstance(d, list) else []
    except Exception:
        return []


def record_disk(used_bytes: int, now: float = None, path=None) -> list:
    """Adds one (time, used bytes) sample, drops old ones, returns the history. Never raises (returns what it has)."""
    now = time.time() if now is None else now
    p = Path(path or history_file())
    h = _load_history(p)
    try:
        h = [s for s in h if s["t"] >= now - HISTORY_DAYS * 86400]
        if not h or now - h[-1]["t"] >= MIN_GAP_S:
            h.append({"t": round(now), "u": int(used_bytes)})
        h = h[-MAX_SAMPLES:]
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(h))
        os.replace(tmp, p)
    except Exception:
        pass
    return h


def forecast_days(history: list, free_bytes: int, now: float = None):
    """Days until the disk is full at the growth of the last 7 days (least-squares slope, so the nightly backup sawtooth does not fool it).
    None when there is not enough history yet (< MIN_SPAN_DAYS or < MIN_SAMPLES samples) or when the disk is not growing."""
    try:
        now = time.time() if now is None else now
        w = [s for s in history if s["t"] >= now - 7 * 86400]
        if len(w) < MIN_SAMPLES or (w[-1]["t"] - w[0]["t"]) < MIN_SPAN_DAYS * 86400:
            return None
        n = len(w)
        mt = sum(s["t"] for s in w) / n
        mu = sum(s["u"] for s in w) / n
        den = sum((s["t"] - mt) ** 2 for s in w)
        if den <= 0:
            return None
        slope = sum((s["t"] - mt) * (s["u"] - mu) for s in w) / den      # bytes per second
        if slope <= 0:
            return None
        return round(free_bytes / (slope * 86400), 1)
    except Exception:
        return None


def backup_info(directory=None, now: float = None) -> dict:
    """The newest backup (a jobs_*.tar.gz file or a snap_* folder) in the backup folder: how many, how old, how big the tarballs are."""
    now = time.time() if now is None else now
    d = Path(directory or backup_dir())
    out = {"dir_exists": d.is_dir(), "count": 0, "newest_age_h": None, "newest_name": None, "tar_bytes": 0}
    try:
        if not out["dir_exists"]:
            return out
        items = list(d.glob("jobs_*.tar.gz")) + [x for x in d.glob("snap_*") if x.is_dir()]
        out["count"] = len(items)
        out["tar_bytes"] = sum(x.stat().st_size for x in d.glob("jobs_*.tar.gz"))
        if items:
            newest = max(items, key=lambda x: x.stat().st_mtime)
            out["newest_name"] = newest.name
            out["newest_age_h"] = round((now - newest.stat().st_mtime) / 3600, 1)
    except Exception:
        pass
    return out


def heartbeat_age_min(status_file=None, now: datetime = None):
    """Minutes since the maintenance run last wrote its status file (the cron writes it on every tick); None when unknown."""
    try:
        f = Path(status_file or (BASE_DIR / "maintenance_status.json"))
        ts = json.loads(f.read_text()).get("timestamp")
        return round(((now or datetime.now()) - datetime.fromisoformat(ts)).total_seconds() / 60, 1)
    except Exception:
        return None


def snapshot(status_file=None, now: datetime = None) -> dict:
    """{"rows": [{key, label, status, value}], "worst": "ok|warn|red"} for the dashboard card. Reads the maintenance results; never raises."""
    rows = []
    try:
        f = Path(status_file or (BASE_DIR / "maintenance_status.json"))
        checks = {c.get("name"): c for c in json.loads(f.read_text()).get("checks", [])}
    except Exception:
        checks = {}
    age = heartbeat_age_min(status_file, now)
    if age is None:
        rows.append({"key": "heartbeat", "label": "Manutenzione", "status": "red", "value": "nessun dato: la manutenzione non gira o non ha mai girato"})
    else:
        st = "red" if age > HEARTBEAT_RED_MIN else "warn" if age > HEARTBEAT_WARN_MIN else "ok"
        rows.append({"key": "heartbeat", "label": "Manutenzione", "status": st,
                     "value": (f"ultimo giro {round(age)} min fa" if st == "ok" else f"FERMA? ultimo giro {round(age)} min fa")})
    for key, label in LABELS:
        c = checks.get(key)
        if not c:
            rows.append({"key": key, "label": label, "status": "warn", "value": "non ancora misurato"})
            continue
        st = c.get("status") if c.get("status") in ("ok", "warn", "red") else "warn"
        val = c.get("it") or (str(c.get("detail") or "ok")[:90] if key in SHOW_DETAIL else ("ok" if st == "ok" else str(c.get("summary") or "")[:120]))
        rows.append({"key": key, "label": label, "status": st, "value": val})
    order = {"ok": 0, "warn": 1, "red": 2}
    return {"rows": rows, "worst": max((r["status"] for r in rows), key=lambda s: order[s])}
