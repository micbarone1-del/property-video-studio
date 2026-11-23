"""backup_mail.py - encrypted copy of the config/data files (weekly) and of the code (monthly) sent by email to the alert address, so a copy exists OUTSIDE the server. 2026-11-23.
  python3 backup_mail.py config     the newest config bundle made by the nightly backup (*.json of the app folder + .env), encrypted
  python3 backup_mail.py code       the tracked source files (git ls-files), encrypted
  python3 backup_mail.py auto       config always; the code too when today is day 1-7 of the month (cron runs it every Sunday, so: first Sunday = both)
Encryption: AES-256 with a password read from a root-only file (PVS_BACKUP_PASS_FILE, default /root/.pvs_backup_pass; the password is chosen by the operator and never goes through the chat).
Before sending, the encrypted bytes are decrypted again and compared with the original; any problem (no password file, too short, wrong mode, too big, mail refused) raises an alert in the dashboard inbox.
Reads only: never writes to or deletes anything in jobs/ or anywhere else. The single mail sender is maintenance_scheduler.send_maintenance_alert (same SMTP login and recipients as the alerts)."""
import os
import subprocess
import sys
import tarfile
import io
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
MAX_MB = 20
MIN_PASS_CHARS = 12
DECRYPT_HELP = "openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in FILE.enc -out FILE.tar.gz"


def backup_dir() -> Path:
    return Path(os.environ.get("PVS_BACKUP_DIR") or "/var/backups/pvs_jobs")


def pass_file() -> Path:
    return Path(os.environ.get("PVS_BACKUP_PASS_FILE") or "/root/.pvs_backup_pass")


def check_pass_file(p: Path) -> None:
    if not p.is_file():
        raise RuntimeError(f"password file {p} does not exist")
    if p.stat().st_mode & 0o077:
        raise RuntimeError(f"password file {p} must be readable by root only (chmod 600)")
    if len(p.read_text().rstrip("\n")) < MIN_PASS_CHARS:
        raise RuntimeError(f"password in {p} is shorter than {MIN_PASS_CHARS} characters")


def _openssl(args, data: bytes, p: Path) -> bytes:
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", *args, "-pass", f"file:{p}"], input=data, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("openssl failed: " + r.stderr.decode(errors="replace")[:200])
    return r.stdout


def encrypt(data: bytes, p: Path) -> bytes:
    check_pass_file(p)
    enc = _openssl(["-salt"], data, p)
    if _openssl(["-d"], enc, p) != data:     # self-check: what we send must open with the same password and give the original back
        raise RuntimeError("self-check failed: the encrypted copy does not decrypt to the original")
    return enc


def newest_config() -> Path:
    files = sorted((backup_dir() / "config").glob("config_*.tar.gz"))
    if not files:
        raise RuntimeError(f"no config bundle found in {backup_dir() / 'config'} (is the nightly backup running?)")
    return files[-1]


def code_tarball() -> bytes:
    names = subprocess.run(["git", "ls-files", "-z"], cwd=BASE, capture_output=True, check=True).stdout.split(b"\0")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n in filter(None, names):
            f = BASE / n.decode()
            if f.is_file():
                t.add(str(f), arcname=n.decode())
    return buf.getvalue()


def payload(kind: str):
    stamp = datetime.now().strftime("%Y-%m-%d")
    if kind == "config":
        f = newest_config()
        return f"config_{stamp}.tar.gz.enc", f.read_bytes(), f"i file di configurazione e dati e il file .env (copia del {f.name})"
    if kind == "code":
        return f"codice_{stamp}.tar.gz.enc", code_tarball(), "il codice del programma (i file tracciati da git)"
    raise ValueError(kind)


def send(kind: str) -> bool:
    import maintenance_scheduler as ms
    try:
        name, data, what = payload(kind)
        enc = encrypt(data, pass_file())
        if len(enc) > MAX_MB * 1024 * 1024:
            raise RuntimeError(f"the encrypted file is {len(enc) // 1048576} MB, over the {MAX_MB} MB limit for an email")
        body = (f"<p>Copia cifrata fuori dal server: {what}.</p><p>Per aprirla serve la password scelta da te. Su un terminale: <code>{DECRYPT_HELP}</code></p>"
                f"<p>Dimensione: {len(enc) // 1024} KB.</p>")
        if not ms.send_maintenance_alert(f"Property Video Studio - copia cifrata ({kind}) {datetime.now():%Y-%m-%d}", body, attachments=[(name, enc)]):
            raise RuntimeError("the mail was not sent (no recipients, no SMTP login, or the mail server refused it)")
        return True
    except Exception as e:
        ms.send_notification(f"Backup per email NON riuscito ({kind})", f"<p>{e}</p>", push_message=f"Backup per email non riuscito ({kind}): {e}", priority="high", tags=["warning"], level="action")
        return False


def main(argv) -> int:
    mode = argv[1] if len(argv) > 1 else "auto"
    kinds = ["config"] + (["code"] if datetime.now().day <= 7 else []) if mode == "auto" else [mode]
    return 0 if all([send(k) for k in kinds]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
