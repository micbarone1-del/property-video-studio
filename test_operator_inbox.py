"""Operator inbox (dashboard notifications) + the daily-cap alert. 2026-11-20. Source-level + real functions (no web server needed).
Run (repo folder):  python3 test_operator_inbox.py"""
import ast, asyncio, json, os, sys, tempfile, threading, types
from datetime import datetime
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="inbox_")
os.environ["PVS_DATA_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operator_inbox as oi

R = []
def chk(n, c):
    R.append(bool(c)); print(("PASS " if c else "FAIL ") + n)

# OI1-OI6: the inbox module itself
a1 = oi.add("Job fallito", "<p>Il job <b>x</b> e' fallito</p>", job_id="j1")
a2 = oi.add("Nuovo job", "arrivato", job_id="j2", level="info")
a3 = oi.add("Maintenance", "disco quasi pieno")
chk("OI1 add returns ids; html is stripped to plain text", a1 and a2 and a3 and oi.snapshot({"j1": {}, "j2": {}})["actions"][-1]["text"] == "Il job x e' fallito")
s = oi.snapshot({"j1": {"property_name": "Casa A"}, "j2": {}})
chk("OI2 actions newest first, info kept apart", [e["id"] for e in s["actions"]] == [a3, a1] and [e["id"] for e in s["info"]] == [a2])
chk("OI3 the job name is attached", s["actions"][1]["job_name"] == "Casa A")
jobs = {"j1": {"released": True}}
chk("OI4 an entry about a released job closes by itself; one with no job stays", [e["id"] for e in oi.snapshot(jobs)["actions"]] == [a3])
chk("OI4b rejected job closes; a job that no longer exists closes", not any(e["job_id"] == "j1" for e in oi.snapshot({"j1": {"failure_code": "rejected_by_operator"}})["actions"]) and not any(e["job_id"] == "j1" for e in oi.snapshot({})["actions"]))
c = oi.add("Tetto", "x", job_id="c1", kind="cap_wait")
w = {"c1": {"status": "draft", "auto_start": {"state": "waiting"}}}
chk("OI5 cap_wait stays open while waiting, closes when the job starts", any(e["id"] == c for e in oi.snapshot(w)["actions"]) and not any(e["id"] == c for e in oi.snapshot({"c1": {"status": "queued", "auto_start": {"state": "started"}}})["actions"]))
chk("OI6 Fatto closes one entry; closing it twice is refused; unknown id refused", oi.mark_done(a3) is True and oi.mark_done(a3) is False and oi.mark_done("nope") is False and not any(e["id"] == a3 for e in oi.snapshot({})["actions"]))
chk("OI7 close all info", oi.mark_all_info_done() == 1 and oi.snapshot({})["info"] == [])
Path(tmp, "operator_inbox.json").write_text("{not json")
chk("OI8 a corrupt file never raises: snapshot empty, add starts again", oi.snapshot({}) == {"actions": [], "info": []} and oi.add("x", "y") is not None)
for i in range(oi.MAX_ENTRIES + 40):
    oi.add("n%d" % i, "t")
chk("OI9 the file stays bounded", len(json.loads(Path(tmp, "operator_inbox.json").read_text())) <= oi.MAX_ENTRIES)
ts = [threading.Thread(target=oi.add, args=("p%d" % i, "t")) for i in range(30)]
[t.start() for t in ts]; [t.join() for t in ts]
n_before = len(json.loads(Path(tmp, "operator_inbox.json").read_text()))
chk("OI10 30 simultaneous adds: the file is still valid JSON", n_before > 0)

# OI11-OI16: wiring (source level on the real files)
ms = open("maintenance_scheduler.py").read()
ap = open("api_server.py").read()
pg = open("operator_page.html").read()
chk("OI11 send_notification records EVERY alert before mail/push (single writer)", ms.index("operator_inbox.add(") < ms.index("email_sent = send_maintenance_alert(") and "job_id=job_id, level=level, kind=kind" in ms.replace("\n", " ") or "operator_inbox.add(subject, push_message or body_html, job_id=job_id, level=level, kind=kind)" in ms)
def _callers(src, name):   # real calls only (a docstring may mention the name)
    return [n.lineno for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and (getattr(n.func, "attr", None) == name or getattr(n.func, "id", None) == name)]
chk("OI12 nobody else sends mail/push around it (only send_notification calls the senders)", len(_callers(ms, "send_maintenance_alert")) == 1 and len(_callers(ms, "send_ntfy_push")) == 1 and not _callers(ap, "send_maintenance_alert") and not _callers(ap, "send_ntfy_push"))
chk("OI13 _notify_operator passes the job id, level and kind", "job_id=job_id, level=level, kind=kind" in ap)
chk("OI14 the new-job alert is information, not an action", 'tags=["inbox_tray"], job_id=job_id, level="info"' in ap)
chk("OI15 /operator/status carries the inbox; Fatto endpoints exist", '"inbox": _operator_inbox_snapshot()' in ap and '"/operator/inbox/{entry_id}/done"' in ap and '"/operator/inbox-info-done"' in ap)
chk("OI16 the page paints the inbox on top, before the cards", pg.index('id="inbox"') < pg.index('id="cards"') and "paintInbox(d.inbox)" in pg and "Da fare (" in pg)
chk("OI17 the data file is ignored by git", "operator_inbox.json" in open(".gitignore").read())

# CAP1-CAP5: the real _auto_start_tick, wait branch, with stubs
tree = ast.parse(ap)
fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_auto_start_tick")
code = ast.get_source_segment(ap, fn)
calls = []
class Log:
    def info(self, *a): pass
    warning = info
actions = []
au = types.ModuleType("auto_start"); au.enabled = lambda: True; au.decide = lambda jobs, now, check: list(actions)
sys.modules["auto_start"] = au
sys.modules["draft_check"] = types.ModuleType("draft_check")
async def _noop(*a, **k): pass
async def _notify(jid, event, **kw): calls.append((jid, event, kw.get("kind"), kw.get("priority")))
JOBS = {"d1": {"status": "draft", "source": "relinx", "property_name": "Casa D", "created_at": "2026-11-20T10:00:00"}}
ns = {"JOBS": JOBS, "JOBS_DIR": tmp, "_AUTO_START_CHECKED": {}, "_auto_release_tick": _noop, "_release_ready_tick": _noop, "_save_job": lambda j: None,
      "_notify_operator": _notify, "log": Log(), "datetime": datetime, "asyncio": asyncio, "luma_resolution": lambda: "1080p", "BackgroundTasks": object,
      "start_generation_for_draft": _noop}
exec(code, ns)
tick = ns["_auto_start_tick"]
def run(): asyncio.run(tick())
actions[:] = [{"job_id": "d1", "action": "wait", "reason": "daily cap: 25.0 EUR committed + 8.7 > 30 EUR"}]
run()
chk("CAP1 first time held by the cap: operator told once, kind cap_wait, high priority", calls == [("d1", "Daily cap", "cap_wait", "high")] and JOBS["d1"]["auto_start"].get("cap_alerted") is True)
actions[:] = [{"job_id": "d1", "action": "wait", "reason": "daily cap: 26.5 EUR committed + 8.7 > 30 EUR"}]
run(); run()
chk("CAP2 the reason text changes (money moves) but there is still ONE alert", len(calls) == 1 and "26.5" in JOBS["d1"]["auto_start"]["reason"] and JOBS["d1"]["auto_start"].get("cap_alerted") is True)
actions[:] = [{"job_id": "d1", "action": "wait", "reason": "2 jobs already generating (limit 2)"}]
run()
chk("CAP3 waiting for a free slot is silent", len(calls) == 1)
JOBS["d2"] = {"status": "draft", "source": "relinx", "property_name": "Casa E", "created_at": "2026-11-20T11:00:00"}
actions[:] = [{"job_id": "d2", "action": "wait", "reason": "2 jobs already generating (limit 2)"}]
run()
chk("CAP4 a job waiting only for a slot is never alerted", len(calls) == 1 and "cap_alerted" not in JOBS["d2"]["auto_start"])
actions[:] = [{"job_id": "d2", "action": "wait", "reason": "daily cap: 30.0 EUR committed + 8.7 > 30 EUR"}]
run()
chk("CAP5 a second job held by the cap gets its own single alert", len(calls) == 2 and calls[1][0] == "d2")

print("\nRESULT: %d PASS / %d FAIL" % (sum(R), len(R) - sum(R)))
sys.exit(0 if all(R) else 1)
