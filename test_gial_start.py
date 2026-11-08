"""gial_start.py (2026-11-02): one job at a time, drafts only, stops on failure. Fake HTTP, no sleeping. Run: python3 test_gial_start.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gial_start as gs
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); fails += 0 if c else 1
class R:
    def __init__(s, code, js=None): s.status_code, s._j, s.text = code, js or {}, str(js)
    def json(s): return s._j
class Fake:
    def __init__(s, plan): s.plan, s.posts, s.state = plan, [], {}     # plan: id -> list of statuses after start
    def get(s, url, timeout=0):
        jid = url.rsplit("/", 1)[1]
        if jid not in s.plan: return R(404)
        if jid not in s.state: return R(200, {"status": "draft"} if s.plan[jid] != "notdraft" else {"status": "done"})
        seq = s.state[jid]; st = seq.pop(0) if len(seq) > 1 else seq[0]
        return R(200, {"status": st, "progress": 50, "message": "m"})
    def post(s, url, timeout=0):
        jid = url.split("/jobs/")[1].split("/")[0]; s.posts.append(jid); s.state[jid] = list(s.plan[jid]); return R(200, {"status": "queued"})
f = Fake({"a": ["running", "awaiting_approval"], "b": ["queued", "running", "done"], "c": ["running", "done"]})
res = gs.run(["a", "b", "c"], s=f, sleep=lambda x: None, out=lambda *a: None)
check("S1 jobs start one after the other, each only after the previous parked (awaiting_approval and done both release the next)", f.posts == ["a", "b", "c"] and res == {"a": "awaiting_approval", "b": "done", "c": "done"}, (f.posts, res))
f = Fake({"a": ["running", "failed"], "b": ["done"]})
res = gs.run(["a", "b"], s=f, sleep=lambda x: None, out=lambda *a: None)
check("S2 a failed job stops the batch: the next one is never started", f.posts == ["a"] and res["b"] == "not started" and res["a"] == "failed", (f.posts, res))
f = Fake({"a": "notdraft", "b": ["done"]})
res = gs.run(["a", "b"], s=f, sleep=lambda x: None, out=lambda *a: None)
check("S3 a job that is not a draft is skipped (never started twice) and the batch goes on", f.posts == ["b"] and res["a"] == "skipped:done", (f.posts, res))
f = Fake({"a": ["running"], "b": ["done"]})
res = gs.run(["a", "b"], s=f, sleep=lambda x: None, out=lambda *a: None, poll=60, max_wait=180)
check("S4 a job that never leaves 'running' stops the batch after the maximum wait", res["a"] == "timeout:running" and res["b"] == "not started", res)
f = Fake({"a": ["done"]})
res = gs.run(["zzz", "a"], s=f, sleep=lambda x: None, out=lambda *a: None)
check("S5 an unknown job id stops the batch before spending anything", f.posts == [] and res["a"] == "not started", (f.posts, res))
src = open("gial_start.py").read()
check("S6 the access key is never printed and the script has no delete call", "print(key" not in src and "out(key" not in src and not any(w in src for w in ("rmtree", "unlink", "os.remove", ".delete(")))
import json, tempfile
from pathlib import Path
jd = Path(tempfile.mkdtemp())
def mk(name, status, ref):
    (jd / name).mkdir(); (jd / name / "job_meta.json").write_text(json.dumps({"status": status, "external_ref": f"T-{ref}-abc123"}))
mk("old11860", "done", "1186"); mk("new11860", "draft", "1186"); mk("other123", "draft", "1237"); mk("old1237x", "failed", "1237")
import listing_registry as lr
check("S10 the registry reads only finished videos, by listing number", sorted((r["listing"], r["job_id"]) for r in lr.scan([("given", jd)]) if r["status"] == "done") == [("1186", "old11860")])
check("S11 same_listing_done: a draft whose listing already has a finished video", gs.same_listing_done("new11860", jd) == ["old11860"] and gs.same_listing_done("other123", jd) == [] and gs.same_listing_done("old11860", jd) == [])
f2 = Fake({"new11860": ["running", "done"], "other123": ["running", "done"]})
logs = []
res2 = gs.run(["new11860", "other123"], s=f2, sleep=lambda x: None, out=lambda *a: logs.append(" ".join(map(str, a))), jobs_dir=jd)
check("S12 duplicate listing is skipped with no start call, the next job still runs", res2["new11860"].startswith("skipped:duplicate") and f2.posts == ["other123"], (res2, f2.posts))
f3 = Fake({"new11860": ["running", "done"]})
res3 = gs.run(["new11860"], s=f3, sleep=lambda x: None, out=lambda *a: None, jobs_dir=jd, again=True)
check("S13 --again generates it anyway", f3.posts == ["new11860"] and res3["new11860"] == "done", (res3, f3.posts))
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
