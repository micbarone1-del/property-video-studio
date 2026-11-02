"""Retention policy (2026-11-02). Numbered PASS/FAIL, same format as the other test files. Run: python3 test_retention_policy.py
Everything happens in a temporary folder; no real job is touched, nothing is deleted by this test (it only asks the policy WHICH folders it would delete)."""
import json, os, re, sys, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path
import retention_policy as rp
fails = 0
def check(n, c):
    global fails
    print("PASS" if c else "FAIL", n)
    fails += 0 if c else 1

GB = 1024 ** 3
NOW = datetime.utcnow()
tmp = Path(tempfile.mkdtemp())

def mk(name, age_days, size_mb=1, status="done", keep=None):
    d = tmp / name
    d.mkdir()
    (d / "clip.mp4").write_bytes(b"x" * 1024)           # real size is irrelevant: sizes are injected below
    meta = {"status": status}
    if keep is not None:
        meta["keep"] = keep
    mp = d / "job_meta.json"
    mp.write_text(json.dumps(meta))
    t = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(mp, (t, t))
    return d

mk("old30", 30); mk("old20", 20); mk("old16", 16); mk("recent10", 10); mk("kept40", 40, keep=True); mk("busy50", 50, status="running")
(tmp / "_test_scratch").mkdir(); (tmp / "_test_scratch" / "f").write_bytes(b"x")
# every folder "weighs" 10 GB for the projection (dir_size_bytes is replaced), disk = 100 GB
rp.dir_size_bytes = lambda d: 10 * GB

# RT1 disk below the high-water mark: nothing is selected, however old the jobs are
check("RT1 disk at 79%: nothing deleted even with 40-50 day old jobs", rp.select_for_eviction(tmp, usage=(100 * GB, 79 * GB), now=NOW) == [])
# RT2 above: oldest first, only unprotected, stops at LOW (65): from 85 GB, three folders of 10 GB bring it to 55 <= 65 after 2 (85->75->65)
sel = rp.select_for_eviction(tmp, usage=(100 * GB, 85 * GB), now=NOW)
check("RT2 disk at 85%: the idlest unprotected first, and it stops as soon as the projection reaches 65%", sel == ["old30", "old20"])
check("RT3 a kept job, a running job, a job younger than 14 days and _test_scratch are never selected",
      not {"kept40", "busy50", "recent10", "_test_scratch"} & set(rp.select_for_eviction(tmp, usage=(100 * GB, 99 * GB), now=NOW)))
all_sel = rp.select_for_eviction(tmp, usage=(100 * GB, 99 * GB), now=NOW)
check("RT4 under heavy pressure still only the 3 old unprotected ones, oldest first", all_sel == ["old30", "old20", "old16"])
check("RT5 exactly at the high-water mark (80%) the cleanup starts", rp.select_for_eviction(tmp, usage=(100 * GB, 80 * GB), now=NOW) != [])
# RT6 in-memory flags win: a job whose meta says nothing but whose JOBS entry has keep
check("RT6 keep from the in-memory job is honoured", "old30" not in rp.select_for_eviction(tmp, jobs={"old30": {"keep": True, "status": "done"}}, usage=(100 * GB, 99 * GB), now=NOW))
# RT7 orphan folder (no job_meta.json): folder mtime decides
o = tmp / "orphan"; o.mkdir(); t = (NOW - timedelta(days=60)).timestamp(); os.utime(o, (t, t))
check("RT7 an old orphan folder without job_meta.json is a candidate, oldest of all", rp.select_for_eviction(tmp, usage=(100 * GB, 99 * GB), now=NOW)[0] == "orphan")
# RT8 wiring: ONE rule, no leftover 7-day constant in either caller
api = open("api_server.py").read(); ms = open("maintenance_scheduler.py").read()
check("RT8 api_server and maintenance_scheduler both use retention_policy; no 7-day cutoff left", "retention_policy" in api and "retention_policy" in ms and "timedelta(days=7)" not in api and "JOB_RETENTION_DAYS" not in ms)
check("RT9 the scheduler's disk warn level equals the cleanup's high-water mark", re.search(r"DISK_WARN_PCT\s*=\s*(\d+)", ms).group(1) == str(int(rp.HIGH_PCT)))
check("RT10 'keep' endpoint exists, is saved with the job, and is listed", '@app.post("/jobs/{job_id}/keep")' in api and 'JOBS[job_id]["keep"] = bool(keep)' in api and '"keep":         bool(job.get("keep"))' in api)
ui = open("ui.html").read()
check("RT11 the library has the Tieni/Tenuto button wired to the endpoint", "setJobKeep" in ui and "'/jobs/' + jobId + '/keep'" in ui)
check("RT12 the cleanup loop deletes only folders chosen by the policy", "if job_dir.name in _evict:" in api)
print("ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(1 if fails else 0)
