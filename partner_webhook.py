"""2026-11-20: delivery state of the partner webhook (completed / failed). Pure functions, no network: api_server does the posting and calls these.
Decided with Michele: first attempt at once, then 3 retries after 1, 5 and 15 minutes (4 attempts in all); the result is stored in the job
(job["webhook_delivery"]: event, status pending|delivered|failed, attempts, last_http, last_error, last_at, next_at); when every attempt fails the
operator is told ONCE. Never the callback URL (it carries a token) and never a change of the video's own status."""
from datetime import datetime, timedelta

RETRY_DELAYS = (60, 300, 900)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds")


def new_state(event: str) -> dict:
    return {"event": event, "status": "pending", "attempts": 0, "last_http": None, "last_error": None, "last_at": None, "next_at": None}


def is_ok_http(code) -> bool:
    return isinstance(code, int) and 200 <= code < 300


def record_attempt(state: dict, ok: bool, http=None, error=None) -> str:
    """Updates the state after ONE attempt. Returns "delivered", "retry" or "failed"."""
    now = datetime.utcnow()
    state["attempts"] = int(state.get("attempts", 0)) + 1
    state["last_http"] = http
    state["last_error"] = None if ok else (error or (f"HTTP {http}" if http else "no answer"))
    state["last_at"] = _iso(now)
    if ok:
        state["status"], state["next_at"] = "delivered", None
        return "delivered"
    if state["attempts"] >= MAX_ATTEMPTS:
        state["status"], state["next_at"] = "failed", None
        return "failed"
    state["status"] = "pending"
    state["next_at"] = _iso(now + timedelta(seconds=RETRY_DELAYS[state["attempts"] - 1]))
    return "retry"


def retry_delay(state: dict):
    """Seconds to wait before the next retry, None when nothing is left to do."""
    if state.get("status") != "pending":
        return None
    idx = max(int(state.get("attempts", 0)) - 1, 0)
    return RETRY_DELAYS[idx] if idx < len(RETRY_DELAYS) else None


def pending_event_jobs(jobs: dict) -> list:
    """[(job_id, state)] of the jobs whose webhook still waits for a retry (used once at startup: a restart must not lose them)."""
    out = []
    for jid, j in jobs.items():
        st = j.get("webhook_delivery") if isinstance(j, dict) else None
        if isinstance(st, dict) and st.get("status") == "pending" and j.get("callback_url"):
            out.append((jid, st))
    return out


def failure_html(job_id: str, job: dict, state: dict) -> str:
    event_it = {"completed": "completato", "failed": "fallito"}.get(state.get("event"), str(state.get("event")))
    last = f"HTTP {state.get('last_http')}" if state.get("last_http") else f"errore {state.get('last_error') or 'sconosciuto'}"
    return (f"<p>Il partner non ha ricevuto la notifica di video {event_it} dopo {state.get('attempts')} tentativi (ultimo esito: {last}).</p>"
            f"<p>Job {job_id}, external_ref {job.get('external_ref')}. Il video e il suo stato non sono cambiati: il partner puo' comunque leggerlo con "
            f"GET /v1/videos/{job_id}. Se il suo indirizzo di ritorno e' di nuovo raggiungibile, va riavvisato a mano.</p>")
