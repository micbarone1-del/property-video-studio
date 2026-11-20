"""2026-11-20: ONE notification for a refused partner request that looks like a real mistake (partner_api.AuthRefusalAlerts + the hook in api_server).
No network, no mail: the decision logic is pure and the hook is checked on the source (fastapi is not needed)."""
import os, sys, tempfile
os.environ.setdefault("PVS_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.getcwd())
import partner_api
ok = True
def chk(name, cond, info=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if (info and not cond) else ""))
    if not cond: ok = False
A = partner_api.AuthRefusalAlerts
a = A()
chk("PA1 a strong refusal notifies at the first occurrence", a.note("s1", True, now=1000.0) is True)
chk("PA2 the same signature does not notify again inside the cooldown", a.note("s1", True, now=1000.0 + 3600) is False)
chk("PA3 after the cooldown it notifies again", a.note("s1", True, now=1000.0 + 21600 + 1) is True)
a = A()
r = [a.note("w", False, now=2000.0 + i) for i in range(3)]
chk("PA4 a weak refusal notifies only at the third hit inside the window", r == [False, False, True], r)
a = A()
r = [a.note("w", False, now=3000.0), a.note("w", False, now=3000.0 + 1000), a.note("w", False, now=3000.0 + 2000)]
chk("PA5 hits older than the window do not add up", r == [False, False, False], r)
a = A()
r = [a.note(f"x{i}", True, now=4000.0 + i) for i in range(6)]
chk("PA6 at most 4 notifications per hour in the whole process, whatever the signatures", r == [True, True, True, True, False, False], r)
chk("PA7 the cap frees up after an hour", a.note("x9", True, now=4000.0 + 3700) is True)
live = partner_api.create_partner("TEST alert")
good = live["api_key"]
chk("PA8 a key of the exact shape of ours that matches nothing is strong", partner_api.auth_refusal_is_strong("pvs_" + "a" * 43, "unknown") is True)
chk("PA9 a short or foreign key is weak", partner_api.auth_refusal_is_strong("pvs_sbagliata", "unknown") is False and partner_api.auth_refusal_is_strong("", "unknown") is False)
partner_api.deactivate_partner(live["partner_id"])
known = partner_api.identify_partner_key(good)
chk("PA10 a key we issued and switched off is strong, whatever its shape", known.endswith("(inactive)") and partner_api.auth_refusal_is_strong("x", known) is True, known)
src = open("api_server.py", encoding="utf-8").read()
i = src.index("def _alert_auth_refusal"); j = src.index("async def get_current_partner")
hook = src[i:j]
chk("PA11 the hook never raises (whole body in try/except), runs the notification in its own thread and marks it high priority", "try:" in hook and "except Exception" in hook and "threading.Thread" in hook and "daemon=True" in hook and '"priority": "high"' in hook)
chk("PA12 the notification text never carries the key", "raw_key" not in hook and "api_key" not in hook)
body = src[j:j + 2200]
chk("PA13 both 401 branches call the hook BEFORE raising, and the answers are unchanged",
    body.count("_alert_auth_refusal(") == 2 and body.index("_alert_auth_refusal(") < body.index("Missing or invalid Authorization header")
    and body.rindex("_alert_auth_refusal(") < body.index("Invalid or inactive API key") and "Invalid or inactive API key" in body and "Missing or invalid Authorization header" in body)
chk("PA14 the hook is NOT called on the success path", body.rindex("_alert_auth_refusal(") < body.index("return partner"))
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
