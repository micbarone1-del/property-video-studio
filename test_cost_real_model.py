"""Job cost by the model that really made each clip (2026-10-26). Pure computation, no network, no jobs/."""
import os, re, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, os.getcwd())
import cost_tracker as ct
import clip_provenance as cp

ok_n, fails = 0, []
def check(n, c, e=""):
    global ok_n
    if c: ok_n += 1; print("PASS", n)
    else: fails.append(n); print("FAIL", n, e)

E = ct.USD_TO_EUR
scenes = [{"duration": 5}] * 6
check("K1 tier rate = direct: 6 clips, nothing known = USD 7.20 -> EUR", abs(sum(ct.video_cost_for_clip("luma", 5) for _ in scenes) - 7.2 * E) < 1e-9)
check("K2 known direct clip = 1.20 USD", abs(ct.video_cost_for_clip("luma", 5, "luma-ray-3.2-direct") - 1.2 * E) < 1e-9)
check("K3 known fal fallback clip = 2.00 USD", abs(ct.video_cost_for_clip("luma", 5, "luma-ray-2-fallback") - 2.0 * E) < 1e-9)
check("K4 unknown model name -> tier rate (not zero)", abs(ct.video_cost_for_clip("luma", 5, "mystery") - 1.2 * E) < 1e-9)
check("K5 veo unaffected by used_model", abs(ct.video_cost_for_clip("premium", 5, "veo-3.1-fast") - 0.5 * E) < 1e-9)
a = ct.calculate_actual_cost(scenes, ["luma"] * 6, [], model_tier="luma", used_models=["luma-ray-3.2-direct"] * 5 + ["luma-ray-2-fallback"])
check("K6 5 direct + 1 fal = 8.0 USD of video", abs(a["video_eur"] - 8.0 * E) < 1e-3, a["video_eur"])
b = ct.calculate_actual_cost(scenes, ["luma"] * 6, [], model_tier="luma")
check("K7 no used_models -> same as the tier rate (old jobs keep working)", abs(b["video_eur"] - 7.2 * E) < 1e-3)
r = ct.calculate_rework_cost([{"duration": 5}], ["luma"], model_tier="luma", used_models=["luma-ray-2-fallback"])
check("K8 rework priced by real model", abs(r["video_eur"] - 2.0 * E) < 1e-3, r)
d = Path(tempfile.mkdtemp()); (d / "clips").mkdir()
f = d / "clips" / "sc_a.mp4"; f.write_bytes(b"x"); cp.write(f, "luma-ray-3.2-direct", "luma")
check("K9 used_model_of reads the sidecar; missing -> None", cp.used_model_of(f) == "luma-ray-3.2-direct" and cp.used_model_of(d / "clips" / "nope.mp4") is None and cp.used_model_of(None) is None)
import scene_rework as sr
job = {"model_tier": "luma", "cost_actual_raw": {"type": "actual", "total_eur": 1.0, "model_tier": "luma"}}
rc = sr.record_rework_cost(job, [{"scene_id": "sc_a", "duration": 5}], "luma", True, job_dir=d)
check("K10 record_rework_cost uses the sidecar model (direct 1.20)", abs(rc["video_eur"] - 1.2 * E) < 1e-3, rc)
rc2 = sr.record_rework_cost(job, [{"scene_id": "sc_zz", "duration": 5}], "luma", True, job_dir=d)
check("K11 no sidecar -> tier rate", abs(rc2["video_eur"] - 1.2 * E) < 1e-3)
ui = open("ui.html").read()
m = re.search(r"VIDEO_COST_PER_SEC_EUR = \{ luma: ([\d.]+)", ui)
check("K12 UI mirror of the luma rate equals the backend", m and abs(float(m.group(1)) - ct.VIDEO_COST_PER_SEC_EUR["luma"]) < 1e-3, m and m.group(1))
api = open("api_server.py").read()
check("K13 api passes used_models to the actual-cost calculation; rework passes job_dir", "used_models=used_models" in api and "job_dir=job_dir" in api)
print(f"\nRESULT: {'ALL PASS' if not fails else fails} ({ok_n}/{ok_n+len(fails)})")
sys.exit(1 if fails else 0)
