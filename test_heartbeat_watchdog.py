"""Heartbeat watchdog (2026-11-23). Numbered PASS/FAIL. Run: python3 test_heartbeat_watchdog.py"""
import json, os, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
T = tempfile.mkdtemp(); os.environ["PVS_DATA_DIR"] = T
import heartbeat_watchdog as w
FAILS = 0
def check(name, cond):
    global FAILS
    print(("PASS " if cond else "FAIL ") + name); FAILS += 0 if cond else 1
sf = Path(T) / "ms.json"; now = datetime.now()
def stat(minutes, at=None): sf.write_text(json.dumps({"timestamp": ((at or now) - timedelta(minutes=minutes)).isoformat(), "checks": []}))
mails = []; ok_send = lambda s, b: (mails.append((s, b)) or True); bad_send = lambda s, b: False
H = 3600
check("W1 decide: 29 min old = ok", w.decide(29, None, 0, 999) == "ok")
check("W2 decide: 31 min old, never mailed = mail", w.decide(31, None, 10 * H, 999) == "mail")
check("W3 decide: stale, mailed 5 h ago = wait", w.decide(60, 10 * H - 5 * H, 10 * H, 999) == "wait")
check("W4 decide: stale, mailed 7 h ago = mail again", w.decide(60, 10 * H - 7 * H, 10 * H, 999) == "mail")
check("W5 decide: no status file and app up 5 min = ok (fresh start)", w.decide(None, None, 0, 5) == "ok")
check("W6 decide: no status file and app up 40 min = mail", w.decide(None, None, 0, 40) == "mail")
stat(5); check("W7 fresh heartbeat: ok, no mail", w.tick(now, ok_send, sf) == "ok" and not mails)
stat(45); check("W8 45 min old: one mail", w.tick(now, ok_send, sf) == "mailed" and len(mails) == 1 and "45 minuti" in mails[0][1])
check("W9 a minute later still stale: no second mail", w.tick(now + timedelta(minutes=1), ok_send, sf) == "wait" and len(mails) == 1)
stat(45, now + timedelta(hours=7) - timedelta(minutes=0)); check("W10 7 hours later still stale: second mail", w.tick(now + timedelta(hours=7), ok_send, sf) == "mailed" and len(mails) == 2)
stat(2, now + timedelta(hours=8)); check("W11 recovered: state reset", w.tick(now + timedelta(hours=8), ok_send, sf) == "ok" and w._load() == {})
stat(60, now + timedelta(hours=8, minutes=1)); check("W12 a new outage right after mails at once", w.tick(now + timedelta(hours=8, minutes=1), ok_send, sf) == "mailed" and len(mails) == 3)
os.remove(w.state_file()); stat(60)
check("W13 mail send fails: not recorded, retried at the next tick", w.tick(now, bad_send, sf) == "mail-failed" and w._load() == {} and w.tick(now, ok_send, sf) == "mailed")
check("W14 broken status file never raises", (sf.write_text("{{{") or True) and w.tick(now, ok_send, sf) in ("ok", "wait", "mailed", "error"))
check("W15 corrupt state file never raises", (w.state_file().write_text("zzz") or True) and w.tick(now, ok_send, sf) in ("ok", "wait", "mailed", "error"))
src = (HERE / "api_server.py").read_text()
check("W16 the app loop calls the watchdog from the existing loop (no second loop)", "heartbeat_watchdog" in src and src.count("asyncio.create_task(_auto_start_loop())") == 1)
check("W17 one reader: the module uses health_kpi.heartbeat_age_min and has no own timestamp parsing", "health_kpi.heartbeat_age_min" in (HERE / "heartbeat_watchdog.py").read_text() and "fromisoformat" not in (HERE / "heartbeat_watchdog.py").read_text())
print(f"test_heartbeat_watchdog FAILS {FAILS}"); sys.exit(1 if FAILS else 0)
