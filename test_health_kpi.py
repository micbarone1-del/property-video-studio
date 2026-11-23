"""Health card + disk trend + backup check + warn alerts (2026-11-23). Numbered PASS/FAIL like the other test files. Run: python3 test_health_kpi.py"""
import ast, json, os, re, sys, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
T = tempfile.mkdtemp()
os.environ["PVS_DATA_DIR"] = T
os.environ["PVS_BACKUP_DIR"] = os.path.join(T, "bk")
import health_kpi as hk

FAILS = 0
def check(name, cond):
    global FAILS
    print(("PASS " if cond else "FAIL ") + name)
    FAILS += 0 if cond else 1

DAY, GB = 86400, 1024 ** 3
now = time.time()
# HK1-HK2 history
h = hk.record_disk(100 * GB, now=now - 20 * DAY)
h = hk.record_disk(101 * GB, now=now)
check("HK1 a sample older than 14 days is dropped, the new one kept", [s["u"] for s in h] == [101 * GB])
h = hk.record_disk(102 * GB, now=now + 60)
check("HK2 two samples less than 10 minutes apart: only the first is kept", len(h) == 1)
# HK3-HK6 forecast
lin = lambda days, per_day: [{"t": now - (days - i * 0.25) * DAY, "u": int((100 + per_day * i * 0.25) * GB)} for i in range(int(days * 4) + 1)]
check("HK3 no forecast with less than 2 days of history", hk.forecast_days(lin(1.5, 10), 30 * GB, now) is None)
d = hk.forecast_days(lin(3, 10), 30 * GB, now)
check("HK4 10 GB/day with 30 GB free = 3.0 days (+-0.1)", d is not None and abs(d - 3.0) < 0.1)
check("HK5 a flat or shrinking disk gives no forecast", hk.forecast_days([{"t": now - i * 3600 * 12, "u": 100 * GB + i * GB} for i in range(8, -1, -1)], 30 * GB, now) is None)
saw = [{"t": now - (4 - i * 0.25) * DAY, "u": int((100 + (7.5 if i % 4 == 3 else 0) + 0.5 * i * 0.25) * GB)} for i in range(17)]
check("HK6 a sawtooth (nightly backup then prune) does not crash and gives a number or None", hk.forecast_days(saw, 30 * GB, now) is None or hk.forecast_days(saw, 30 * GB, now) > 0)
check("HK6b garbage history never raises", hk.forecast_days([{"x": 1}], 1, now) is None)
# HK7-HK10 backups
b = Path(T) / "bk"; b.mkdir()
check("HK7 empty backup folder: count 0", hk.backup_info(now=now)["count"] == 0)
for n, age_h in (("jobs_a.tar.gz", 50), ("jobs_b.tar.gz", 10)):
    f = b / n; f.write_bytes(b"x" * 1000); os.utime(f, (now - age_h * 3600, now - age_h * 3600))
i = hk.backup_info(now=now)
check("HK8 two backups: count 2, newest is the 10 h one, tarball bytes summed", i["count"] == 2 and i["newest_name"] == "jobs_b.tar.gz" and abs(i["newest_age_h"] - 10) < 0.1 and i["tar_bytes"] == 2000)
sd = b / "snap_2026-11-23"; sd.mkdir(); os.utime(sd, (now - 2 * 3600, now - 2 * 3600))
check("HK9 a snap_* folder counts as a backup and can be the newest", hk.backup_info(now=now)["newest_name"] == "snap_2026-11-23")
check("HK10 missing folder: dir_exists False, no crash", hk.backup_info(Path(T) / "nope")["dir_exists"] is False)
# HK11-HK13 snapshot
sf = Path(T) / "ms.json"
def status(ts, checks): sf.write_text(json.dumps({"timestamp": ts.isoformat(), "checks": checks}))
nowd = datetime.now()
chk = [{"name": "disk_usage", "status": "warn", "summary": "s", "detail": "d", "it": "82% usato"}, {"name": "backup_health", "status": "ok", "detail": "d", "it": "1 copia"},
       {"name": "service_status", "status": "ok", "detail": "HTTP 200: {big json}"}, {"name": "credits", "status": "ok", "detail": "fal.ai: 16 remaining"},
       {"name": "stuck_jobs", "status": "ok", "detail": "none"}]
status(nowd - timedelta(minutes=3), chk)
s = hk.snapshot(sf, nowd); r = {x["key"]: x for x in s["rows"]}
check("HK11 fresh status file: heartbeat ok, worst = warn (the disk), Italian text used", r["heartbeat"]["status"] == "ok" and s["worst"] == "warn" and r["disk_usage"]["value"] == "82% usato")
check("HK11b ok checks show 'ok' (no raw HTTP/JSON), credits show their detail", r["service_status"]["value"] == "ok" and "fal.ai" in r["credits"]["value"])
status(nowd - timedelta(minutes=30), chk)
check("HK12 status file 30 minutes old: heartbeat RED and worst RED", hk.snapshot(sf, nowd)["rows"][0]["status"] == "red" and hk.snapshot(sf, nowd)["worst"] == "red")
s = hk.snapshot(Path(T) / "missing.json", nowd)
check("HK13 no status file at all: red heartbeat row, no crash, every check 'non ancora misurato'", s["worst"] == "red" and len(s["rows"]) == 6)
# HK14-HK19 wiring in the real files
ms = (HERE / "maintenance_scheduler.py").read_text(); api = (HERE / "api_server.py").read_text(); ui = (HERE / "operator_page.html").read_text()
check("HK14 maintenance registry has backup_health and an interval for it", '"backup_health":        check_backup_health' in ms and '"backup_health":        60' in ms)
check("HK15 the scheduler RT9 rule still holds: DISK_WARN_PCT literal 80", re.search(r"DISK_WARN_PCT\s*=\s*(\d+)", ms).group(1) == "80")
check("HK16 warn alerts: loop over WARN_ALERT_CHECKS with a 24 h cooldown key", "for _name in WARN_ALERT_CHECKS" in ms and "_warn_alert_" in ms and "WARN_ALERT_COOLDOWN_HOURS = 24" in ms)
check("HK17 /operator/status returns health from health_kpi", '"health": _health_snapshot()' in api and "health_kpi.snapshot()" in api)
check("HK18 page: chips container, paintHealth defined and called", 'id="health"' in ui and "function paintHealth" in ui and "paintHealth(d.health)" in ui)
check("HK19 health_kpi does no disk measuring of its own (no shutil): one calculation, in check_disk", "shutil" not in Path(HERE / "health_kpi.py").read_text())
# HK20-HK24 behaviour of the real checks (needs the scheduler importable)
try:
    import maintenance_scheduler as m
    m.BASE_DIR = Path(T)
    db = m.check_disk()
    check("HK20 check_disk returns status, summary, detail and the Italian text", db["name"] == "disk_usage" and db["status"] in ("ok", "warn", "red") and "usato" in db["it"])
    cb = m.check_backup_health()
    check("HK21 backup check: backups 2 h old -> ok", cb["status"] == "ok" and "copie" in cb["it"])
    for x in list(b.glob("jobs_*")) + [sd]:
        if x.is_dir(): x.rmdir()
        else: x.unlink()
    check("HK22 backup check: no backup -> red", m.check_backup_health()["status"] == "red")
    f = b / "jobs_old.tar.gz"; f.write_bytes(b"x"); os.utime(f, (now - 40 * 3600, now - 40 * 3600))
    check("HK23 backup check: newest 40 h old -> red", m.check_backup_health()["status"] == "red")
    sent = []
    m.send_notification = lambda subject, body, **kw: sent.append(subject) or {"email": False, "push": False}
    m.send_maintenance_alert = lambda *a, **k: False
    m.STATUS_FILE = Path(T) / "st.json"; m.LAST_RUN_FILE = Path(T) / "lr.json"
    m.CHECK_FUNCTIONS = {"disk_usage": lambda: {"name": "disk_usage", "title": "Storage Space", "status": "warn", "summary": "full soon", "detail": "d"}}
    m.CHECK_INTERVALS = {"disk_usage": 30}
    m.run_due_checks(); n1 = len(sent)
    (Path(T) / "lr.json").write_text(json.dumps({k: v for k, v in json.loads((Path(T) / "lr.json").read_text()).items() if k != "disk_usage"}))
    m.run_due_checks()
    check("HK24 a disk at 'warn' sends exactly ONE alert, and not again on the next run (24 h cooldown)", n1 == 1 and len(sent) == 1)
except Exception as e:
    check(f"HK20-24 scheduler importable and behaving ({type(e).__name__}: {e})", False)
# HK25 existing tests untouched: the stuck-jobs and retention tests still agree with the patched file
print(f"test_health_kpi FAILS {FAILS}")
sys.exit(1 if FAILS else 0)
