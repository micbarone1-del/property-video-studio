"""
maintenance_scheduler.py

Tiered automatic health & maintenance checks for Property Video Studio.

Unlike a single "run everything once a day" script, each check below runs
on its OWN interval (see CHECK_INTERVALS). This file is designed to be
invoked FREQUENTLY (every 5 minutes, via cron — see deployment notes below),
but each individual check only actually executes once its own interval has
elapsed since it last ran. maintenance_last_run.json persists per-check
timestamps so this stays correct across restarts and repeated invocations.

WHY THE OUTER TRIGGER MUST BE EXTERNAL (cron), NOT AN IN-APP BACKGROUND TASK:
service_status is a health check on api_server.py itself. If that check
were scheduled from WITHIN api_server.py (e.g. an asyncio background task),
it could never detect the one failure mode that matters most — the app
process itself crashing or hanging — because the check would die along
with the thing it's supposed to be watching. Running this as an
independent, cron-triggered process is what makes it a real check.

Deployment (run once):
  apt-get install -y cron && systemctl enable cron && systemctl start cron
  (crontab -l 2>/dev/null; echo "*/5 * * * * cd /var/www/property-video-studio && venv/bin/python3 maintenance_scheduler.py >> /tmp/maintenance.log 2>&1") | crontab -

Checks and their intervals — see CHECK_INTERVALS below for the source of
truth; this table is illustrative:
  - service_status        every  5 min  — HTTP health check; outages need fast detection
  - disk_usage             every 30 min
  - stuck_jobs              every 30 min
  - credits                every  1 hr  — credit_monitor already alerts directly
                                          at job start/end; this is a backup net
  - fallback_rate          every  1 hr
  - test_scratch_size      every  6 hr  — low urgency
  - cleanup_verification   every 24 hr  — the only check with a real destructive
                                          side effect (triggers actual job deletion
                                          via /diagnostics) — deliberately the
                                          least frequent

On any RED-flag check (from the latest known state of ALL checks, not just
ones that happened to run this tick), sends an alert email to every address
in maintenance_alert_emails.json — throttled to at most one email per
ALERT_COOLDOWN_MINUTES for an ongoing issue, so a persistent problem doesn't
spam an email every 5 minutes.

NOTE ON JOB SCHEMA ASSUMPTIONS: check_stuck_jobs() assumes each job
directory's job.json has "status" and "generation_started_at" fields.
If the actual field names differ, this check will just harmlessly report
"none" rather than error — verify against real job.json content if you
want to trust this one specifically.
"""

import os
import json
import shutil
import smtplib
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests
from dotenv import load_dotenv
import credit_monitor

load_dotenv()
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
JOBS_DIR          = BASE_DIR / "jobs"
TEST_SCRATCH_DIR  = JOBS_DIR / "_test_scratch"
STATUS_FILE       = BASE_DIR / "maintenance_status.json"
LAST_RUN_FILE     = BASE_DIR / "maintenance_last_run.json"
ALERT_EMAILS_FILE = BASE_DIR / "maintenance_alert_emails.json"
LOG_FILE          = Path("/tmp/property-video.log")  # confirmed via start.sh — screen session pipes uvicorn output here
API_BASE          = "http://localhost:8000"

# ── Per-check frequency, in minutes — the actual scheduling source of truth ──
CHECK_INTERVALS = {
    "service_status":       5,
    "disk_usage":           30,
    "stuck_jobs":            30,
    "credits":               60,
    "fallback_rate":         60,
    "test_scratch_size":     360,
    "cleanup_verification":  1440,
}
ALERT_COOLDOWN_MINUTES = 60  # don't re-email more than once/hour for an ongoing issue

# ── Thresholds (tune as needed) ─────────────────────────────────────────────
DISK_WARN_PCT             = 80
DISK_RED_PCT              = 90
STUCK_JOB_MINUTES         = 45
TEST_SCRATCH_WARN_MB      = 500
TEST_SCRATCH_MAX_AGE_DAYS = 3
JOB_RETENTION_DAYS        = 7
FALLBACK_RATE_RED         = 5
FALLBACK_LOG_TAIL_LINES   = 5000  # bound scan cost regardless of run frequency

EMAIL_FROM     = credit_monitor.EMAIL_FROM
EMAIL_PASSWORD = credit_monitor.EMAIL_PASSWORD


# ── Recipient list (editable via API, not just .env) ───────────────────────

def load_alert_emails() -> list:
    if ALERT_EMAILS_FILE.exists():
        try:
            return json.loads(ALERT_EMAILS_FILE.read_text())
        except Exception:
            log.error("[Maintenance] Could not parse maintenance_alert_emails.json — using default.")
    default = os.getenv("ALERT_EMAIL_TO", "").strip()
    return [default] if default else []


def save_alert_emails(emails: list) -> None:
    ALERT_EMAILS_FILE.write_text(json.dumps(emails, indent=2))


# ── Per-check scheduling state ──────────────────────────────────────────────

def _load_last_run() -> dict:
    if LAST_RUN_FILE.exists():
        try:
            return json.loads(LAST_RUN_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_last_run(data: dict) -> None:
    LAST_RUN_FILE.write_text(json.dumps(data, indent=2))


def _is_due(check_name: str, last_run: dict) -> bool:
    last = last_run.get(check_name)
    if not last:
        return True  # never run before
    interval = timedelta(minutes=CHECK_INTERVALS.get(check_name, 60))
    try:
        return datetime.now() - datetime.fromisoformat(last) > interval
    except Exception:
        return True


# ── Individual checks ────────────────────────────────────────────────────────

def check_disk() -> dict:
    total, used, free = shutil.disk_usage(BASE_DIR)
    pct = round(used / total * 100, 1)
    status = "red" if pct >= DISK_RED_PCT else "warn" if pct >= DISK_WARN_PCT else "ok"
    return {"name": "disk_usage", "status": status,
            "detail": f"{pct}% used ({free // (1024**3)} GB free)"}


def check_credits() -> dict:
    try:
        credits = credit_monitor.get_all_credits()
        status = "red" if credits.get("any_low") else "ok"
        detail = f"fal: {credits.get('fal', {}).get('balance')}, elevenlabs: {credits.get('elevenlabs', {}).get('remaining_chars')}"
        return {"name": "credits", "status": status, "detail": detail}
    except Exception as e:
        return {"name": "credits", "status": "warn", "detail": f"check failed: {e}"}


def check_service() -> dict:
    """Deployment runs via a `screen` session + uvicorn (see start.sh), not a
    systemd unit — so the real check is hitting the server's own /health
    endpoint, the same check start.sh itself uses to confirm a successful launch."""
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=5)
        ok = resp.status_code == 200 and "ok" in resp.text
        return {"name": "service_status", "status": "ok" if ok else "red",
                "detail": f"HTTP {resp.status_code}: {resp.text[:80]}"}
    except Exception as e:
        return {"name": "service_status", "status": "red", "detail": f"server unreachable: {e}"}


def check_stuck_jobs() -> dict:
    if not JOBS_DIR.exists():
        return {"name": "stuck_jobs", "status": "ok", "detail": "no jobs directory"}
    stuck = []
    cutoff = datetime.now() - timedelta(minutes=STUCK_JOB_MINUTES)
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir() or job_dir.name == "_test_scratch":
            continue
        meta_file = job_dir / "job.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
        except Exception:
            continue
        status = meta.get("status", "")
        started = meta.get("generation_started_at")
        if status in ("generating", "processing") and started:
            try:
                if datetime.fromisoformat(started) < cutoff:
                    stuck.append(job_dir.name)
            except Exception:
                pass
    return {"name": "stuck_jobs", "status": "red" if stuck else "ok",
            "detail": f"{len(stuck)} stuck job(s): {', '.join(stuck)}" if stuck else "none"}


def check_test_scratch() -> dict:
    if not TEST_SCRATCH_DIR.exists():
        return {"name": "test_scratch_size", "status": "ok", "detail": "directory does not exist"}
    total_bytes = sum(f.stat().st_size for f in TEST_SCRATCH_DIR.rglob("*") if f.is_file())
    mb = round(total_bytes / (1024**2), 1)
    status = "warn" if mb >= TEST_SCRATCH_WARN_MB else "ok"
    return {"name": "test_scratch_size", "status": status, "detail": f"{mb} MB"}


def _diagnostics_headers() -> dict:
    key = os.getenv("UI_ACCESS_KEY", "").strip()
    return {"X-Access-Key": key} if key else {}


def check_cleanup_ran() -> dict:
    """Triggers the server's REAL 7-day auto-cleanup by calling its own
    /diagnostics endpoint over HTTP — that's the only place the deletion
    logic actually lives, so this reuses it rather than re-implementing
    deletion in a second place. Re-scans the filesystem afterward to
    confirm nothing past the retention window is still sitting there.
    """
    try:
        resp = requests.get(f"{API_BASE}/diagnostics", headers=_diagnostics_headers(), timeout=15)
        resp.raise_for_status()
        diag = resp.json()
        cleaned_by_diagnostics = diag.get("cleaned_jobs", 0)
    except Exception as e:
        return {"name": "cleanup_verification", "status": "warn",
                "detail": f"could not reach /diagnostics to trigger cleanup: {e}"}

    if not JOBS_DIR.exists():
        return {"name": "cleanup_verification", "status": "ok", "detail": "no jobs directory"}

    cutoff = datetime.now() - timedelta(days=JOB_RETENTION_DAYS + 1)
    stale = []
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir() or job_dir.name == "_test_scratch":
            continue
        mtime = datetime.fromtimestamp(job_dir.stat().st_mtime)
        if mtime < cutoff:
            stale.append(job_dir.name)

    if stale:
        detail = (f"{len(stale)} job(s) still past retention after triggering cleanup "
                  f"(diagnostics reported {cleaned_by_diagnostics} cleaned this run): "
                  f"{', '.join(stale[:5])}{'...' if len(stale) > 5 else ''}")
        return {"name": "cleanup_verification", "status": "red", "detail": detail}
    return {"name": "cleanup_verification", "status": "ok",
            "detail": f"clean — {cleaned_by_diagnostics} job(s) removed this run" if cleaned_by_diagnostics
                      else "clean, nothing needed removal"}


def _tail_lines(path: Path, n: int) -> list:
    """Efficiently reads roughly the last n lines of a (potentially large)
    log file, without loading the whole thing into memory."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 8192
            data = b''
            while size > 0 and data.count(b'\n') <= n:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
        return data.decode(errors='ignore').splitlines()[-n:]
    except Exception:
        return []


def check_fallback_rate() -> dict:
    if not LOG_FILE.exists():
        return {"name": "fallback_rate", "status": "warn", "detail": "log file not found — check LOG_FILE path"}
    lines = _tail_lines(LOG_FILE, FALLBACK_LOG_TAIL_LINES)
    count = sum(1 for l in lines
                if "falling back to Veo" in l or "Luma failed" in l or "Veo Standard failed" in l)
    status = "red" if count >= FALLBACK_RATE_RED else "ok"
    return {"name": "fallback_rate", "status": status,
            "detail": f"{count} fallback event(s) in last {len(lines)} log lines scanned"}


# ── Housekeeping ─────────────────────────────────────────────────────────────

def clean_test_scratch() -> dict:
    if not TEST_SCRATCH_DIR.exists():
        return {"reclaimed_mb": 0, "items_removed": 0, "detail": "directory does not exist"}
    cutoff = datetime.now() - timedelta(days=TEST_SCRATCH_MAX_AGE_DAYS)
    reclaimed = 0
    removed = 0
    for item in TEST_SCRATCH_DIR.iterdir():
        try:
            mtime = datetime.fromtimestamp(item.stat().st_mtime)
            if mtime < cutoff:
                size = (sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                        if item.is_dir() else item.stat().st_size)
                shutil.rmtree(item) if item.is_dir() else item.unlink()
                reclaimed += size
                removed += 1
        except Exception as e:
            log.error(f"[Maintenance] Could not clean {item}: {e}")
    return {"reclaimed_mb": round(reclaimed / (1024**2), 1), "items_removed": removed}


# ── Email ────────────────────────────────────────────────────────────────────

def send_maintenance_alert(subject: str, body_html: str) -> bool:
    recipients = load_alert_emails()
    if not recipients or not all([EMAIL_FROM, EMAIL_PASSWORD]):
        log.warning("[Maintenance] Alert email skipped — no recipients or SMTP creds not configured.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, recipients, msg.as_string())
        log.info(f"[Maintenance] Alert email sent to {recipients}")
        return True
    except Exception as e:
        log.error(f"[Maintenance] Failed to send alert email: {e}")
        return False


def _alert_is_on_cooldown(last_run: dict) -> bool:
    last_alert = last_run.get("_last_alert_sent")
    if not last_alert:
        return False
    try:
        return datetime.now() - datetime.fromisoformat(last_alert) < timedelta(minutes=ALERT_COOLDOWN_MINUTES)
    except Exception:
        return False


# ── Registry — check name -> function ───────────────────────────────────────
CHECK_FUNCTIONS = {
    "service_status":       check_service,
    "disk_usage":           check_disk,
    "stuck_jobs":           check_stuck_jobs,
    "credits":              check_credits,
    "fallback_rate":        check_fallback_rate,
    "test_scratch_size":    check_test_scratch,
    "cleanup_verification": check_cleanup_ran,
}


# ── Main entry point ─────────────────────────────────────────────────────────

def run_due_checks() -> dict:
    """Call this frequently (every 5 min via cron — see module docstring).
    Each individual check only actually executes once its own interval has
    elapsed. Always writes a FULL, merged status snapshot — checks that
    weren't due this tick keep their last known result — so the UI panel
    and any consumer of maintenance_status.json always sees a complete
    picture, not just whatever happened to run in this particular tick.
    """
    last_run = _load_last_run()

    prior_status = {}
    if STATUS_FILE.exists():
        try:
            prior = json.loads(STATUS_FILE.read_text())
            prior_status = {c["name"]: c for c in prior.get("checks", [])}
        except Exception:
            pass

    results = dict(prior_status)
    ran_this_tick = []

    for name, fn in CHECK_FUNCTIONS.items():
        if _is_due(name, last_run):
            try:
                results[name] = fn()
            except Exception as e:
                results[name] = {"name": name, "status": "warn", "detail": f"check crashed: {e}"}
            last_run[name] = datetime.now().isoformat()
            ran_this_tick.append(name)

    cleanup_result = (prior_status.get("_cleanup_housekeeping")
                       or {"reclaimed_mb": 0, "items_removed": 0})
    if "test_scratch_size" in ran_this_tick:
        cleanup_result = clean_test_scratch()

    checks_list = [v for k, v in results.items() if not k.startswith("_")]
    any_red = any(c.get("status") == "red" for c in checks_list)

    report = {
        "timestamp": datetime.now().isoformat(),
        "checks_ran_this_tick": ran_this_tick,
        "checks": checks_list,
        "cleanup": cleanup_result,
        "any_red": any_red,
    }
    STATUS_FILE.write_text(json.dumps(report, indent=2))

    if any_red and not _alert_is_on_cooldown(last_run):
        red_checks = [c for c in checks_list if c.get("status") == "red"]
        body = "<h3>Property Video Studio — Maintenance Alert</h3><ul>"
        for c in red_checks:
            body += f"<li><b>{c['name']}</b>: {c['detail']}</li>"
        body += "</ul>"
        if send_maintenance_alert("Property Video Studio — Maintenance Alert", body):
            last_run["_last_alert_sent"] = datetime.now().isoformat()

    _save_last_run(last_run)
    log.info(f"[Maintenance] Tick complete. ran={ran_this_tick} any_red={any_red}")
    return report


if __name__ == "__main__":
    run_due_checks()
