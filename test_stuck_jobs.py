"""Stuck-job check: finds running jobs whose folder is silent for 45+ min. Source-level
(exec of the real functions with stubs) - the module needs dotenv/credit_monitor."""
import ast, json, os, tempfile, time
from pathlib import Path
src = open("maintenance_scheduler.py").read()
tree = ast.parse(src)
want = {"_job_last_activity", "find_stuck_jobs"}
code = "\n".join(ast.get_source_segment(src, n) for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name in want)
ns = {"os": os, "json": json, "Path": Path, "STUCK_JOB_MINUTES": 45,
      "STUCK_STATUSES": ("running", "preparing")}
exec(code, ns)
find = ns["find_stuck_jobs"]
ok = 0; bad = 0
def t(name, cond):
    global ok, bad
    print(("PASS" if cond else "FAIL"), name); ok += cond; bad += (not cond)
now = time.time()
def mk(root, name, status, age_min, meta=True):
    d = root / name; d.mkdir()
    if meta:
        (d / "job_meta.json").write_text(json.dumps({"status": status}))
    (d / "clip.mp4").write_text("x")
    for f in d.iterdir():
        os.utime(f, (now - age_min * 60,) * 2)
with tempfile.TemporaryDirectory() as tmp:
    r = Path(tmp)
    mk(r, "aaaaaaaa1", "running", 60)
    mk(r, "bbbbbbbb2", "running", 5)
    mk(r, "cccccccc3", "done", 600)
    mk(r, "dddddddd4", "queued", 600)
    mk(r, "eeeeeeee5", "preparing", 50)
    mk(r, "ffffffff6", "running", 600, meta=False)
    mk(r, "_test_scratch", "running", 600)
    got = dict(find(r, now))
    t("SJ1 running 60 min silent -> stuck", "aaaaaaaa1" in got and got["aaaaaaaa1"] >= 59)
    t("SJ2 running 5 min -> not stuck", "bbbbbbbb2" not in got)
    t("SJ3 done old -> not stuck", "cccccccc3" not in got)
    t("SJ4 queued old -> not stuck (waits for a slot)", "dddddddd4" not in got)
    t("SJ5 preparing 50 min -> stuck", "eeeeeeee5" in got)
    t("SJ6 folder without job_meta.json ignored", "ffffffff6" not in got)
    t("SJ7 folders starting with _ ignored", "_test_scratch" not in got)
    # a fresh clip in an otherwise old job keeps it alive
    d = r / "aaaaaaaa1"; os.utime(d / "clip.mp4", (now - 60,) * 2)
    (d / "new.mp4").write_text("y")
    t("SJ8 recent file inside the job keeps it alive", "aaaaaaaa1" not in dict(find(r, now)))
    t("SJ9 missing jobs dir -> empty", find(r / "nope", now) == [])
    (r / "gggggggg7").mkdir(); (r / "gggggggg7" / "job_meta.json").write_text("{broken")
    t("SJ10 corrupt job_meta.json ignored, no crash", "gggggggg7" not in dict(find(r, now)))
t("SJ11 check interval is 10 min", '"stuck_jobs":            10,' in src)
t("SJ12 old dead job.json lookup gone", '/ "job.json"' not in src and '.get("generation_started_at")' not in src)
t("SJ13 check_stuck_jobs never writes files",
  "write_text" not in ast.get_source_segment(src, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check_stuck_jobs")))
print(f"{ok} PASS / {bad} FAIL"); raise SystemExit(1 if bad else 0)
