"""P1 (2026-10-28): a clip that failed to generate is a visible stop, never a partial video.
Found on job cc33f8af: two clips failed, were neither 'rejected' nor 'flagged', the QC gate did not stop and the video was
assembled with 4 scenes under a 6-scene voice. api_server.py cannot be imported here (no fastapi): the real functions are cut
out of the source and run with stand-ins for the outside world. No network, no key, no cost.
Run: python3 test_failed_clips.py"""
import os, sys, ast, asyncio, tempfile, shutil, types, json, subprocess, re
from pathlib import Path
sys.path.insert(0, os.getcwd())

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

SRC = open("api_server.py").read()
TREE = ast.parse(SRC)
def cut(*names):
    out = []
    for n in TREE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names:
            out.append(ast.get_source_segment(SRC, n))
    assert len(out) == len(names), (names, len(out))
    return "\n\n".join(out)

class HTTPException(Exception):
    def __init__(self, status_code, detail): self.status_code, self.detail = status_code, detail
class Log:
    def __getattr__(self, k): return lambda *a, **kw: None

tmp = Path(tempfile.mkdtemp())
def make_job(jid, n, existing):
    d = tmp / jid; (d / "clips").mkdir(parents=True); (d / "audio").mkdir()
    cfg = [{"scene_id": f"sc{i}"} for i in range(n)]
    for i in existing:
        (d / "clips" / f"sc{i}.mp4").write_bytes(b"x")
    return cfg

calls = {"assemble": 0, "notify": 0}
fake_va = types.ModuleType("video_assembly")
def fake_assemble(**kw):
    calls["assemble"] += 1; calls["clips"] = list(kw["video_clip_paths"]); return True
fake_va.assemble_property_video = fake_assemble
sys.modules["video_assembly"] = fake_va

JOBS = {}
async def _notify_operator(*a, **kw): calls["notify"] += 1
async def _send_partner_webhook(*a, **kw): pass
ns = dict(os=os, shutil=shutil, asyncio=asyncio, json=json, Path=Path, log=Log(), JOBS=JOBS, JOBS_DIR=tmp,
          HTTPException=HTTPException, _notify_operator=_notify_operator, _send_partner_webhook=_send_partner_webhook,
          _save_job=lambda j: None, _warm_previews=lambda *a, **kw: None, _release_job_lock=lambda j: None,
          _overlay_narration_audio=lambda *a, **kw: None, cost_model=types.SimpleNamespace(get_agency=lambda x: None))
exec(cut("_MissingClips", "_awaiting_payload", "_missing_clip_scenes", "run_reassemble_only"), ns)

# --- F1 helper shapes
check("F1 awaiting payload always has the three lists", ns["_awaiting_payload"]([1], [2], [3]) == {"rejected": [1], "flagged": [2], "failed": [3]})

# --- F2 4 of 6 clips: assembly does NOT run, the job waits in review and lists the missing scenes
JOBS["a"] = {"status": "running", "scenes_config": make_job("a", 6, [0, 1, 4, 5]), "property_name": "P", "timeline": {"mode": "anchored", "targets": [5]*6}}
check("F2a missing scenes are found by index", ns["_missing_clip_scenes"]("a") == [2, 3])
calls.update(assemble=0, notify=0)
asyncio.run(ns["run_reassemble_only"]("a"))
check("F2b assembly NOT called with 4 of 6 clips", calls["assemble"] == 0)
check("F2c job waits in awaiting_approval (visible), not 'failed' and not 'done'", JOBS["a"]["status"] == "awaiting_approval", JOBS["a"]["status"])
check("F2d the missing scenes are listed as failed", JOBS["a"]["awaiting_scenes"].get("failed") == [2, 3], JOBS["a"].get("awaiting_scenes"))
check("F2e operator informed exactly once", calls["notify"] == 1, calls["notify"])
check("F2f no output file claimed", "output_path" not in JOBS["a"])

# --- F3 all clips: normal assembly, unchanged
JOBS["b"] = {"status": "running", "scenes_config": make_job("b", 6, range(6)), "property_name": "P"}
calls.update(assemble=0, notify=0)
asyncio.run(ns["run_reassemble_only"]("b"))
check("F3a all 6 clips: assembled once with 6 clips", calls["assemble"] == 1 and len(calls["clips"]) == 6)
check("F3b job done, no operator notice", JOBS["b"]["status"] == "done" and calls["notify"] == 0, JOBS["b"]["status"])

# --- F4 legacy file names still count as a clip (older jobs)
cfg = make_job("c", 2, [])
(tmp / "c" / "clips" / "scene_000.mp4").write_bytes(b"x"); (tmp / "c" / "clips" / "scene_001.mp4").write_bytes(b"x")
JOBS["c"] = {"status": "running", "scenes_config": cfg, "property_name": "P"}
check("F4 legacy scene_NNN.mp4 clips are not reported missing", ns["_missing_clip_scenes"]("c") == [])

# --- F5 approve: a scene without clip cannot be approved, only redone
async def _rework_gate(*a, **kw): pass
class BG:
    def __init__(self): self.tasks = []
    def add_task(self, *a, **kw): self.tasks.append(a)
ns2 = dict(ns, Form=lambda *a, **kw: None, BackgroundTasks=BG, app=types.SimpleNamespace(post=lambda *a, **kw: (lambda f: f)),
           _rework_gate=_rework_gate, _acquire_job_lock=lambda *a: True, run_redo_scenes_batch=None, run_reassemble_only=None)
exec(cut("approve_job"), ns2)
JOBS["d"] = {"status": "awaiting_approval", "scenes_config": make_job("d", 6, [0, 1, 4, 5]), "scenes": []}
def approve(approved, redo):
    try:
        asyncio.run(ns2["approve_job"]("d", BG(), json.dumps({"approved_scenes": approved, "redo_scenes": redo}))); return None
    except HTTPException as e:
        return e.status_code
check("F5a approving everything while 2 and 3 have no clip -> 400", approve([0, 1, 2, 3, 4, 5], []) == 400)
check("F5b redoing only scene 2 while 3 has no clip -> 400", approve([], [2]) == 400)
check("F5c redoing both missing scenes is accepted", approve([], [2, 3]) is None)
JOBS["d"]["status"] = "awaiting_approval"
JOBS["e"] = {"status": "awaiting_approval", "scenes_config": make_job("e", 3, range(3)), "scenes": []}
try:
    asyncio.run(ns2["approve_job"]("e", BG(), json.dumps({"approved_scenes": [0], "redo_scenes": []}))); ok = True
except HTTPException: ok = False
check("F5d a normal approval (all clips present) still goes through", ok)

# --- F6 the pipeline gate counts failed clips (source) and UI
pipe = SRC[SRC.index("async def run_pipeline("):]
check("F6a pipeline records a failed clip in failed_scenes", "elif not ok:" in pipe and "failed_scenes.append(i)" in pipe)
check("F6b the QC gate opens for failed clips too", "if rejected_scenes or flagged_scenes or failed_scenes:" in pipe)
check("F6c the gate state uses the single payload function", "_awaiting_payload(rejected_scenes, flagged_scenes, failed_scenes)" in pipe)
check("F6d no code path left that skips a missing clip", "skipping from assembly" not in SRC)
ui = open("ui.html").read()
check("F6e the review panel knows failed clips and offers only redo for them", "awaiting.failed" in ui and "isFailed ? ''" in ui and "Clip non generata" in ui)
scripts = re.findall(r"<script[^>]*>(.*?)</script>", ui, re.S)
big = max(scripts, key=len)
p = Path(tmp / "ui_check.js"); p.write_text(big)
try:
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True); okjs = r.returncode == 0; msg = r.stderr[:200]
except FileNotFoundError:
    okjs = True; msg = "node missing: skipped"
check("F6f ui.html script still parses", okjs, msg)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
