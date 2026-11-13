"""test_release_rule.py (2026-11-13): the ONE 'releasable' rule and the 'ready to release' notice. No server, no network."""
import sys
from pathlib import Path
import release_rule as rr

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(info)))
    fails += 0 if ok else 1

OK = {"source": "relinx", "status": "done", "awaiting_scenes": []}
check("RR1 a finished clean Relinx job is releasable", rr.releasable(OK))
check("RR2 not done -> no", not rr.releasable(dict(OK, status="running")))
check("RR3 already released -> no", not rr.releasable(dict(OK, released=True)))
check("RR4 other source -> no", not rr.releasable(dict(OK, source="web")))
check("RR5 needs the operator -> no", not rr.releasable(dict(OK, needs_operator={"why": "x"})))
check("RR6 delivery blocked -> no", not rr.releasable(dict(OK, delivery_blocked=True)))
check("RR7 a rejected scene left (dict form) -> no", not rr.releasable(dict(OK, awaiting_scenes={"rejected": [3], "flagged": [], "failed": []})))
check("RR8 empty awaiting dict -> yes", rr.releasable(dict(OK, awaiting_scenes={"rejected": [], "flagged": [], "failed": []})))
check("RR9 old list form with items -> no", not rr.releasable(dict(OK, awaiting_scenes=[1])))

jobs = {"old1": dict(OK), "old2": dict(OK), "run": dict(OK, status="running")}
seen = set()
check("RR10 baseline: old finished jobs are remembered, nobody is notified", rr.new_notices(jobs, seen, True) == [] and seen == {"old1", "old2"}, seen)
jobs["run"]["status"] = "done"
check("RR11 a job that finishes later is reported once", rr.new_notices(jobs, seen, False) == ["run"])
check("RR12 and not again", rr.new_notices(jobs, seen, False) == [])
jobs["blocked"] = dict(OK, awaiting_scenes={"rejected": [1], "flagged": [], "failed": []})
check("RR13 a done job with a scene waiting is not reported", rr.new_notices(jobs, seen, False) == [] and "blocked" not in seen)

src = Path("api_server.py").read_text()
check("RR14 the automatic release uses the same rule", "release_rule.releasable(j)" in src)
check("RR15 the notice tick runs in the periodic tick", "await _release_ready_tick()" in src)
check("RR16 the notice only in manual release mode", '_release_mode() != "manual"' in src)
check("RR17 the old inline rule is gone (one place)", 'not j.get("delivery_blocked")' not in src.split("async def _auto_release_tick")[1].split("async def _auto_start_tick")[0])
sys.exit(1 if fails else 0)
