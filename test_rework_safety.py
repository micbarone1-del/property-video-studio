"""test_rework_safety.py - a rework never fails the whole job and a rework without a clip is not an attempt (2026-11-16, Michele).
No network, no keys: the helper is extracted from api_server.py and run with stand-ins."""
import ast, asyncio, os, sys, tempfile
from pathlib import Path
import rework_policy as rwp

fails = []
def check(n, ok):
    print(("PASS " if ok else "FAIL ") + n)
    if not ok: fails.append(n)

# ---- give_back arithmetic
j = {"rework_counts": {"a": 1, "b": 2}, "rework_rounds": 2, "auto_reworked": ["a", "b"]}
rwp.give_back(j, ["a"], round_too=False)
check("RS1 one scene given back, round kept", j["rework_counts"]["a"] == 0 and j["rework_counts"]["b"] == 2 and j["rework_rounds"] == 2)
check("RS2 the automatic-attempt marker of that scene is removed too", j["auto_reworked"] == ["b"])
rwp.give_back(j, ["b"], round_too=True)
check("RS3 round given back when asked", j["rework_rounds"] == 1 and j["rework_counts"]["b"] == 1)
j = {"rework_counts": {"a": 0}, "rework_rounds": 0}
rwp.give_back(j, ["a", "zz"], round_too=True)
check("RS4 never below zero, unknown scene harmless", j["rework_counts"]["a"] == 0 and j["rework_rounds"] == 0)

# ---- the crash helper, extracted from api_server.py
src = Path("api_server.py").read_text()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_park_after_rework_crash")
code = ast.get_source_segment(src, fn)
sent = []
class Log:
    def warning(self, *a, **k): pass
async def _notify(job_id, event, subject, body_html, push_message, tags=None, priority="default"):
    sent.append(event)
saved = []
tmp = tempfile.mkdtemp()
mp4 = Path(tmp) / "final.mp4"; mp4.write_bytes(b"x")
JOBS = {"j1": {"status": "running", "output_path": str(mp4), "rework_counts": {"s1": 1}, "rework_rounds": 1, "property_name": "P",
               "rework_in_progress": {"scene_ids": ["s1"]}},
        "j2": {"status": "running", "output_path": None, "rework_counts": {"s1": 1}, "rework_rounds": 1}}
ns = {"JOBS": JOBS, "_rwp": rwp, "Path": Path, "_save_job": lambda i: saved.append(i), "_notify_operator": _notify, "log": Log()}
exec(code, ns)
asyncio.run(ns["_park_after_rework_crash"]("j1", ["s1"], policy=True, video=True, err=RuntimeError("boom")))
check("RS5 a crash on a job with a final video leaves it done", JOBS["j1"]["status"] == "done")
check("RS6 the attempt is given back", JOBS["j1"]["rework_counts"]["s1"] == 0 and JOBS["j1"]["rework_rounds"] == 0)
check("RS7 the operator is told once, the job flagged", sent == ["Rework crashed"] and JOBS["j1"]["needs_operator"]["kind"] == "rework_crashed")
check("RS8 the in-progress marker is cleared", "rework_in_progress" not in JOBS["j1"])
asyncio.run(ns["_park_after_rework_crash"]("j1", ["s1"], policy=True, video=True, err=RuntimeError("again")))
check("RS9 a second crash does not notify again", sent == ["Rework crashed"])
asyncio.run(ns["_park_after_rework_crash"]("j2", ["s1"], policy=True, video=True, err=RuntimeError("boom")))
check("RS10 with no final video the job waits for the operator, never failed", JOBS["j2"]["status"] == "awaiting_approval")

# ---- wiring in the real file
run = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_redo")
rs = ast.get_source_segment(src, run)
check("RS11 _run_redo no longer sets the job to failed", '"status": "failed"' not in rs)
check("RS12 _run_redo parks the job through the helper", "_park_after_rework_crash(job_id" in rs)
check("RS13 scenes without a clip are retried (PVS_REWORK_NOGEN_RETRIES) and given back", "PVS_REWORK_NOGEN_RETRIES" in rs and "give_back" in rs)
ra = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_reassemble_only")
rss = ast.get_source_segment(src, ra)
check("RS14 reassembly failure keeps a job that already has a final video", "_had_video" in rss and "resta il video precedente" in rss)
check("RS15 first-generation reassembly failure still fails and tells the partner", "Errore assemblaggio" in rss and rss.count("_send_partner_webhook(job_id, \"failed\")") == 1)
sys.exit(1 if fails else 0)
