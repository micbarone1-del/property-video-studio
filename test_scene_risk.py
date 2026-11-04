"""test_scene_risk.py - scene_risk registry (2026-11-04): recording, summary, never-raises, and the two QC wirings. Fakes only, no network, no spend. Run: python3 test_scene_risk.py"""
import json, os, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_SCENE_RISK_FILE"] = str(tmp / "ev.jsonl")
os.environ.pop("PVS_FAKE_PROVIDERS", None); os.environ.pop("PVS_SCENE_RISK", None)
import scene_risk as sr
import scene_rework as srw
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); fails += 0 if c else 1
F = tmp / "ev.jsonl"
check("S1 no file, empty summary", sr.summary()["events"] == 0 and sr.load_events() == [])
check("S2 record writes one line with the fields", sr.record("j1", "sc_a", {"category": "kitchen", "pov_movement": "forward"}, "pass", movement="forward", tier="draft") and len(F.read_text().splitlines()) == 1)
e = json.loads(F.read_text().splitlines()[0])
check("S3 fields", e["job"] == "j1" and e["cat"] == "kitchen" and e["move"] == "forward" and e["stage"] == "first" and e["verdict"] == "pass" and e["tier"] == "draft", e)
check("S4 an unknown verdict is not recorded", sr.record("j1", "sc_a", {}, "banana") is False and len(F.read_text().splitlines()) == 1)
os.environ["PVS_SCENE_RISK"] = "0"
check("S5 PVS_SCENE_RISK=0 records nothing", sr.record("j1", "sc_b", {}, "pass") is False and len(F.read_text().splitlines()) == 1)
os.environ.pop("PVS_SCENE_RISK"); os.environ["PVS_FAKE_PROVIDERS"] = "1"
check("S6 fake providers record nothing", sr.record("j1", "sc_b", {}, "pass") is False)
os.environ.pop("PVS_FAKE_PROVIDERS")
os.environ["PVS_SCENE_RISK_FILE"] = str(tmp / "afile" / "x" / "ev.jsonl")
(tmp / "afile").write_text("i am a file, not a folder")
check("S7 an unwritable path never raises", sr.record("j1", "sc_b", {}, "pass") is False)
os.environ["PVS_SCENE_RISK_FILE"] = str(F)
with open(F, "a") as f:
    f.write("this line is damaged\n")
check("S8 a damaged line does not hide the others", len(sr.load_events()) == 1)
for i in range(12):
    sr.record("j2", f"s{i}", {"category": "living"}, "flag" if i < 6 else "pass", movement="forward")
for i in range(6):
    sr.record("j2", f"s{i}", {"category": "living"}, "reject" if i < 3 else "pass", stage="rework", movement="forward", previous="flag")
sr.record("j2", "sz", {"category": "living"}, "failed", movement="forward")
b = sr.summary()["by_category"]["living"]
check("S9 counts: 12 first, 6 flagged, 6 reworked, 3 persistent, 3 resolved, 1 failed", (b["n"], b["first_flag"], b["rework_checked"], b["persistent"], b["resolved"], b["failed"]) == (12, 6, 6, 3, 3, 1), b)
check("S10 rates and risky (n>=10, persistent 0.5>=0.25)", b["first_flag_rate"] == 0.5 and b["persistent_rate"] == 0.5 and b["risky"] is True, b)
check("S11 a small bucket is never risky", sr.summary()["by_category"]["kitchen"]["risky"] is False)
check("S12 category|movement bucket exists", "living|forward" in sr.summary()["by_category_movement"])
# the rework wiring: qc_redone records the verdict of the regenerated clip with the previous one
jd = tmp / "jobX"; (jd / "clips").mkdir(parents=True); (jd / "images").mkdir()
for sid in ("sc_a", "sc_b"):
    (jd / "clips" / f"{sid}.mp4").write_bytes(b"x"); (jd / "images" / f"{sid}.jpg").write_bytes(b"x")
job = {"scenes_config": [{"scene_id": "sc_a", "space_type": "large", "category": "bedrooms", "pov_movement": "forward"}, {"scene_id": "sc_b", "space_type": "large", "category": "bedrooms", "pov_movement": "forward"}],
       "scenes": [{"scene_id": s, "index": i, "qc_verdict": "pass"} for i, s in enumerate(("sc_a", "sc_b"))],
       "qc_results": [{"scene": 0, "type": "video", "verdict": "flag"}, {"scene": 1, "type": "video", "verdict": "reject"}], "claude_usage": {}}
verd = {"sc_a": {"verdict": "pass"}, "sc_b": {"verdict": "reject"}}
deps = types.SimpleNamespace(analyse_clip=lambda c, s, sp: dict(verd[Path(c).stem], claude_usage={}), log=types.SimpleNamespace(warning=lambda *a: None, info=lambda *a: None), save=lambda: None)
before = len(sr.load_events())
out = srw.qc_redone(job, jd, ["sc_a", "sc_b"], deps)
new = sr.load_events()[before:]
check("S13 qc_redone behaves as before", out["rejected"] == [1] and out["flagged"] == [] and out["checked"] == ["sc_a", "sc_b"], out)
check("S14 qc_redone recorded both, with stage rework and the previous verdict", [(x["scene"], x["verdict"], x["stage"], x.get("previous"), x["job"]) for x in new] == [("sc_a", "pass", "rework", "flag", "jobX"), ("sc_b", "reject", "rework", "reject", "jobX")], new)
srcs = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_server.py"), encoding="utf-8").read()
check("S15 the first-generation QC is wired (verdict and failed), inside try/except", srcs.count("_scene_risk.record(") == 2 and srcs.count("import scene_risk as _scene_risk") == 2)
check("S16 the registry file is gitignored", "scene_risk_events.jsonl" in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gitignore")).read())
print("FAILS:", fails)
sys.exit(1 if fails else 0)
