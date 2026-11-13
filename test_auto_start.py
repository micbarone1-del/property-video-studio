import os, inspect
from datetime import datetime, timedelta
import auto_start as au
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)
now = datetime(2026, 11, 6, 12, 0, 0)
iso = lambda h: (now - timedelta(hours=h)).isoformat()
ok = lambda jid: [("INFO", "C14", "x")]
bad = lambda jid: [("FAIL", "C3", "voice too short")]
def drafts(*ids):
    return {i: {"source": "relinx", "status": "draft", "created_at": iso(n)} for n, i in enumerate(ids)}
os.environ.pop("PVS_AUTO_START", None)
chk("S1 off by default", au.enabled() is False)
os.environ["PVS_AUTO_START"] = "1"; chk("S2 on with 1", au.enabled() is True)
chk("S3 defaults: cap 30, max 2", au.cap_eur() == 30.0 and au.max_active() == 2)
a = au.decide(drafts("a"), now, ok, cap=30, max_act=2)
chk("S4 clean draft -> start", [x["action"] for x in a] == ["start"])
a = au.decide(drafts("a"), now, bad, cap=30, max_act=2)
chk("S5 draft with a FAIL -> refuse with the reason", a[0]["action"] == "refuse" and "C3" in a[0]["reason"])
a = au.decide(drafts("a", "b", "c"), now, ok, cap=100, max_act=2)
chk("S6 concurrency: 2 start, the 3rd waits", [x["action"] for x in a] == ["start", "start", "wait"] or sorted(x["action"] for x in a) == ["start", "start", "wait"])
jobs = drafts("a")
jobs["r1"] = {"source": "relinx", "status": "running", "created_at": iso(1)}
jobs["r2"] = {"source": "relinx", "status": "running", "created_at": iso(1)}
chk("S7 two already running -> wait", au.decide(jobs, now, ok, cap=100, max_act=2)[0]["action"] == "wait")
jobs = drafts("a")
jobs["d1"] = {"source": "relinx", "status": "done", "created_at": iso(3), "cost_actual": {"grand_total_eur": 25.0}}
a = au.decide(jobs, now, ok, cap=30, max_act=2)
chk("S8 daily cap: 25 spent + 8.7 > 30 -> wait", a[0]["action"] == "wait" and "cap" in a[0]["reason"])
jobs["d1"]["created_at"] = iso(30)
chk("S9 spend older than 24 h does not count -> start", au.decide(jobs, now, ok, cap=30, max_act=2)[0]["action"] == "start")
j2 = {"x": {"source": "relinx", "status": "draft", "created_at": iso(1), "auto_start": {"state": "refused"}}}
chk("S10 an already refused draft is not evaluated again", au.decide(j2, now, ok) == [])
j3 = {"x": {"source": None, "status": "draft", "created_at": iso(1)}}
chk("S11 manual drafts are never auto-started", au.decide(j3, now, ok) == [])
j4 = {"q": {"source": "relinx", "status": "queued", "created_at": iso(1)}}
chk("S12 a partner job still being prepared (queued, not started by us) is not 'generating'", au.active_count(j4) == 0)
j5 = {"q": {"source": "relinx", "status": "queued", "created_at": iso(1), "auto_start": {"state": "started"}}}
chk("S13 an auto-started queued job IS generating", au.active_count(j5) == 1)
j6 = {"o": {"source": "relinx", "status": "draft", "created_at": iso(2)}, "n": {"source": "relinx", "status": "draft", "created_at": iso(1)}}
chk("S14 oldest draft first", [x["job_id"] for x in au.decide(j6, now, ok, cap=100, max_act=5)] == ["o", "n"])
os.environ["PVS_AUTO_START_NOT_BEFORE"] = (now - timedelta(minutes=90)).isoformat()
j7 = {"old": {"source": "relinx", "status": "draft", "created_at": iso(3)}, "new": {"source": "relinx", "status": "draft", "created_at": iso(1)}}
chk("S14b drafts older than PVS_AUTO_START_NOT_BEFORE are ignored", [x["job_id"] for x in au.decide(j7, now, ok, cap=100, max_act=5)] == ["new"])
os.environ.pop("PVS_AUTO_START_NOT_BEFORE")
src = open("api_server.py").read()
chk("S15 wiring: tick reuses the button's path and the draft_check + duplicate rules",
    "await start_generation_for_draft(jid, bt)" in src and "draft_check.check_job(jid" in src and "gial_start.same_listing_done(jid" in src)
chk("S16 wiring: startup only when the switch is on; page exempt from the key (data needs the key)",
    "if auto_start.enabled():" in src and '"/operator-page"' in src and '@app.get("/operator/status")' in src)
html = open("operator_page.html", encoding="utf-8").read()
chk("S17 page sends the access key and asks only on 403", "X-Access-Key" in html and "r.status === 403" in html)
chk("S19 status carries the detail of the stops (not the number of dict keys)", '"stops": len(det)' in src and '"stops_detail": det' in src)
chk("S20 page: approve posts the app's own approval JSON with the key; redo asks for confirmation", "approved_scenes: approved, redo_scenes: redo" in html and "/approve'" in html and "confirm(" in html)
chk("S21 page: clip previews and download links use the existing endpoints", "/clip/' + s.scene + '/preview" in html and "/preview\"" in html and "/download\"" in html)
chk("S22 release mode: default manual, switch endpoint, auto release uses the operator's own release path",
    'RELEASE_MODE_FILE = JOBS_DIR / "_release_mode.json"' in src and '"/operator/release-mode"' in src and "await release_job(jid)" in src
    and 'return m if m in ("manual", "auto") else "manual"' in src)
import release_rule as _rr   # 2026-11-13: the rule moved to ONE module (release_rule.py), shared with the 'ready to release' notice
_okj = {"source": "relinx", "status": "done", "awaiting_scenes": {"rejected": [], "flagged": [], "failed": []}}
chk("S23 auto release never touches a job that needs the operator or has stops (an empty stops dict is NOT a stop)",
    "release_rule.releasable(j)" in src and _rr.releasable(_okj) and not _rr.releasable(dict(_okj, needs_operator={"x": 1}))
    and not _rr.releasable(dict(_okj, awaiting_scenes={"rejected": [2], "flagged": [], "failed": []})))
chk("S24 page: release switch and per-job release button with confirmation", "setRelease(" in html and "releaseJob(" in html and "Consegna all" in html)
import py_compile; py_compile.compile("api_server.py", doraise=True)
chk("S18 api_server compiles", True)
print("FAILS", F)
