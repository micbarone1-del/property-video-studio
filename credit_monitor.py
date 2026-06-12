"""
credit_monitor.py
─────────────────
Checks remaining credits on fal.ai and ElevenLabs before and after each job.
Sends email alerts when any balance drops below configured thresholds.

Thresholds (set in .env):
  FAL_CREDIT_THRESHOLD        – warn below this USD value (default: 5.00)
  ELEVENLABS_CHAR_THRESHOLD   – warn below this character count (default: 10000)
  ALERT_EMAIL_TO              – address to send alerts to
  ALERT_EMAIL_FROM            – address to send alerts from (Gmail)
  ALERT_EMAIL_PASSWORD        – Gmail app password (not your main password)
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
FAL_THRESHOLD        = float(os.getenv("FAL_CREDIT_THRESHOLD", "5.00"))
ELEVENLABS_THRESHOLD = int(os.getenv("ELEVENLABS_CHAR_THRESHOLD", "10000"))

# ── Email config ───────────────────────────────────────────────────────────────
EMAIL_TO       = os.getenv("ALERT_EMAIL_TO", "")
EMAIL_FROM     = os.getenv("ALERT_EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")


# ── fal.ai credit check ────────────────────────────────────────────────────────

def get_fal_credits() -> dict:
    """
    Returns { "balance": float, "ok": bool, "error": str|None }
    ok=False means balance is below threshold or check failed.
    """
    api_key = os.getenv("FAL_KEY", "")
    if not api_key:
        return {"balance": None, "ok": True, "error": "FAL_KEY not set"}
    try:
        resp = requests.get(
            "https://api.fal.ai/billing/credits",
            headers={"Authorization": f"Key {api_key}"},
            timeout=10
        )
        resp.raise_for_status()
        data     = resp.json()
        balance  = float(data.get("balance", 0))
        return {
            "balance":  round(balance, 2),
            "ok":       balance >= FAL_THRESHOLD,
            "error":    None
        }
    except Exception as e:
        log.warning(f"[Credits] fal.ai check failed: {e}")
        return {"balance": None, "ok": True, "error": str(e)}


# ── ElevenLabs character check ─────────────────────────────────────────────────

def get_elevenlabs_credits() -> dict:
    """
    Returns { "characters_remaining": int, "ok": bool, "error": str|None }
    """
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        return {"characters_remaining": None, "ok": True, "error": "ELEVENLABS_API_KEY not set"}
    try:
        resp = requests.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": api_key},
            timeout=10
        )
        resp.raise_for_status()
        data      = resp.json()
        limit     = int(data.get("character_limit", 0))
        used      = int(data.get("character_count", 0))
        remaining = max(0, limit - used)
        return {
            "characters_remaining": remaining,
            "character_limit":      limit,
            "characters_used":      used,
            "ok":                   remaining >= ELEVENLABS_THRESHOLD,
            "error":                None
        }
    except Exception as e:
        log.warning(f"[Credits] ElevenLabs check failed: {e}")
        return {"characters_remaining": None, "ok": True, "error": str(e)}


# ── Combined status ────────────────────────────────────────────────────────────

def get_all_credits() -> dict:
    """
    Returns a combined status dict for the UI banner and email alerts.
    {
      "fal":        { "balance": 12.50, "ok": True, "error": None },
      "elevenlabs": { "characters_remaining": 45000, "ok": True, "error": None },
      "any_low":    False,
      "checked_at": "2026-06-12 14:30:00"
    }
    """
    fal  = get_fal_credits()
    el   = get_elevenlabs_credits()
    return {
        "fal":        fal,
        "elevenlabs": el,
        "any_low":    not fal["ok"] or not el["ok"],
        "checked_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    }


# ── Email alert ────────────────────────────────────────────────────────────────

def send_alert_email(subject: str, body: str) -> bool:
    """Sends an alert email via Gmail SMTP. Returns True on success."""
    if not all([EMAIL_TO, EMAIL_FROM, EMAIL_PASSWORD]):
        log.warning("[Credits] Email alert skipped — ALERT_EMAIL_* vars not configured.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

        log.info(f"[Credits] Alert email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        log.error(f"[Credits] Failed to send alert email: {e}")
        return False


def check_and_alert(job_id: str = "", property_name: str = "") -> dict:
    """
    Runs a full credit check and sends an email alert if any balance is low.
    Call this at the start and end of each job.
    Returns the full credits dict.
    """
    status = get_all_credits()

    if not status["any_low"]:
        return status

    # Build alert email
    warnings = []

    fal = status["fal"]
    if not fal["ok"] and fal["balance"] is not None:
        warnings.append(f"""
        <tr>
          <td style="padding:12px;border-bottom:1px solid #eee">
            <strong>fal.ai</strong>
          </td>
          <td style="padding:12px;border-bottom:1px solid #eee;color:#c0392b">
            ${fal['balance']:.2f} remaining
            (threshold: ${FAL_THRESHOLD:.2f})
          </td>
          <td style="padding:12px;border-bottom:1px solid #eee">
            <a href="https://fal.ai/dashboard">Top up →</a>
          </td>
        </tr>""")

    el = status["elevenlabs"]
    if not el["ok"] and el["characters_remaining"] is not None:
        warnings.append(f"""
        <tr>
          <td style="padding:12px;border-bottom:1px solid #eee">
            <strong>ElevenLabs</strong>
          </td>
          <td style="padding:12px;border-bottom:1px solid #eee;color:#c0392b">
            {el['characters_remaining']:,} characters remaining
            (threshold: {ELEVENLABS_THRESHOLD:,})
          </td>
          <td style="padding:12px;border-bottom:1px solid #eee">
            <a href="https://elevenlabs.io/app/subscription">Top up →</a>
          </td>
        </tr>""")

    if not warnings:
        return status

    context = ""
    if job_id:
        context = f"<p>This alert was triggered during job <strong>{job_id}</strong>"
        if property_name:
            context += f" ({property_name})"
        context += ".</p>"

    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#3d5a47;color:white;padding:20px;border-radius:6px 6px 0 0">
        <h2 style="margin:0">⚠ Property Video Studio — Low Credits Alert</h2>
      </div>
      <div style="background:#fff;padding:20px;border:1px solid #e2ddd6;border-top:none">
        {context}
        <p>The following services are running low and may cause jobs to fail:</p>
        <table style="width:100%;border-collapse:collapse">
          <tr style="background:#f7f5f0">
            <th style="padding:12px;text-align:left">Service</th>
            <th style="padding:12px;text-align:left">Status</th>
            <th style="padding:12px;text-align:left">Action</th>
          </tr>
          {''.join(warnings)}
        </table>
        <p style="color:#7a7469;font-size:0.85em;margin-top:20px">
          Checked at {status['checked_at']} · Property Video Studio
        </p>
      </div>
    </div>"""

    send_alert_email(
        subject=f"⚠ Low Credits Alert — Property Video Studio",
        body=body
    )

    return status


# ── CLI test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Checking credits...")
    status = get_all_credits()
    print(f"\nfal.ai:      ${status['fal'].get('balance', 'N/A')}")
    print(f"ElevenLabs:  {status['elevenlabs'].get('characters_remaining', 'N/A'):,} characters remaining")
    print(f"Any low:     {status['any_low']}")
    print(f"Checked at:  {status['checked_at']}")
