"""patch_mail.py - lets maintenance_scheduler.send_maintenance_alert carry attachments (default: none, behaviour unchanged). Every anchor must occur exactly once; a second run refuses."""
import sys
from pathlib import Path
p = Path("maintenance_scheduler.py"); s = p.read_text()
if "attachments=None" in s:
    print("SKIP: already patched"); sys.exit(0)
pairs = [
 ("from email.mime.text import MIMEText\n", "from email.mime.text import MIMEText\nfrom email.mime.base import MIMEBase\nfrom email import encoders\n"),
 ("def send_maintenance_alert(subject: str, body_html: str) -> bool:", "def send_maintenance_alert(subject: str, body_html: str, attachments=None) -> bool:   # attachments: [(file name, bytes)] (2026-11-23, backup_mail.py)"),
 ('        msg = MIMEMultipart("alternative")\n        msg["Subject"] = subject\n        msg["From"] = EMAIL_FROM\n        msg["To"] = ", ".join(recipients)\n        msg.attach(MIMEText(body_html, "html"))\n',
  '        msg = MIMEMultipart("mixed" if attachments else "alternative")\n        msg["Subject"] = subject\n        msg["From"] = EMAIL_FROM\n        msg["To"] = ", ".join(recipients)\n        msg.attach(MIMEText(body_html, "html"))\n        for _name, _data in (attachments or []):\n            _part = MIMEBase("application", "octet-stream")\n            _part.set_payload(_data)\n            encoders.encode_base64(_part)\n            _part.add_header("Content-Disposition", "attachment", filename=_name)\n            msg.attach(_part)\n'),
]
for old, new in pairs:
    if s.count(old) != 1:
        print(f"FAIL: anchor found {s.count(old)} times: {old[:60]!r}"); sys.exit(1)
    s = s.replace(old, new)
p.write_text(s); print("OK   maintenance_scheduler.py")
