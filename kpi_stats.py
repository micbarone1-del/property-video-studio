"""kpi_stats.py - 2026-11-24 (KPI dashboard). PURE: jobs dict + health samples + a clock in, series and lists out (no server, no disk).
Windows: 24h = 24 hourly buckets, 7d = 28 buckets of 6 h, 30d = 30 daily buckets, the last one ending NOW.
Time of a job event: the logged status change (status_log.py) when it exists, otherwise the creation time of the job, marked approx=True
(jobs from before the deploy have no log; the counts, cost and rework are still right per day, the generation time is NOT estimated for them)."""
from datetime import datetime, timedelta

import status_log

WINDOWS = {"24h": (24, 3600), "7d": (28, 21600), "30d": (30, 86400)}
DEFAULT_N = 20


def _dt(iso):
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def event_time(job, kind):
    """(datetime or None, approx). kind: done | failed."""
    if kind == "done":
        t = status_log.last_time(job, "done")
    else:
        t = status_log.first_time(job, "failed")
    if t:
        return _dt(t), False
    return _dt(job.get("created_at")), True


def gen_minutes(job):
    """Minutes from the first start (queued / preparing / running) to the first end (done / awaiting_approval); None when the log lacks either."""
    a = _dt(status_log.first_time(job, "queued", "preparing", "running"))
    b = _dt(status_log.first_time(job, "done", "awaiting_approval"))
    if not a or not b or b < a:
        return None
    return round((b - a).total_seconds() / 60.0, 1)


def cost_of(job):
    c = job.get("cost_actual")
    if isinstance(c, dict) and isinstance(c.get("grand_total_eur"), (int, float)):
        return float(c["grand_total_eur"])
    return None


def had_rework(job):
    return bool(job.get("auto_reworked")) or bool(job.get("reworks"))


def _buckets(now, window):
    n, step = WINDOWS[window]
    start = now - timedelta(seconds=n * step)
    return start, n, step


def _slot(t, start, n, step):
    if t is None or t < start:
        return None
    i = int((t - start).total_seconds() // step)
    return i if 0 <= i < n else (n - 1 if i == n else None)


def build(jobs, samples, now, window="24h"):
    """{"window", "now", "tiles": {key: {"label","unit","points":[{"t","v"}], "total","detail"}}}. v = None where a bucket has no data."""
    if window not in WINDOWS:
        window = "24h"
    start, n, step = _buckets(now, window)
    times = [(start + timedelta(seconds=i * step)).isoformat() for i in range(n)]
    done, failed, gen, cost, rw_n, rw_d = ([[] for _ in range(n)] for _ in range(6))
    approx_any = False
    for j in jobs.values():
        if not isinstance(j, dict):
            continue
        st = j.get("status")
        if st == "done":
            t, ap = event_time(j, "done")
            i = _slot(t, start, n, step)
            if i is not None:
                done[i].append(j); approx_any = approx_any or ap
                g = gen_minutes(j)
                if g is not None:
                    gen[i].append(g)
                c = cost_of(j)
                if c is not None:
                    cost[i].append(c)
                rw_d[i].append(1)
                if had_rework(j):
                    rw_n[i].append(1)
        elif st == "failed":
            t, ap = event_time(j, "failed")
            i = _slot(t, start, n, step)
            if i is not None:
                failed[i].append(j); approx_any = approx_any or ap
    avg = lambda xs: (round(sum(xs) / len(xs), 2) if xs else None)
    allgen = [x for b in gen for x in b]
    allcost = [x for b in cost for x in b]
    ndone, nfail = sum(len(b) for b in done), sum(len(b) for b in failed)
    ndr = sum(len(b) for b in rw_d)
    nrw = sum(len(b) for b in rw_n)
    tiles = {
        "completed": {"label": "Video completati", "unit": "", "points": [{"t": times[i], "v": len(done[i])} for i in range(n)], "total": ndone},
        "failed": {"label": "Video falliti", "unit": "", "points": [{"t": times[i], "v": len(failed[i])} for i in range(n)], "total": nfail,
                   "detail": ("riuscita %d%%" % round(100.0 * ndone / (ndone + nfail))) if (ndone + nfail) else "nessun video"},
        "gen_time": {"label": "Tempo di generazione", "unit": "min", "points": [{"t": times[i], "v": avg(gen[i])} for i in range(n)],
                     "total": avg(allgen), "detail": ("max %s min su %d video" % (max(allgen), len(allgen))) if allgen else "nessun dato ancora (si registra dal deploy)"},
        "cost_avg": {"label": "Costo medio per video", "unit": "EUR", "points": [{"t": times[i], "v": avg(cost[i])} for i in range(n)],
                     "total": avg(allcost), "detail": ("su %d video con costo noto" % len(allcost)) if allcost else "nessun costo noto"},
        "rework_pct": {"label": "Rework", "unit": "%", "points": [{"t": times[i], "v": (round(100.0 * len(rw_n[i]) / len(rw_d[i]), 1) if rw_d[i] else None)} for i in range(n)],
                       "total": (round(100.0 * nrw / ndr, 1) if ndr else None), "detail": ("%d video su %d con rework" % (nrw, ndr)) if ndr else "nessun video"},
    }
    cut = start.timestamp()
    smp = [s for s in (samples or []) if isinstance(s, dict) and s.get("t", 0) >= cut]

    def sseries(key):
        pts = [[] for _ in range(n)]
        for s in smp:
            i = _slot(datetime.utcfromtimestamp(s["t"]), start, n, step)
            if i is not None and isinstance(s.get(key), (int, float)):
                pts[i].append(s[key])
        return [{"t": times[i], "v": (round(sum(pts[i]) / len(pts[i]), 2) if pts[i] else None)} for i in range(n)]
    last = smp[-1] if smp else {}
    tiles["stuck"] = {"label": "Job fermi", "unit": "", "points": sseries("s"), "total": last.get("s"),
                      "detail": "ora" if last else "nessun campione ancora"}
    tiles["health"] = {"label": "Salute: disco e memoria", "unit": "%", "points": sseries("p"), "points2": sseries("m"), "total": last.get("p"),
                       "total2": last.get("m"), "detail": ("disco %s%% (linea piena), memoria %s%% (tratteggiata)" % (last.get("p"), last.get("m"))) if last else "nessun campione ancora"}
    return {"window": window, "now": now.isoformat(), "approx": approx_any, "tiles": tiles}


def list_items(jobs, kind, now, n=DEFAULT_N):
    """The drill-down lists: the last `n` items of a kind, newest first. kinds: completed | failed | cost | rework | gen_time."""
    rows = []
    for jid, j in jobs.items():
        if not isinstance(j, dict):
            continue
        st = j.get("status")
        base = {"job_id": jid, "name": j.get("property_name"), "status": st}
        if kind == "completed" and st == "done":
            t, ap = event_time(j, "done"); rows.append(dict(base, t=t, approx=ap, value=cost_of(j)))
        elif kind == "failed" and st == "failed":
            t, ap = event_time(j, "failed"); rows.append(dict(base, t=t, approx=ap, value=j.get("failure_code") or str(j.get("message") or "")[:80]))
        elif kind == "cost" and st == "done" and cost_of(j) is not None:
            t, ap = event_time(j, "done"); rows.append(dict(base, t=t, approx=ap, value=cost_of(j)))
        elif kind == "rework" and st in ("done", "awaiting_approval", "failed") and had_rework(j):
            t, ap = event_time(j, "done"); rows.append(dict(base, t=t, approx=ap, value=len(j.get("auto_reworked") or []) + len(j.get("reworks") or [])))
        elif kind == "gen_time" and st == "done" and gen_minutes(j) is not None:
            t, ap = event_time(j, "done"); rows.append(dict(base, t=t, approx=ap, value=gen_minutes(j)))
    rows = [r for r in rows if r["t"] is not None]
    rows.sort(key=lambda r: r["t"], reverse=True)
    if kind == "gen_time":
        rows = rows[:max(1, int(n))]
        rows.sort(key=lambda r: r["value"], reverse=True)   # the slowest first inside the last n
    else:
        rows = rows[:max(1, int(n))]
    for r in rows:
        r["t"] = r["t"].isoformat()
    return rows
