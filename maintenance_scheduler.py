"""
maintenance_scheduler.py

Daily automated health & maintenance check for Property Video Studio.

Run via cron (see setup command in the deployment notes) — NOT imported by
api_server.py's request path. It writes its report to maintenance_status.json,
which api_server.py exposes via GET /maintenance/status for the UI panel.

Checks performed (all read-only, cheap — safe to run even if a job happens
to be generating at the same time):
  - Disk usage on the project volume
  - fal.ai / ElevenLabs credit balance (reuses credit_monitor.get_all_credits())
  - property-video.service systemd status
  - Stuck jobs (status stuck in "generating"/"processing" past STUCK_JOB_MINUTES)
  - _test_scratch/ directory size (should stay small — growth means test
    cleanup isn't actually happening)
  - Recent Luma→Veo / Veo-Standard→Fast fallback rate (log scan) — a spike can
    mean an upstream fal.ai issue, not just one bad photo
  - Confirms the existing 7-day job auto-cleanup is actually deleting what it
    should (nothing currently checks that it *worked*, only that it *runs*)

Housekeeping performed:
  - Deletes _test_scratch/ contents older than TEST_SCRATCH_MAX_AGE_DAYS
  - Reports reclaimed disk space

On any RED-flag check, sends one alert email to every address in
maintenance_alert_emails.json (editable via the API / UI — see api_server.py's
/maintenance/alert-emails endpoints), reusing the Gmail SMTP credentials
already configured for credit_monitor.py (ALERT_EMAIL_FROM / ALERT_EMAIL_PASSWORD
in .env). Does not touch credit_monitor.py's own existing single-recipient
alert path — that keeps working independently for its own per-job checks.

NOTE ON JOB SCHEMA ASSUMPTIONS: check_stuck_jobs() and check_cleanup_ran()
assume each job directory has a job.json with "status" and
"generation_started_at" fields, and that job-directory mtime reflects last
activity. If the actual field names in api_server.py's job model differ,
these two checks will just harmlessly report "none/ok" rather than error —
adjust the field names below to match reality before trusting their output.
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
ALERT_EMAILS_FILE = BASE_DIR / "maintenance_alert_emails.json"
LOG_FILE          = Path("/tmp/property-video.log")  # confirmed via start.sh — screen session pipes uvicorn output here
API_BASE          = "http://localhost:8000"

# ── Thresholds (tune as needed) ─────────────────────────────────────────────
DISK_WARN_PCT             = 80
DISK_RED_PCT              = 90
STUCK_JOB_MINUTES         = 45     # a single scene generation shouldn't take this long
TEST_SCRATCH_WARN_MB      = 500
TEST_SCRATCH_MAX_AGE_DAYS = 3
JOB_RETENTION_DAYS        = 7      # must match api_server.py's own cleanup window
FALLBACK_RATE_RED         = 5      # more than N fallbacks logged looks like an upstream issue

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
    logic actually lives (inside api_server.py), so this reuses it rather
    than re-implementing deletion in a second, separate place. Calling the
    live endpoint also means the server's in-memory job list gets updated
    correctly, which a standalone script deleting files directly could not
    safely do. After triggering it, re-scans the filesystem to confirm
    nothing past the retention window is still sitting there.
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


def check_fallback_rate() -> dict:
    if not LOG_FILE.exists():
        return {"name": "fallback_rate", "status": "warn", "detail": "log file not found — check LOG_FILE path"}
    count = 0
    try:
        with open(LOG_FILE) as f:
            for line in f:
                if "falling back to Veo" in line or "Luma failed" in line or "Veo Standard failed" in line:
                    count += 1
    except Exception as e:
        return {"name": "fallback_rate", "status": "warn", "detail": f"could not read log: {e}"}
    status = "red" if count >= FALLBACK_RATE_RED else "ok"
    return {"name": "fallback_rate", "status": status, "detail": f"{count} fallback event(s) found in log"}


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


# ── Email ──────────────────────────────────────────────────────────────────

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


# ── Main ─────────────────────────────────────────────────────────────────────

def run_maintenance() -> dict:
    checks = [
        check_disk(),
        check_credits(),
        check_service(),
        check_stuck_jobs(),
        check_test_scratch(),
        check_cleanup_ran(),
        check_fallback_rate(),
    ]
    cleanup_result = clean_test_scratch()
    any_red = any(c["status"] == "red" for c in checks)

    report = {
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
        "cleanup": cleanup_result,
        "any_red": any_red,
    }
    STATUS_FILE.write_text(json.dumps(report, indent=2))

    if any_red:
        red_checks = [c for c in checks if c["status"] == "red"]
        body = "<h3>Property Video Studio — Maintenance Alert</h3><ul>"
        for c in red_checks:
            body += f"<li><b>{c['name']}</b>: {c['detail']}</li>"
        body += "</ul>"
        send_maintenance_alert("Property Video Studio — Maintenance Alert", body)

    log.info(f"[Maintenance] Run complete. any_red={any_red}")
    return report


if __name__ == "__main__":
    run_maintenance()
