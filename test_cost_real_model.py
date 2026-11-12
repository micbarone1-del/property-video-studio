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
m = re.search(r"VIDEO_COST_PER_SEC_EUR = \{ luma: lumaEurPerSec \|\| ([\d.]+)", ui)
check("K12 UI: Luma rate comes from the server (/cost/infra); the only literal left is the 1080p value used before it loads, equal to the backend", m and abs(float(m.group(1)) - ct.luma_eur_per_sec("1080p")) < 1e-3 and "lumaEurPerSec = ci.luma_eur_per_sec" in ui and "luma_eur_per_sec" in open("api_server.py").read(), m and m.group(1))
api = open("api_server.py").read()
check("K13 api passes used_models to the actual-cost calculation; rework passes job_dir", "used_models=used_models" in api and "job_dir=job_dir" in api)
# ---- 2026-10-27: Luma is always one 5 s clip per scene (job 26d7a774 showed EUR 11.04 for a job of EUR 6.62) ----
import types as _t
for _n in ("fal_client", "moviepy", "anthropic"):
    sys.modules.setdefault(_n, _t.ModuleType(_n))
import narration as _nar
ui_src = open("ui.html", encoding="utf-8").read()
est = ct.estimate_job_cost([{"duration": d, "voiceover": ""} for d in (8, 9, 7, 10, 6, 8)], model_tier="luma", do_upscale=False, do_vision_qc=False)
check("K14 estimate for 6 Luma scenes of any narration length = 6 clips of 5 s (EUR 6.62), not the narration seconds", abs(est["video_eur"] - 6 * 5 * ct.VIDEO_COST_PER_SEC_EUR["luma"]) < 1e-3 and abs(est["video_eur"] - 6.624) < 1e-2, est["video_eur"])
check("K15 the rework estimate and the actual cost use the same fixed 5 s", abs(ct.video_cost_for_clip("luma", 9) - ct.video_cost_for_clip("luma", 5)) < 1e-9 and abs(ct.video_cost_for_clip("luma", 9, "luma-ray-3.2-direct") - 1.2 * E) < 1e-9)
check("K16 Veo is still billed per second of the scene (unchanged)", abs(ct.video_cost_for_clip("premium", 8) - 8 * ct.VIDEO_COST_PER_SEC_EUR["premium"]) < 1e-9)
check("K17 ONE value: cost_tracker.LUMA_CLIP_SECS == narration.FIXED_SCENE_SECS_BY_TIER['luma'] == the UI duration slider for luma", ct.LUMA_CLIP_SECS == _nar.FIXED_SCENE_SECS_BY_TIER["luma"] == 5 and re.search(r"if \(tier === 'luma'\) return \{min: 5, max: 5, step: 1, def: 5", ui_src) is not None)
check("K18 the UI estimate takes the Luma seconds from that slider table, not from the scene's narration length", "getDurationRangeForTier('luma').def" in ui_src and "(sc.duration || 8) * rate" not in ui_src)
mq = re.search(r"const CLIP_QC_EST\s*=\s*([\d.]+)", ui_src)
check("K19 the UI clip-QC cost equals the backend constant (Claude vision), the old Florence constant is gone", mq and abs(float(mq.group(1)) - ct.CLIP_QC_EST_EUR_PER_CLIP) < 1e-9 and "FLORENCE" not in ui_src, mq and mq.group(1))
check("K20 labels say Luma Ray 3.2 (UI dropdown, UI cost lines, backend cost report); no 'Ray 2' label left", "Luma Ray 3.2 (~" in ui_src and "luma: 'Luma Ray 3.2'" in ui_src and '"luma":     "Luma Ray 3.2"' in open("cost_tracker.py").read() and "Luma Ray 2 (~" not in ui_src)
# ---- 2026-11-12: Luma price BY RESOLUTION (360p test jobs were priced at the 1080p rate: EUR 6.62 shown for 6 clips that cost USD 0.36) ----
import os as _os
_old = _os.environ.get("PVS_LUMA_RESOLUTION")
_os.environ["PVS_LUMA_RESOLUTION"] = "360p"
check("K17 360p: 6 clips = USD 0.36", abs(sum(ct.video_cost_for_clip("luma", 5) for _ in scenes) / E - 0.36) < 1e-9)
check("K18 360p: estimate = actual = rework price of one clip (same table)", abs(ct.estimate_job_cost(scenes, model_tier="luma", do_upscale=False, do_vision_qc=False)["video_eur"] - 6 * 0.06 * E) < 1e-3 and abs(ct.calculate_rework_cost([{"duration": 5}], [], True, model_tier="luma")["video_eur"] - 0.06 * E) < 1e-3)
check("K19 360p: known direct clip = 0.06, fal fallback still 2.00", ct.clip_price_usd("luma-ray-3.2-direct") == 0.06 and ct.clip_price_usd("luma-ray-2-fallback") == 2.0)
check("K20 360p is a measured price", ct.luma_price_is_measured())
_os.environ["PVS_LUMA_RESOLUTION"] = "720p"
check("K21 unmeasured resolution is priced like 1080p and flagged", ct.luma_direct_usd_per_clip() == 1.2 and not ct.luma_price_is_measured())
_os.environ.pop("PVS_LUMA_RESOLUTION", None)
check("K22 default (no switch) = 1080p 1.20", ct.luma_direct_usd_per_clip() == 1.2 and ct.luma_price_is_measured())
check("K23 explicit resolution argument wins over the switch", ct.luma_direct_usd_per_clip("360p") == 0.06 and ct.luma_direct_usd_per_clip("1080p") == 1.2)
check("K24 the 1.20 / 0.06 literals live once, in cost_tracker", len(re.findall(r"LUMA_DIRECT_USD_PER_CLIP_BY_RES\s*=", open("cost_tracker.py").read())) == 1)
if _old is not None: _os.environ["PVS_LUMA_RESOLUTION"] = _old

print(f"\nRESULT: {'ALL PASS' if not fails else fails} ({ok_n}/{ok_n+len(fails)})")
sys.exit(1 if fails else 0)
