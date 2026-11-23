"""Encrypted copies by email (2026-11-23). Numbered PASS/FAIL like the other test files. Run: python3 test_backup_mail.py"""
import email, os, re, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
T = Path(tempfile.mkdtemp())
os.environ["PVS_BACKUP_DIR"] = str(T / "bk")
os.environ["PVS_BACKUP_PASS_FILE"] = str(T / "pass")
(T / "bk" / "config").mkdir(parents=True)
import backup_mail as bm
import maintenance_scheduler as ms

FAILS = 0
def check(name, cond):
    global FAILS
    print(("PASS " if cond else "FAIL ") + name)
    FAILS += 0 if cond else 1

def setpass(text, mode=0o600):
    p = T / "pass"; p.write_text(text); os.chmod(p, mode); return p
def raises(fn):
    try: fn(); return False
    except Exception: return True

p = setpass("una password lunga abbastanza")
enc = bm.encrypt(b"SECRET=abc123 some config", p)
check("BM1 encrypt then decrypt gives the original, and the ciphertext does not show the text", b"SECRET" not in enc and bm._openssl(["-d"], enc, p) == b"SECRET=abc123 some config")
p2 = T / "pass2"; p2.write_text("tutta un'altra password"); os.chmod(p2, 0o600)
check("BM2 a wrong password does not open it", raises(lambda: bm._openssl(["-d"], enc, p2)))
check("BM3 missing password file is refused", raises(lambda: bm.check_pass_file(T / "nope")))
check("BM4 a password shorter than 12 characters is refused", raises(lambda: (setpass("corta"), bm.check_pass_file(T / "pass"))))
check("BM5 a password file readable by others is refused", raises(lambda: (setpass("una password lunga abbastanza", 0o644), bm.check_pass_file(T / "pass"))))
setpass("una password lunga abbastanza")
(T / "bk" / "config" / "config_2026-11-22.tar.gz").write_bytes(b"old bundle")
(T / "bk" / "config" / "config_2026-11-23.tar.gz").write_bytes(b"NEWEST SECRET=zzz bundle")
name, data, what = bm.payload("config")
check("BM6 config payload is the NEWEST bundle, named .tar.gz.enc", data == b"NEWEST SECRET=zzz bundle" and name.endswith(".tar.gz.enc") and name.startswith("config_"))
g = T / "repo"; g.mkdir()
subprocess.run(["git", "init", "-q"], cwd=g); (g / "a.py").write_text("print(1)"); (g / ".env").write_text("KEY=1"); (g / ".gitignore").write_text(".env\n")
subprocess.run(["git", "add", "a.py", ".gitignore"], cwd=g)
bm.BASE = g
import tarfile, io
members = tarfile.open(fileobj=io.BytesIO(bm.code_tarball()), mode="r:gz").getnames()
check("BM7 code tarball holds the tracked files and NOT the ignored .env", "a.py" in members and ".env" not in members)
# mail sending (fake SMTP) -------------------------------------------------------------------------------
sent_msgs, notif = [], []
class FakeSMTP:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, *a): pass
    def sendmail(self, f, to, msg): sent_msgs.append(msg)
ms.smtplib.SMTP_SSL = FakeSMTP
ms.EMAIL_FROM, ms.EMAIL_PASSWORD = "from@x.it", "pw"
ms.load_alert_emails = lambda: ["to@x.it"]
ms.send_notification = lambda subject, body, **kw: notif.append(subject) or {"email": False, "push": False}
ok = ms.send_maintenance_alert("s", "<p>b</p>", attachments=[("f.enc", b"\x00\x01binary")])
m = email.message_from_string(sent_msgs[-1])
atts = [x for x in m.walk() if x.get_filename()]
check("BM8 send_maintenance_alert with an attachment: multipart/mixed, the file arrives byte for byte", ok and m.get_content_type() == "multipart/mixed" and atts[0].get_filename() == "f.enc" and atts[0].get_payload(decode=True) == b"\x00\x01binary")
ms.send_maintenance_alert("s", "<p>b</p>")
m2 = email.message_from_string(sent_msgs[-1])
check("BM9 without attachments the mail is exactly as before (multipart/alternative, no file)", m2.get_content_type() == "multipart/alternative" and not [x for x in m2.walk() if x.get_filename()])
bm.BASE = HERE
sent_msgs.clear(); notif.clear()
check("BM10 config mail: sent once, attachment decrypts to the bundle, no alert raised", bm.send("config") is True and len(sent_msgs) == 1 and not notif and
      bm._openssl(["-d"], [x for x in email.message_from_string(sent_msgs[0]).walk() if x.get_filename()][0].get_payload(decode=True), T / "pass") == b"NEWEST SECRET=zzz bundle")
sent_msgs.clear(); notif.clear()
os.remove(T / "pass")
check("BM11 no password file: nothing is sent and ONE alert goes to the dashboard", bm.send("config") is False and not sent_msgs and len(notif) == 1 and "NON riuscito" in notif[0])
setpass("una password lunga abbastanza"); sent_msgs.clear(); notif.clear()
big = bm.MAX_MB; bm.MAX_MB = 0
check("BM12 a file over the size limit is not sent and raises an alert", bm.send("config") is False and not sent_msgs and len(notif) == 1)
bm.MAX_MB = big; notif.clear(); ms.load_alert_emails = lambda: []
check("BM13 no recipient configured: not sent, alert raised (never a silent failure)", bm.send("config") is False and len(notif) == 1)
ms.load_alert_emails = lambda: ["to@x.it"]; notif.clear(); sent_msgs.clear()
class D(datetime):
    d = 3
    @classmethod
    def now(cls, tz=None): return datetime(2026, 12, cls.d, 4, 30)
bm.datetime = D
calls = []; real_send = bm.send; bm.send = lambda k: calls.append(k) or True
D.d = 3; bm.main(["x", "auto"]); a = list(calls); calls.clear()
D.d = 15; bm.main(["x", "auto"]); b = list(calls)
check("BM14 auto mode: day 3 sends config and code, day 15 only config", a == ["config", "code"] and b == ["config"])
src = (HERE / "backup_mail.py").read_text()
check("BM15 backup_mail never deletes or writes files (no rmtree/remove/unlink/write_*/open for writing; the only tarfile write is to memory)", not re.search(r"rmtree|\.unlink|os\.remove|\.write_text|\.write_bytes", src) and not [l for l in src.splitlines() if re.search(r"\bopen\(", l) and "tarfile.open(fileobj=buf" not in l])
check("BM16 one mail sender, one recipient reader: it calls maintenance_scheduler, no second SMTP code", "send_maintenance_alert" in src and "smtplib" not in src)
check("BM17 the password is never printed or put in a mail body", "print(" not in src and "read_text" in src and "body" in src and "p.read_text" not in src.split("body =")[1])
print(f"test_backup_mail FAILS {FAILS}")
import shutil; shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if FAILS else 0)
