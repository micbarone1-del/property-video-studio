"""heartbeat_watchdog.py - the ONE place that decides whether the maintenance cron has stopped and mails the operator about it. 2026-11-23.
The age comes from health_kpi.heartbeat_age_min (the same reader as the dashboard card, no second copy of that logic).
Rules (agreed with the operator): mail when the heartbeat is older than STALE_MIN (30 min); repeat at most every REPEAT_H (6 h) while it stays stale;
when it recovers the state resets, so a new outage mails at once. The last-mail time is kept in a small file, so an app restart does not cause a second mail.
No status file at all counts as stale only after the app has been up for STALE_MIN minutes (a fresh install is not an outage). Never raises."""
import json
import logging
import time
from datetime import datetime

import health_kpi

log = logging.getLogger("api_server")
STALE_MIN = 30
REPEAT_H = 6
_STARTED = time.time()


def state_file():
    return health_kpi._data_dir() / "heartbeat_watchdog_state.json"


def _load() -> dict:
    try:
        return json.loads(state_file().read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        state_file().write_text(json.dumps(d))
    except Exception as e:
        log.warning(f"[Watchdog] could not save state (non-fatal): {e}")


def decide(age_min, last_mail_ts, now_ts, uptime_min) -> str:
    """Pure decision: 'mail' | 'wait' | 'ok'. age_min None = no status file."""
    stale = (age_min is None and uptime_min >= STALE_MIN) or (age_min is not None and age_min > STALE_MIN)
    if not stale:
        return "ok"
    if last_mail_ts and now_ts - last_mail_ts < REPEAT_H * 3600:
        return "wait"
    return "mail"


def tick(now: datetime = None, send=None, status_file=None) -> str:
    """One check; called every minute by the app's existing loop. Returns what it did (for the tests and the log)."""
    try:
        now = now or datetime.now()
        now_ts = now.timestamp()
        age = health_kpi.heartbeat_age_min(status_file, now)
        st = _load()
        action = decide(age, st.get("last_mail"), now_ts, (time.time() - _STARTED) / 60)
        if action == "ok":
            if st.get("last_mail"):
                _save({})            # recovered: the next outage mails at once
            return "ok"
        if action == "wait":
            return "wait"
        if send is None:
            import credit_monitor
            send = credit_monitor.send_alert_email
        what = "nessun dato di manutenzione" if age is None else f"ultimo giro {round(age)} minuti fa"
        ok = send("Property Video Studio: la manutenzione automatica sembra ferma",
                  f"<p>Il controllo automatico (ogni 5 minuti) non risulta attivo: {what}.</p>"
                  "<p>Disco, backup e crediti potrebbero non essere sotto controllo. Controlla il cron di manutenzione sul server.</p>"
                  f"<p>Se resta fermo ripeto questa mail al massimo ogni {REPEAT_H} ore.</p>")
        if ok:
            _save({"last_mail": now_ts})
            return "mailed"
        return "mail-failed"          # not saved: tried again at the next tick
    except Exception as e:
        log.warning(f"[Watchdog] tick failed (non-fatal): {e}")
        return "error"
