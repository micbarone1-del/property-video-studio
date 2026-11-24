"""2026-11-24: KPI dashboard data (status_log.py + kpi_stats.py). Pure: no server, no network."""
import os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status_log as sl, kpi_stats as ks
FAILS = 0
def check(name, cond):
    global FAILS
    print(("PASS " if cond else "FAIL ") + name); FAILS += 0 if cond else 1
now = datetime(2026, 11, 24, 12, 0, 0)
iso = lambda dt: dt.isoformat()
# K1-K5 status_log
j = {"status": "draft", "created_at": iso(now - timedelta(seconds=10))}
check("K1 a new job (created seconds ago): its first status is logged with a time", sl.note_status(j, now) and j["status_log"][0]["s"] == "draft")
check("K2 same status again: nothing changes", sl.note_status(j, now) is False and len(j["status_log"]) == 1)
j["status"] = "queued"; sl.note_status(j, now + timedelta(minutes=1)); j["status"] = "running"; sl.note_status(j, now + timedelta(minutes=2)); j["status"] = "done"; sl.note_status(j, now + timedelta(minutes=9))
check("K3 the changes are logged in order with their times", [e["s"] for e in j["status_log"]] == ["draft", "queued", "running", "done"] and sl.last_time(j, "done") == iso(now + timedelta(minutes=9)))
old = {"status": "done", "created_at": iso(now - timedelta(days=3))}
sl.note_status(old, now)
check("K4 an OLD job gets no made-up time: status known, log empty", old.get("status_last") == "done" and old.get("status_log") == [])
check("K5 garbage never raises", sl.note_status({}, now) is False and sl.note_status({"status": "x", "created_at": "zzz"}, now) in (True, False))
# build a small world
def job(jid, status, mins_ago, gen=None, cost=None, rework=False, created_days_ago=None, logged=True):
    done_at = now - timedelta(minutes=mins_ago)
    d = {"status": status, "property_name": "P" + jid, "created_at": iso(done_at - timedelta(minutes=30) if created_days_ago is None else now - timedelta(days=created_days_ago))}
    if logged:
        d["status_log"] = [{"s": "queued", "t": iso(done_at - timedelta(minutes=gen or 5))}, {"s": status, "t": iso(done_at)}]
    if cost is not None:
        d["cost_actual"] = {"grand_total_eur": cost}
    if rework:
        d["auto_reworked"] = [1]
    return d
jobs = {"a": job("a", "done", 30, gen=7, cost=10.0), "b": job("b", "done", 90, gen=12, cost=14.0, rework=True), "c": job("c", "failed", 45),
        "d": job("d", "done", 60 * 30, gen=5, cost=8.0), "old": job("old", "done", 0, created_days_ago=3, logged=False, cost=11.0), "x": job("x", "draft", 5)}
r = ks.build(jobs, [], now, "24h"); T = r["tiles"]
check("K6 24h: 24 hourly points per tile", all(len(t["points"]) == 24 for t in T.values()))
check("K7 completed in 24h = a and b (d is 30 h old, the old job without a log falls on its creation day, outside 24h)", T["completed"]["total"] == 2)
check("K8 failed = 1 and the success rate is told", T["failed"]["total"] == 1 and "67%" in T["failed"]["detail"])
check("K9 generation time = average of 7 and 12 = 9.5 min, max 12", T["gen_time"]["total"] == 9.5 and "max 12" in T["gen_time"]["detail"])
check("K10 average cost = 12.0 EUR", T["cost_avg"]["total"] == 12.0)
check("K11 rework = 50% (1 of 2)", T["rework_pct"]["total"] == 50.0)
r7 = ks.build(jobs, [], now, "7d"); check("K12 7d: 28 points; counts a, b, d and the old job (no log, created 3 days ago) = 4", len(r7["tiles"]["completed"]["points"]) == 28 and r7["tiles"]["completed"]["total"] == 4)
r30 = ks.build(jobs, [], now, "30d"); check("K13 30d: 30 points; the old job (no log) is counted by its creation day and flagged approx", len(r30["tiles"]["completed"]["points"]) == 30 and r30["tiles"]["completed"]["total"] == 4 and r30["approx"] is True)
check("K14 an unknown window falls back to 24h", ks.build(jobs, [], now, "zz")["window"] == "24h")
smp = [{"t": (now - timedelta(hours=h)).timestamp(), "u": 1, "p": 40.0 + h, "m": 20.0, "s": (1 if h == 0 else 0)} for h in (5, 3, 1, 0)]
rs = ks.build(jobs, smp, now, "24h")["tiles"]
check("K15 stuck jobs: current = last sample, series from samples", rs["stuck"]["total"] == 1 and sum(1 for p in rs["stuck"]["points"] if p["v"] is not None) >= 3)
check("K16 health: disk and memory series, current values", rs["health"]["total"] == 40.0 and rs["health"]["total2"] == 20.0 and len(rs["health"]["points2"]) == 24)
check("K17 no samples: tiles say so, no crash", ks.build(jobs, [], now, "24h")["tiles"]["health"]["total"] is None)
L = ks.list_items(jobs, "completed", now, 2)
check("K18 completed list: newest first, limited to n", [x["job_id"] for x in L] == ["a", "b"])
check("K19 cost list: only jobs with a known cost", {x["job_id"] for x in ks.list_items(jobs, "cost", now, 20)} == {"a", "b", "d", "old"})
check("K20 rework list: only jobs with rework", [x["job_id"] for x in ks.list_items(jobs, "rework", now)] == ["b"])
check("K21 generation-time list: slowest first", [x["job_id"] for x in ks.list_items(jobs, "gen_time", now)][:2] == ["b", "a"])
check("K22 failed list carries the reason", ks.list_items(jobs, "failed", now)[0]["job_id"] == "c")
api = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_server.py"), encoding="utf-8").read()
save = api[api.index("def _save_job("):api.index("def _load_jobs_from_disk")]
check("K23 the ONE place that saves a job logs the status change, before writing the file", "status_log.note_status(job)" in save and save.index("note_status") < save.index("_atomic_write_json"))
check("K24 the two KPI endpoints exist", '@app.get("/operator/kpi")' in api and '@app.get("/operator/kpi/list")' in api)
print("test_kpi_stats FAILS", FAILS); sys.exit(1 if FAILS else 0)
