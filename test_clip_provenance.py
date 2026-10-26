"""Patch A (2026-10-15): clip provenance sidecars, fal warning data, shared clip resolver, shared prompt rule.
Run: python3 test_clip_provenance.py"""
import os, re, sys, json, tempfile
from pathlib import Path
REPO = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, REPO)
import clip_provenance as cp
import cost_tracker as ct
res = []
def check(n, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + n + ("" if ok else f" -- {info}"))

# P1 classification
check("P1a direct luma tier is NOT a fal substitute", not cp.is_fal_substitute("luma-ray-3.2-direct", "luma"))
check("P1b luma-ray-2-fallback is", cp.is_fal_substitute("luma-ray-2-fallback", "luma"))
check("P1c veo fallback and ltx emergency are", cp.is_fal_substitute("veo-3.1-fallback", "luma") and cp.is_fal_substitute("ltx-emergency", "premium"))
check("P1d luma tier on plain fal Ray 2 (direct switched off) is flagged", cp.is_fal_substitute("luma-ray-2", "luma"))
check("P1e premium tier normal Veo Fast is NOT flagged (fal is its normal provider)", not cp.is_fal_substitute("veo-3.1-fast", "premium"))

tmp = Path(tempfile.mkdtemp(prefix="pvsprov_")); (tmp / "clips").mkdir()
def mk(name):
    p = tmp / "clips" / name; p.write_bytes(b"x"); return p

# P2 sidecar round trip, never raises
a = mk("sc_a.mp4")
check("P2a write returns True and read gives the data", cp.write(a, "luma-ray-2-fallback", "luma", "Luma diretto: HTTP 402") and cp.read(a)["model"] == "luma-ray-2-fallback" and cp.read(a)["fal_substitute"] is True and "402" in cp.read(a)["reason"])
check("P2b write into a missing folder returns False and does not raise", cp.write(tmp / "nope" / "x.mp4", "m", "luma") is False)
check("P2c read of a clip without sidecar is None", cp.read(mk("scene_009.mp4")) is None)
check("P2d the sidecar is not matched by a *.mp4 glob", not any(str(x).endswith(".model.json") for x in (tmp / "clips").glob("*.mp4")))

# P3 resolver: scene_id first, then legacy, else None (same order as the reassemble step)
mk("scene_005.mp4"); new = mk("sc_b774d3a0.mp4")
check("P3a rework case: scene_id clip wins over legacy scene_005", cp.clip_file_for_scene(tmp, 5, "sc_b774d3a0") == new)
check("P3b only legacy exists -> legacy", cp.clip_file_for_scene(tmp, 5, "sc_missing").name == "scene_005.mp4")
check("P3c neither exists -> None", cp.clip_file_for_scene(tmp, 7, "sc_none") is None)
check("P3d no scene_id given -> legacy", cp.clip_file_for_scene(tmp, 5, None).name == "scene_005.mp4")

# P4 summary
t2 = Path(tempfile.mkdtemp(prefix="pvsprov2_")); (t2 / "clips").mkdir()
cfg = []
for i in range(6):
    sid = f"sc_{i}"; (t2 / "clips" / f"{sid}.mp4").write_bytes(b"x"); cfg.append({"scene_id": sid, "duration": 5})
cp.write(t2 / "clips" / "sc_0.mp4", "luma-ray-3.2-direct", "luma")
cp.write(t2 / "clips" / "sc_2.mp4", "luma-ray-2-fallback", "luma", "Luma diretto: HTTP 402 - crediti o budget Luma esauriti")
cp.write(t2 / "clips" / "sc_3.mp4", "luma-ray-2-fallback", "luma", "Luma diretto: HTTP 402 - crediti o budget Luma esauriti")
cp.write(t2 / "clips" / "sc_4.mp4", "veo-3.1-fallback", "luma", "x")
u = cp.summarize(t2, cfg)
check("P4a counts only fal clips (3), skips direct and no-sidecar", u["fal_clips"] == 3 and [c["index"] for c in u["clips"]] == [2, 3, 4], u)
check("P4b level high when Veo is involved", u["level"] == "high", u["level"])
check("P4c estimated fal cost 2+2+0.50 = 4.50 and direct equivalent 3 x 1.20 = 3.60", u["est_usd_on_fal"] == 4.5 and u["est_usd_if_direct"] == 3.6, u)
check("P4d reason carried to the UI data", "402" in (u["clips"][0]["reason"] or ""))
t3 = Path(tempfile.mkdtemp(prefix="pvsprov3_")); (t3 / "clips").mkdir(); (t3 / "clips" / "sc_0.mp4").write_bytes(b"x")
cp.write(t3 / "clips" / "sc_0.mp4", "luma-ray-2-fallback", "luma", "r")
u3 = cp.summarize(t3, [{"scene_id": "sc_0", "duration": 5}])
check("P4e only Ray 2 -> level fal (not high)", u3["level"] == "fal" and u3["fal_clips"] == 1, u3)
check("P4f nothing from fal -> level none, 0 clips; empty config is safe", cp.summarize(t2.parent / "nodir", cfg)["fal_clips"] == 0 and cp.summarize(t2, None)["level"] == "none")

# P5 prices defined once
check("P5a prices", ct.clip_price_usd("luma-ray-3.2-direct") == 1.2 and ct.clip_price_usd("luma-ray-2-fallback") == 2.0 and ct.clip_price_usd("veo-3.1-fallback", 6) == 0.6 and ct.clip_price_usd("unknown") is None)
check("P5b job cost table: luma = DIRECT rate 0.2208 EUR/s (changed 2026-10-26 from the fal 0.368), veo fast 0.092 unchanged", abs(ct.VIDEO_COST_PER_SEC_EUR["luma"] - 0.2208) < 1e-9 and abs(ct.VIDEO_COST_PER_SEC_EUR["premium"] - 0.092) < 1e-9)
check("P5c the fal Ray 2 price literal exists once in cost_tracker", len(re.findall(r"LUMA_RAY2_FAL_USD_PER_CLIP\s*=", open("cost_tracker.py").read())) == 1)

# P6 wiring (source level: api_server / ui import heavy modules)
api = open("api_server.py").read(); ui = open("ui.html").read(); vg = open("video_generation.py").read()
check("P6a get_clip uses the shared resolver", "clip_provenance.clip_file_for_scene(JOBS_DIR / job_id, scene_index, _sid)" in api)
check("P6b get_job returns fal_usage", 'job["fal_usage"] = clip_provenance.summarize(' in api)
check("P6c UI has the red banner and calls it on every job fetch (poll + 3 loads)", 'id="fal-warning"' in ui and ui.count("renderFalWarning(") >= 5, ui.count("renderFalWarning("))
check("P6d generation writes the sidecar once, after a successful download", vg.count("clip_provenance.write(") == 1)
check("P6e FAL_FALLBACK_ENABLED gate sits between direct failure and fal Ray 2", re.search(r"if not FAL_FALLBACK_ENABLED:.*?return False.*?_generate_luma\(image_url", vg, re.S) is not None)
check("P6f FAL_FALLBACK_ENABLED defaults to true", 'os.environ.get("FAL_FALLBACK_ENABLED", "true")' in vg)
print("RESULT:", "ALL PASS" if all(res) else "FAILURES", f"({sum(res)}/{len(res)})")
sys.exit(0 if all(res) else 1)
