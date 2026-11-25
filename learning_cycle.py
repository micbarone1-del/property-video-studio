"""learning_cycle.py - the AUTOMATIC loop (2026-11-25, Michele: "automatico, con avviso solo se pienamente provato"). Runs once a day from the existing
maintenance_scheduler (check "learning_cycle", every 1440 min; no new cron). Nobody has to do anything.
Each run: (1) learning_loop.report on the real registry + jobs, writes learning_report.json and learning_rules.json (rules that HELD on unseen jobs);
(2) keeps learning_state.json (when each rule was first seen, whether apply is on); (3) decides whether a rule is FULLY PROVEN; (4) revert check.
FULLY PROVEN (written before looking at any result), ALL of:
  a. the rule has been in learning_rules.json (held on the hold-out) for at least PROVEN_MIN_DAYS days in a row;
  b. the shadow phase is due (learning_apply.report phase3_due: 40 firing scenes or 14/12/2026);
  c. on production scenes after the rule was first seen, scenes matching it (learn_shadow) are >= SHADOW_MIN_N and from >= MIN_JOBS distinct jobs, with a bad rate >= 1.3x the rest and >= 10 points above;
  d. the rule names a movement ('move' in its condition) and learning_apply.pick_alt_move finds a better one in the registry.
Then the cycle writes apply=on with an expiry (APPLY_DAYS days, renewed every day the conditions still hold) for THAT rule only, and sends ONE notification.
Revert: learning_apply.revert_check; if it says REVERT, apply goes off, the revert file blocks everything (also the manual switch) until a human removes it, ONE notification.
Notifications: ONLY these two events. Nothing else is sent. Never touches jobs/. Never raises out of run()."""
import json
import os
import time
from pathlib import Path

import learning_apply as la
import learning_loop as ll

PROVEN_MIN_DAYS = 7
SHADOW_MIN_N = 10
APPLY_DAYS = 14
HERE = Path(__file__).resolve().parent


def _data():
    return Path(os.getenv("PVS_DATA_DIR") or HERE)


def state_file():
    return _data() / "learning_state.json"


def status_file():
    return _data() / "learning_status.json"


def _write(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_state():
    try:
        s = json.loads(state_file().read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def _days_between(d1, d2):
    t = lambda d: time.mktime(time.strptime(d[:10], "%Y-%m-%d"))
    return int((t(d2) - t(d1)) / 86400)


def shadow_evidence(rule_id, since_ts, events):
    first = [e for e in events if e.get("stage") == "first" and str(e.get("ts") or "") >= since_ts]
    m = [e for e in first if rule_id in (e.get("learn_shadow") or [])]
    rest = [e for e in first if rule_id not in (e.get("learn_shadow") or [])]
    bad = lambda xs: (sum(1 for e in xs if la._bad(e)) / len(xs)) if xs else None
    rm, rr = bad(m), bad(rest)
    ok = bool(len(m) >= SHADOW_MIN_N and rm is not None and rr is not None and rm >= ll.HOLDOUT_MIN_RATIO * rr and rm - rr >= ll.HOLDOUT_MIN_GAP)
    jobs = len({e.get("job") for e in m})
    return {"n": len(m), "jobs": jobs, "rate": rm, "rest_rate": rr, "ok": bool(ok and jobs >= ll.MIN_JOBS)}


def _default_notify(subject, body):
    import maintenance_scheduler as ms
    return ms.send_notification(subject, f"<p>{body}</p>", push_message=body, priority="high", tags=["brain"], level="info", kind="learning")


def run(today=None, notify=None, jobs_dir=None):
    """Returns the status dict (also written to learning_status.json). Never raises."""
    try:
        return _run(today or time.strftime("%Y-%m-%d"), notify or _default_notify, jobs_dir)
    except Exception as e:
        return {"ok": False, "error": f"learning cycle failed: {e}", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _run(today, notify, jobs_dir):
    data = _data()
    jobs_dir = Path(jobs_dir or os.getenv("PVS_JOBS_DIR") or (HERE / "jobs"))
    risk = ll.load_jsonl(os.getenv("PVS_SCENE_RISK_FILE") or data / "scene_risk_events.jsonl")
    shadow = ll.load_jsonl(os.getenv("PVS_STANDARD_SHADOW_FILE") or data / "standard_shadow_events.jsonl")
    rep = ll.report(risk, shadow, ll.load_jobs(jobs_dir))
    rules = ll.export_rules(rep)
    _write(data / "learning_report.json", rep)
    _write(data / "learning_rules.json", rules)
    now_ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    st = load_state()
    seen = st.get("first_seen") or {}
    ids = [r["id"] for r in rules["rules"]]
    seen = {i: seen.get(i) or {"date": today, "ts": now_ts} for i in ids}      # a rule that stops holding is forgotten: its clock restarts
    events = la._events()
    notes = []
    apply = st.get("apply") or {"on": False}
    reverted = la.revert_file().exists()
    if apply.get("on") or reverted:
        res = la.revert_check()
        if res.get("status") == "REVERT" or reverted:
            if apply.get("on"):
                apply = {"on": False, "reverted": today}
                notify("Ciclo di apprendimento: regola spenta", f"Dopo l'applicazione i tassi sono peggiorati: la regola e' stata spenta da sola ({res}). Per riaccenderla serve togliere a mano learning_apply_revert.json.")
                notes.append("reverted")
    proven, due = [], la.report(events)["phase3_due"]
    evidence = {}
    for r in rules["rules"]:
        cond = dict((c[0], c[1]) for c in r["cond"])
        ev = shadow_evidence(r["id"], seen[r["id"]]["ts"], events)
        days = _days_between(seen[r["id"]]["date"], today)
        alt = la.pick_alt_move(cond.get("move"), events, ctx=r["cond"]) if "move" in cond else None
        evidence[r["id"]] = {**ev, "days_held": days, "alt_move": alt}
        if days >= PROVEN_MIN_DAYS and due and ev["ok"] and alt and not reverted and not la.revert_file().exists():
            proven.append(r["id"])
    if proven:
        until = time.strftime("%Y-%m-%d", time.localtime(time.mktime(time.strptime(today, "%Y-%m-%d")) + APPLY_DAYS * 86400))
        was_on = bool(apply.get("on")) and set(apply.get("rules") or []) == set(proven)
        apply = {**apply, "on": True, "until": until, "rules": proven, "since": apply.get("since") if was_on else now_ts}
        if not was_on:
            notify("Ciclo di apprendimento: regola provata e applicata", f"Regola/e {', '.join(proven)} provata/e (regge sul hold-out, in ombra su scene reali, movimento alternativo noto). Applicata/e fino al {until}, con ritorno automatico se peggiora.")
            notes.append("applied")
    elif apply.get("on") and not proven:
        apply = {"on": False, "ended": today}
    st = {"first_seen": seen, "apply": apply, "updated": now_ts}
    _write(state_file(), st)
    status = {"ok": True, "ts": now_ts, "rules_holding": len(ids), "phase3_due": due, "scenes_firing": la.report(events)["scenes_firing"],
              "apply_on": bool(apply.get("on")), "apply_until": apply.get("until"), "evidence": evidence, "notified": notes,
              "rows": rep["video"]["rows"], "note": "" if ids else "nessuna regola regge ancora (dati insufficienti o nessuno schema stabile)"}
    _write(status_file(), status)
    return status
