"""Patch L2 (2026-10-23): creating a draft from a listing URL no longer keeps the browser waiting for minutes.
The request reads the listing and applies the acceptance rule, then answers with the job id (status "preparing");
the slow part runs in the background and ends in "draft" or "prep_failed". No network, no audio, no API key.
Run: python3 test_url_draft_background.py"""
import os, sys, asyncio, ast, builtins, re, subprocess, tempfile, json
sys.path.insert(0, os.getcwd())
import job_recovery as jr

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

class Log:
    def __init__(self): self.msgs = []
    def warning(self, m): self.msgs.append(("w", m))
    def exception(self, m): self.msgs.append(("x", m))

def new_jobs():
    return {"j1": {"status": "preparing", "message": "...", "property_name": "P", "created_at": "2026-10-23T10:00:00"}}
saved = []

# ---------------- A. the state machine (pure)
async def ok_work(jobs):
    jobs["j1"]["status"] = "draft"; jobs["j1"]["scenes_config"] = [1, 2]
jobs = new_jobs(); saved.clear()
asyncio.run(jr.run_preparation("j1", jobs, saved.append, lambda: ok_work(jobs), log=Log()))
check("A1 successful work leaves the job as the work set it (draft)", jobs["j1"]["status"] == "draft" and "prep_error" not in jobs["j1"])

async def perr():
    raise jr.PrepError("Not enough usable photos for this listing: x. Try again in a moment, or upload manually.")
jobs = new_jobs(); saved.clear()
asyncio.run(jr.run_preparation("j1", jobs, saved.append, perr, log=Log()))
check("A2 a PrepError -> prep_failed, the message is the one the HTTP error used to carry, saved to disk",
      jobs["j1"]["status"] == "prep_failed" and jobs["j1"]["message"].startswith("Not enough usable photos") and jobs["j1"]["prep_error"] == jobs["j1"]["message"] and saved == ["j1"], jobs["j1"])

async def boom():
    raise RuntimeError("kaboom")
jobs = new_jobs(); saved.clear(); lg = Log()
asyncio.run(jr.run_preparation("j1", jobs, saved.append, boom, log=lg))
check("A3 an unexpected exception -> prep_failed with its text, logged with traceback, nothing raised",
      jobs["j1"]["status"] == "prep_failed" and "kaboom" in jobs["j1"]["message"] and any(k == "x" for k, _ in lg.msgs), jobs["j1"])

async def lazy():
    return None
jobs = new_jobs(); saved.clear()
asyncio.run(jr.run_preparation("j1", jobs, saved.append, lazy, log=Log()))
check("A4 work that returns without finishing never leaves the job 'preparing' forever", jobs["j1"]["status"] == "prep_failed" and saved == ["j1"], jobs["j1"])

def bad_save(_):
    raise OSError("disk full")
jobs = new_jobs()
try:
    asyncio.run(jr.run_preparation("j1", jobs, bad_save, perr, log=Log())); raised = False
except Exception:
    raised = True
check("A5 a failing save does not raise out of the background task (status still set in memory)", not raised and jobs["j1"]["status"] == "prep_failed")
jobs = {}
try:
    asyncio.run(jr.run_preparation("nope", jobs, saved.append, perr, log=Log())); raised = False
except Exception:
    raised = True
check("A6 a job that vanished does not crash the task", not raised)

# ---------------- B. restart recovery
check("B1 'preparing' is an orphan state", "preparing" in jr.ORPHAN_STATES)
with tempfile.TemporaryDirectory() as d:
    jobs = {"p1": {"status": "preparing", "property_name": "Casa", "created_at": "x"},
            "r1": {"status": "running", "property_name": "Run", "scenes_config": [], "created_at": "y"},
            "d1": {"status": "draft", "property_name": "Dr", "created_at": "z"}}
    saved.clear()
    rec = jr.recover_orphans(jobs, d, saved.append)
    by = {r["job_id"]: r for r in rec}
    check("B2 a job left 'preparing' by a restart becomes prep_failed with a clear message and is saved",
          jobs["p1"]["status"] == "prep_failed" and "riavvio" in jobs["p1"]["message"] and "p1" in saved and by["p1"]["new"] == "prep_failed", jobs["p1"])
    check("B3 no partner webhook is triggered for it (only 'failed' triggers one)", by["p1"]["new"] != "failed" and by["p1"]["has_callback"] is False)
    check("B4 other statuses behave as before (running with no images -> failed; draft untouched)", jobs["r1"]["status"] == "failed" and jobs["d1"]["status"] == "draft")

# ---------------- C. api_server.py wiring (it cannot be imported here: no fastapi)
src = open("api_server.py").read()
tree = ast.parse(src)
def fn(name):
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name: return n
    return None
def seg(name): return ast.get_source_segment(src, fn(name))
ep, worker, runner = seg("create_job_from_url"), seg("_prepare_url_draft_work"), seg("_prepare_url_draft")
check("C1 the three functions exist", bool(ep and worker and runner))
check("C2 the endpoint takes BackgroundTasks and schedules the preparation", "background_tasks: BackgroundTasks" in ep and "background_tasks.add_task(_prepare_url_draft" in ep)
check("C3 the endpoint answers with the job id and status 'preparing'", '"status": "preparing"' in ep and "return {\"job_id\": job_id" in ep)
i_acc, i_job = ep.index("check_listing_acceptance"), ep.index('"status": "preparing"')
check("C4 option B: reading the listing and the acceptance rule happen BEFORE the job exists (a rejected listing leaves no job)",
      ep.index("extract_listing") < i_acc < i_job and "status_code=422" in ep and "status_code=400" in ep and ep.index("check_listing_acceptance") < ep.index("mkdir"))
check("C5 the slow steps moved to the worker (narration, download, captions, vision, cost)",
      all(k in worker for k in ["generate_narration_and_derive_scenes", "download_selected_photos", "generate_captions_for_categories", "_apply_vision_analysis_to_scenes", "estimate_job_cost"]) and
      not any(k in ep for k in ["generate_narration_and_derive_scenes", "download_selected_photos", "generate_captions_for_categories", "_apply_vision_analysis_to_scenes"]))
check("C6 the worker ends by setting status 'draft' and saving, with the same stored fields as before",
      '"status": "draft"' in worker and "_save_job(job_id)" in worker and all(k in worker for k in
      ['"narration_text"', '"narration_path"', '"narration_mode"', '"timeline"', '"timeline_fallback"', '"selection_report"', '"claude_usage"', '"cost_estimate"', '"source_url"', '"scenes_config"', '"property_id"']))
check("C7 keeps the creation time of the stub (list order stays stable)", 'JOBS[job_id].get("created_at")' in worker)
check("C8 nothing is deleted by the code: no rmtree anywhere in the URL creation path", "rmtree" not in ep and "rmtree" not in worker)
check("C9 the worker raises PrepError (not HTTPException: nobody could catch it after the response)", "PrepError" in worker and "HTTPException" not in worker)
check("C10 the runner goes through the ONE shared state machine", "_jr.run_preparation" in runner and "import job_recovery as _jr" in src)
check("C11 exactly one implementation: the narration call is not duplicated in the endpoint", ep.count("generate_narration") == 0 and worker.count("generate_narration_and_derive_scenes") == 1)
check("C12 the Relinx adapter is untouched by this patch (still calls its own creation path)", "partner" in src and src.count("def _prepare_url_draft_work") == 1)

def undefined_names(source, func_names):
    t = ast.parse(source)
    glob = set(dir(builtins))
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): glob.add(n.name)
        for x in ast.walk(n):
            if isinstance(x, (ast.Import, ast.ImportFrom)):
                for a in x.names: glob.add((a.asname or a.name).split(".")[0])
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store): glob.add(x.id)
    bad = []
    for f in t.body:
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name in func_names:
            loc = set()
            for x in ast.walk(f):
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    loc |= {a.arg for a in x.args.args + x.args.kwonlyargs}
                    if x.args.vararg: loc.add(x.args.vararg.arg)
                    if x.args.kwarg: loc.add(x.args.kwarg.arg)
                    if not isinstance(x, ast.Lambda): loc.add(x.name)
                if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)): loc.add(x.id)
                if isinstance(x, (ast.Import, ast.ImportFrom)):
                    for a in x.names: loc.add((a.asname or a.name).split(".")[0])
                if isinstance(x, ast.ExceptHandler) and x.name: loc.add(x.name)
            for x in ast.walk(f):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id not in loc and x.id not in glob:
                    bad.append((f.name, x.id, x.lineno))
    return bad
bad = undefined_names(src, {"create_job_from_url", "_prepare_url_draft_work", "_prepare_url_draft"})
check("C13 no undefined name in the three functions (a name lost in the move would only fail at run time)", not bad, bad)
check("C14 the name check really catches an undefined name (self-test)", undefined_names("def f():\n    return nope_x\n", {"f"}) == [("f", "nope_x", 2)])

# ---------------- D. the page
ui = open("ui.html").read()
check("D1 the page polls the job status after the POST", "async function waitForDraft" in ui and "authFetch(`/jobs/${jobId}`)" in ui and "await waitForDraft(data.job_id" in ui)
check("D2 handles both final states and keeps polling through network errors",
      "job.status === 'draft'" in ui and "job.status === 'prep_failed'" in ui and "connessione instabile" in ui and "catch (e)" in ui.split("async function waitForDraft")[1].split("async function startFromUrl")[0])
check("D3 the library shows both new statuses", "preparing:" in ui and "prep_failed:" in ui)
check("D4 the old fields of the synchronous answer are no longer read (scene_count / video_duration_secs)", "data.scene_count" not in ui.split("async function startFromUrl")[1].split("let _editJobSeq")[0])
m = re.findall(r"<script>(.*?)</script>", ui, re.S)
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write("\n".join(m)); jsfile = f.name
r = subprocess.run(["node", "--check", jsfile], capture_output=True, text=True) if subprocess.run(["which", "node"], capture_output=True).returncode == 0 else None
check("D5 the page script has no syntax error (node --check)", r is not None and r.returncode == 0, (r.stderr[:300] if r else "node not available"))
check("E1 every touched module compiles", subprocess.run([sys.executable, "-m", "py_compile", "api_server.py", "job_recovery.py", "scene_script.py", "listing_scraper.py"]).returncode == 0)

print()
print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
