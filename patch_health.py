"""patch_health.py - applies the 2026-11-23 health-card change. Every anchor must occur EXACTLY once or nothing is written. Run once; a second run refuses (marker check)."""
import sys
from pathlib import Path

def edit(path, pairs, marker):
    p = Path(path)
    s = p.read_text()
    if marker in s:
        print(f"SKIP {path}: already patched"); return
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f"FAIL {path}: anchor found {n} times: {old[:60]!r}"); sys.exit(1)
        s = s.replace(old, new)
    p.write_text(s)
    print(f"OK   {path}")

edit("maintenance_scheduler.py", [
 ("import credit_monitor\n", "import credit_monitor\nimport health_kpi\n"),
 ("DISK_RED_PCT              = 90\n", """DISK_RED_PCT              = 90
DISK_FORECAST_WARN_DAYS   = 14   # 2026-11-23: days until full at the recent growth; below this = warn, below RED = red (even when the % looks low)
DISK_FORECAST_RED_DAYS    = 5
BACKUP_STALE_HOURS        = 30   # the backup runs nightly; older than this = red
BACKUP_SHARE_WARN         = 0.40 # the backup tarballs use more than this share of the disk = warn
WARN_ALERT_CHECKS         = ("disk_usage", "backup_health")   # these also send ONE alert per day at "warn" (the generic alert only fires at red)
WARN_ALERT_COOLDOWN_HOURS = 24
"""),
 ('    "disk_usage":           30,\n', '    "disk_usage":           30,\n    "backup_health":        60,\n'),
 ('''def check_disk() -> dict:
    total, used, free = shutil.disk_usage(BASE_DIR)
    pct = round(used / total * 100, 1)
    free_gb = free // (1024**3)
    status = "red" if pct >= DISK_RED_PCT else "warn" if pct >= DISK_WARN_PCT else "ok"
    if status == "ok":
        summary = f"Plenty of storage space available ({free_gb} GB free)."
    elif status == "warn":
        summary = f"Storage is getting full ({pct}% used, {free_gb} GB free) — worth keeping an eye on."
    else:
        summary = f"Storage is almost full ({pct}% used, only {free_gb} GB free) — action needed soon."
    return {"name": "disk_usage", "title": "Storage Space", "status": status,
            "summary": summary, "detail": f"{pct}% used ({free_gb} GB free)"}
''', '''def check_disk() -> dict:
    total, used, free = shutil.disk_usage(BASE_DIR)
    pct = round(used / total * 100, 1)
    free_gb = free // (1024**3)
    status = "red" if pct >= DISK_RED_PCT else "warn" if pct >= DISK_WARN_PCT else "ok"
    days = health_kpi.forecast_days(health_kpi.record_disk(used), free)   # 2026-11-23: the trend, not only the level
    if days is not None and days < DISK_FORECAST_RED_DAYS:
        status = "red"
    elif days is not None and days < DISK_FORECAST_WARN_DAYS and status == "ok":
        status = "warn"
    trend = f" At the recent growth it is full in about {days:g} days." if days is not None and days < DISK_FORECAST_WARN_DAYS else ""
    if status == "ok":
        summary = f"Plenty of storage space available ({free_gb} GB free)."
    elif status == "warn":
        summary = f"Storage is getting full ({pct}% used, {free_gb} GB free) — worth keeping an eye on.{trend}"
    else:
        summary = f"Storage is almost full ({pct}% used, only {free_gb} GB free) — action needed soon.{trend}"
    it = f"{pct:g}% usato - {free_gb} GB liberi" + (f" - pieno tra circa {days:g} giorni" if days is not None else " - previsione in raccolta (servono 2 giorni di dati)")
    return {"name": "disk_usage", "title": "Storage Space", "status": status,
            "summary": summary, "detail": f"{pct}% used ({free_gb} GB free)", "it": it}


def check_backup_health() -> dict:
    """2026-11-23: is the nightly backup there, recent, and not eating the disk? (On 2026-11-23 the backups were 141 of the 162 GB in use.)"""
    info = health_kpi.backup_info()
    total = shutil.disk_usage(BASE_DIR).total
    base = {"name": "backup_health", "title": "Backups"}
    if not info["dir_exists"] or info["count"] == 0:
        return {**base, "status": "red", "summary": "No backup found — the nightly backup may not be running.", "detail": "no backup", "it": "nessun backup trovato"}
    gb = round(info["tar_bytes"] / (1024**3))
    detail = f"{info['count']} backups, newest {info['newest_age_h']:g} h old, tarballs {gb} GB"
    it = f"{info['count']} copie - l'ultima di {info['newest_age_h']:g} ore fa - {gb} GB"
    if info["newest_age_h"] > BACKUP_STALE_HOURS:
        return {**base, "status": "red", "summary": f"The newest backup is {info['newest_age_h']:g} hours old — the nightly backup stopped.", "detail": detail, "it": it}
    if info["tar_bytes"] / total > BACKUP_SHARE_WARN:
        return {**base, "status": "warn", "summary": f"Backups use {round(info['tar_bytes'] / total * 100)}% of the disk — shorten the retention or make them incremental.", "detail": detail, "it": it}
    return {**base, "status": "ok", "summary": "Backups are recent.", "detail": detail, "it": it}
'''),
 ('''    "disk_usage":           check_disk,
''', '''    "disk_usage":           check_disk,
    "backup_health":        check_backup_health,
'''),
 ('''# ── Registry — check name -> function ───''', '''def _warn_alert_on_cooldown(last_run: dict, name: str) -> bool:
    ts = last_run.get("_warn_alert_" + name)
    try:
        return bool(ts) and datetime.now() - datetime.fromisoformat(ts) < timedelta(hours=WARN_ALERT_COOLDOWN_HOURS)
    except Exception:
        return False


# ── Registry — check name -> function ───'''),
 ('''    _save_last_run(last_run)
    log.info(f"[Maintenance] Tick complete.''', '''    for _name in WARN_ALERT_CHECKS:   # 2026-11-23: disk and backups also alert at "warn", once a day each (the red alert above fires only at red)
        _c = results.get(_name) or {}
        if _c.get("status") == "warn" and not _warn_alert_on_cooldown(last_run, _name):
            _t = _c.get("title", _name)
            send_notification(f"Property Video Studio — {_t}", f"<h3>{_t}</h3><p>{_c.get('summary', '')}</p><p>{_c.get('detail', '')}</p>",
                              push_message=f"{_t}: {_c.get('summary', '')}", priority="default", tags=["warning"], level="action")
            last_run["_warn_alert_" + _name] = datetime.now().isoformat()   # set even if mail/push failed: the dashboard inbox already has it, no repeat every 5 minutes

    _save_last_run(last_run)
    log.info(f"[Maintenance] Tick complete.'''),
], "import health_kpi")

edit("api_server.py", [
 ('"inbox": _operator_inbox_snapshot(), "jobs": rows[:(300 if (q or "").strip() else 80)]}',
  '"inbox": _operator_inbox_snapshot(), "health": _health_snapshot(), "jobs": rows[:(300 if (q or "").strip() else 80)]}'),
 ('@app.post("/operator/inbox/{entry_id}/done")', '''def _health_snapshot():
    """2026-11-23: the "Salute del sistema" card: the results of the maintenance checks plus the maintenance heartbeat (health_kpi)."""
    try:
        import health_kpi
        return health_kpi.snapshot()
    except Exception as e:
        log.warning(f"[Health] snapshot failed (non-fatal): {e}")
        return {"rows": [], "worst": "warn"}


@app.post("/operator/inbox/{entry_id}/done")'''),
], "_health_snapshot")

edit("operator_page.html", [
 ("  .todo .it .t { flex:1; min-width:220px; font-size:14px; }\n", """  .todo .it .t { flex:1; min-width:220px; font-size:14px; }
  .hl { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 12px; }
  .hl .h { border:1px solid var(--line); background:var(--card); border-radius:8px; padding:5px 9px; font-size:13px; border-left-width:5px; }
  .hl .h.ok { border-left-color:var(--ok); } .hl .h.warn { border-left-color:var(--warn); } .hl .h.red { border-left-color:var(--bad); font-weight:600; }
"""),
 ('  <div id="inbox"></div>\n', '  <div id="inbox"></div>\n  <div class="hl" id="health"></div>\n'),
 ("let FILTER = ''; let Q = '';", """function paintHealth(h) {   // 2026-11-23: system health chips (disk, backups, maintenance heartbeat, service, credits, stuck jobs)
  const rows = (h && h.rows) || [];
  document.getElementById('health').innerHTML = rows.map(r => '<span class="h ' + esc(r.status) + '" title="' + esc(r.status) + '"><b>' + esc(r.label) + '</b>: ' + esc(r.value) + '</span>').join('');
}
let FILTER = ''; let Q = '';"""),
 ("    paintInbox(d.inbox);\n", "    paintInbox(d.inbox);\n    paintHealth(d.health);\n"),
], "paintHealth")

p = Path(".gitignore"); s = p.read_text()
if "disk_history.json" not in s:
    p.write_text(s.rstrip("\n") + "\ndisk_history.json\ndisk_history.json.tmp\n"); print("OK   .gitignore")
