"""Clip QC of reworked clips (2026-11-02): scene_rework.qc_redone + the api_server wiring. Fakes only. Run: python3 test_rework_qc.py"""
import os, sys, tempfile, types, json
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import scene_rework as sr
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); fails += 0 if c else 1
tmp = Path(tempfile.mkdtemp())
(tmp / "clips").mkdir(); (tmp / "images").mkdir()
for sid in ("sc_a", "sc_b", "sc_c"):
    (tmp / "clips" / f"{sid}.mp4").write_bytes(b"x"); (tmp / "images" / f"{sid}.jpg").write_bytes(b"x")
def job():
    return {"scenes_config": [{"scene_id": s, "space_type": "large"} for s in ("sc_a", "sc_b", "sc_c")],
            "scenes": [{"scene_id": s, "index": i, "qc_verdict": "pass"} for i, s in enumerate(("sc_a", "sc_b", "sc_c"))],
            "qc_results": [{"scene": 1, "type": "video", "verdict": "reject", "issues": ["invented shelf"]}, {"scene": 1, "type": "tts", "verdict": "pass"}],
            "claude_usage": {}}
def deps(verdicts):
    calls = []
    def analyse(clip, src, space):
        calls.append((clip, src, space))
        v = verdicts[Path(clip).stem]
        if isinstance(v, Exception): raise v
        return dict(v, claude_usage={"input_tokens": 100, "output_tokens": 20, "calls": 1, "cost_eur": 0.02})
    return types.SimpleNamespace(analyse_clip=analyse, log=types.SimpleNamespace(warning=lambda *a: None, info=lambda *a: None), save=lambda: None), calls
P = {"verdict": "pass", "issues": []}
d, calls = deps({"sc_a": P, "sc_b": {"verdict": "reject", "issues": ["new door"]}, "sc_c": {"verdict": "flag", "issues": ["soft"]}})
j = job()
r = sr.qc_redone(j, tmp, [{"scene_id": "sc_a"}, {"scene_id": "sc_b"}, {"scene_id": "sc_c"}], d)
check("RQ1 every redone clip is judged by the injected clip QC with its own clip, original photo and space type", len(calls) == 3 and calls[0][0].endswith("clips/sc_a.mp4") and calls[0][1].endswith("images/sc_a.jpg") and calls[0][2] == "large", calls)
check("RQ2 rejected and flagged scene INDEXES are reported; a passing one is not", r["rejected"] == [1] and r["flagged"] == [2] and r["checked"] == ["sc_a", "sc_b", "sc_c"], r)
check("RQ3 the scene status carries the REAL verdict (no more unconditional 'pass')", [s["qc_verdict"] for s in j["scenes"]] == ["pass", "reject", "flag"], j["scenes"])
vid = [q for q in j["qc_results"] if q["type"] == "video" and q["scene"] == 1]
check("RQ4 the scene's earlier video QC entry is replaced (one entry), keeps the old verdict, marked rework; tts entry untouched",
      len(vid) == 1 and vid[0]["rework"] is True and vid[0]["previous_verdict"] == "reject" and vid[0]["issues"] == ["new door"] and any(q["type"] == "tts" for q in j["qc_results"]), j["qc_results"])
check("RQ5 the REAL Claude cost of the 3 checks is added to the job", j["claude_usage"]["calls"] == 3 and abs(j["claude_usage"]["cost_eur"] - 0.06) < 1e-9, j["claude_usage"])
d, _ = deps({"sc_a": P, "sc_b": P, "sc_c": P}); j = job()
r = sr.qc_redone(j, tmp, [{"scene_id": s} for s in ("sc_a", "sc_b", "sc_c")], d)
check("RQ6 all clips pass -> nothing rejected or flagged (the caller reassembles)", not r["rejected"] and not r["flagged"])
d, _ = deps({"sc_a": RuntimeError("api down"), "sc_b": {"verdict": "pass", "issues": [], "error": "parse"}, "sc_c": P}); j = job()
r = sr.qc_redone(j, tmp, [{"scene_id": s} for s in ("sc_a", "sc_b", "sc_c")], d)
check("RQ7 a QC that crashes or returns an error is 'unchecked' and does NOT block (an error is never a reject)", r["unchecked"] == ["sc_a", "sc_b"] and not r["rejected"] and r["checked"] == ["sc_c"], r)
(tmp / "clips" / "sc_c.mp4").unlink()
d, _ = deps({"sc_a": P, "sc_b": P, "sc_c": P}); j = job()
r = sr.qc_redone(j, tmp, [{"scene_id": "sc_c"}, {"scene_id": "nope"}], d)
check("RQ8 a missing clip is unchecked; an unknown scene id is ignored", r["unchecked"] == ["sc_c"] and r["checked"] == [])
src = Path("api_server.py").read_text()
i = src.index("async def _run_redo(")
body = src[i:src.index("async def run_redo_scene(")]
check("RQ9 _run_redo judges the reworked clips BEFORE the reassembly and returns without reassembling when the gate parks the job",
      body.index("_rework_qc_gate(") < body.index("await run_reassemble_only(job_id)") and "if gate:" in body and body.count("run_reassemble_only(job_id)") == 1)
g = src[src.index("async def _rework_qc_gate("):i]
check("RQ10 the gate parks the job at awaiting_approval with the standard awaiting payload, notifies once, and uses the same QC function as the pipeline",
      '"status": "awaiting_approval"' in g and "_awaiting_payload(qc[" in g and "_notify_operator(" in g and "from vision_analysis import analyse_output" in g and "qc_redone" in g)
check("RQ11 PVS_REWORK_QC=0 and the job's own QC switch turn it off", "PVS_REWORK_QC" in src and 'job.get("enable_vision_qc", True)' in src)
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
