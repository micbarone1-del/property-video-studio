"""Point 3, the REAL runner (api_server._run_redo + _rework_qc_gate + alt_photo_rework) driven with fakes at the edges: no Luma, no Claude, no network.
Needs the server environment (fastapi): where it is not installed the test says SKIPPED. Run: python3 test_alt_photo_runner.py"""
import asyncio, os, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import fastapi  # noqa
except Exception:
    print("SKIPPED (fastapi not installed here: run it on the server)"); sys.exit(0)
for name in ("fal_client", "moviepy"):
    if name not in sys.modules:
        try: __import__(name)
        except Exception: sys.modules[name] = types.ModuleType(name)
TMP = Path(tempfile.mkdtemp())
os.environ["PVS_JOBS_DIR"] = str(TMP)
os.environ["PVS_AUTO_ALT_PHOTO"] = "1"
import api_server as A
import listing_scraper as LS
A.JOBS_DIR = TMP

res = []
def check(name, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(info)))

PHOTO = {"url": "https://x/alt.jpg", "rank_status": "ranked", "feature_visible": True, "quality": "ok"}

def run(qc_seq, pick=PHOTO, auto=("sc_bath",), jid="j1", switch="1"):
    os.environ["PVS_AUTO_ALT_PHOTO"] = switch
    d = TMP / jid
    for sub in ("images", "enhanced", "clips"): (d / sub).mkdir(parents=True, exist_ok=True)
    (d / "images" / "sc_bath.jpg").write_bytes(b"OLD"); (d / "clips" / "sc_bath.mp4").write_bytes(b"CLIP")
    job = {"status": "running", "model_tier": "premium", "enable_vision_qc": True, "auto_reworked": list(auto), "property_name": "T",
           "scenes_config": [{"scene_id": "sc_kit", "category": "kitchen"}, {"scene_id": "sc_live", "category": "living"}, {"scene_id": "sc_bath", "category": "bathrooms"}],
           "scenes": [], "qc_results": [], "selection_report": {"selected": {}, "candidate_urls": {"bathrooms": ["u1", "u2"]}}}
    A.JOBS[jid] = job
    log = {"redo": [], "reasm": 0, "qc": 0}
    async def fake_redo(j, jd, ids, deps, **kw):
        log["redo"].append((list(ids), kw.get("label"), (Path(jd) / "images" / "sc_bath.jpg").read_bytes()))
        return {"redone": [{"scene_id": s} for s in ids], "failed": [], "skipped": []}
    def fake_qc(j, jd, redone, deps):
        v = qc_seq[min(log["qc"], len(qc_seq) - 1)]; log["qc"] += 1
        return {"rejected": [2] if v == "reject" else [], "flagged": [2] if v == "flag" else [], "checked": ["sc_bath"], "unchecked": []}
    async def fake_reasm(job_id): log["reasm"] += 1
    async def noop(*a, **k): return None
    A._sr.redo_scenes = fake_redo; A._sr.qc_redone = fake_qc; A._sr.record_rework_cost = lambda *a, **k: None; A._sr.lost_generations = lambda *a, **k: []
    A.run_reassemble_only = fake_reasm; A._notify_operator = noop; A._warm_previews = lambda *a, **k: None
    A._redo_deps = lambda job_id: types.SimpleNamespace(log=types.SimpleNamespace(warning=lambda *a: None, info=lambda *a: None))
    import vision_analysis as VA; VA.analyse_output = lambda *a, **k: {}
    LS.pick_alternative_photo = lambda rep, cat, excl: {"photo": pick, "reason": "no other photo of this room" if not pick else "ok"}
    LS.fetch_photo_bytes = lambda url, *a, **k: {"ok": True, "content": b"NEWPHOTO"}
    asyncio.run(A._run_redo(jid, ["sc_bath"], video=True, strict=False, policy=True, label="Rework automatico"))
    return job, log

job, log = run(["reject", "pass"])
check("R1 rejected twice -> alternative photo -> passes: the SAME runner ran twice, the second time on the NEW photo, then ONE reassembly",
      len(log["redo"]) == 2 and log["redo"][0][2] == b"OLD" and log["redo"][1][2] == b"NEWPHOTO" and log["redo"][1][1] == "Rework foto alternativa" and log["reasm"] == 1, log)
check("R2 the job is not parked, the attempt says accepted, the rework budget counted both rounds", job["status"] != "awaiting_approval" and job["alt_photo"]["sc_bath"]["status"] == "accepted" and job["rework_counts"]["sc_bath"] == 2 and "alt_pending" not in job, (job["status"], job.get("alt_photo"), job.get("rework_counts")))
job, log = run(["reject", "reject"], jid="j2")
check("R3 alternative rejected too -> the job parks for the operator, no reassembly, only ONE alternative tried", len(log["redo"]) == 2 and log["reasm"] == 0 and job["status"] == "awaiting_approval" and job["alt_photo"]["sc_bath"]["status"] == "rejected_again", (log, job["status"], job.get("alt_photo")))
job, log = run(["reject", "flag"], jid="j3")
check("R4 alternative flagged -> parks for the operator", job["status"] == "awaiting_approval" and log["reasm"] == 0, job["status"])
job, log = run(["reject"], pick=None, jid="j4")
check("R5 no alternative photo -> parks at once, ONE redo only, the reason is in the job", len(log["redo"]) == 1 and job["status"] == "awaiting_approval" and job["alt_photo"]["sc_bath"]["status"] == "none", (log, job.get("alt_photo")))
job, log = run(["reject"], switch="0", jid="j5")
check("R6 switch off -> exactly today's behaviour (parks, one redo, no alt_photo in the job)", len(log["redo"]) == 1 and job["status"] == "awaiting_approval" and "alt_photo" not in job, (log, job.get("alt_photo")))
job, log = run(["reject"], auto=(), jid="j6")
check("R7 scene rejected only once (no automatic rework before) -> not tried", len(log["redo"]) == 1 and job["status"] == "awaiting_approval" and "alt_photo" not in job or job.get("alt_photo") == {}, (log, job.get("alt_photo")))
job, log = run(["pass"], jid="j7")
check("R8 first rework passes -> plain reassembly, no alternative involved", len(log["redo"]) == 1 and log["reasm"] == 1 and not job.get("alt_photo"), (log, job.get("alt_photo")))
print("%d/%d PASS" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
