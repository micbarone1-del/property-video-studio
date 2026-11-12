"""Point 3 simulation (2026-11-12): alternative photo after the SECOND rejection of the same scene. Fakes only: no network, no Claude, no Luma.
Run: python3 test_alt_photo_rework.py"""
import os, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alt_photo_rework as apr

res = []
def check(name, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(info)))

def make_job(tmp, auto=("sc_bath",), cats=("living", "kitchen", "bathrooms")):
    d = Path(tmp); (d / "images").mkdir(parents=True, exist_ok=True); (d / "enhanced").mkdir(exist_ok=True); (d / "clips").mkdir(exist_ok=True)
    sids = ["sc_live", "sc_kit", "sc_bath"][:len(cats)]
    for s in sids:
        (d / "images" / f"{s}.jpg").write_bytes(b"OLD-" + s.encode())
        (d / "enhanced" / f"{s}_L1U1_enhanced.jpg").write_bytes(b"ENH-" + s.encode())
        (d / "clips" / f"{s}.mp4").write_bytes(b"CLIP-" + s.encode())
    job = {"scenes_config": [{"scene_id": s, "category": c} for s, c in zip(sids, cats)], "auto_reworked": list(auto),
           "selection_report": {"selected": {}, "candidate_urls": {}}, "rework_counts": {"sc_bath": 1}}
    return job, d

def deps(photo=None, reason="ok", data=b"NEW", allowed=True, calls=None):
    def pick(rep, cat, excl):
        if calls is not None: calls.append((cat, list(excl)))
        return {"photo": photo, "reason": reason}
    return types.SimpleNamespace(pick=pick, fetch=lambda u: data, evaluate=lambda j, ids: {"allowed": allowed, "reasons": [] if allowed else ["cap"]})

os.environ["PVS_AUTO_ALT_PHOTO"] = "1"
P = {"url": "https://x/p7.jpg", "rank_status": "ranked", "feature_visible": True, "quality": "ok"}

with tempfile.TemporaryDirectory() as t:
    job, d = make_job(t)
    out = apr.prepare(job, d, [2], [], deps(P))
    check("S1 twice-rejected scene -> alternative chosen, the scene id is returned for the rework runner", out["scene_ids"] == ["sc_bath"], out)
    check("S2 the new photo is the scene's source image (images/<sid>.jpg)", (d / "images" / "sc_bath.jpg").read_bytes() == b"NEW")
    rej = d / "rejected_photos"
    check("S3 nothing is deleted: old photo, enhanced file and a copy of the clip are in rejected_photos/", len(list(rej.iterdir())) == 3 and (rej / "sc_bath__old.jpg").read_bytes() == b"OLD-sc_bath", sorted(x.name for x in rej.iterdir()))
    check("S4 the old enhanced file is gone from enhanced/ (it would be reused by the rework), the other scenes untouched", not (d / "enhanced" / "sc_bath_L1U1_enhanced.jpg").exists() and (d / "enhanced" / "sc_kit_L1U1_enhanced.jpg").exists() and (d / "images" / "sc_kit.jpg").read_bytes() == b"OLD-sc_kit")
    check("S5 the attempt is recorded in the job (status generating, new url, checks)", job["alt_photo"]["sc_bath"]["status"] == "generating" and job["alt_photo"]["sc_bath"]["new_url"] == P["url"] and job["alt_photo"]["sc_bath"]["feature_visible"] is True, job.get("alt_photo"))
    # outcome: the clip with the alternative photo passes the QC
    ch = apr.record_outcome(job, ["sc_bath"], [], [], [])
    check("S6 alternative clip passes the QC -> accepted (the job goes on by itself)", ch == {"sc_bath": "accepted"} and job["alt_photo"]["sc_bath"]["status"] == "accepted", ch)
    out2 = apr.prepare(job, d, [2], [], deps(P))
    check("S7 ONE alternative per scene: a later reject of the same scene is not tried again", out2["scene_ids"] == [] and "already tried" in out2["reason"], out2)

with tempfile.TemporaryDirectory() as t:
    job, d = make_job(t); apr.prepare(job, d, [2], [], deps(P))
    ch = apr.record_outcome(job, ["sc_bath"], [], [2], [])
    check("S8 alternative clip rejected again -> rejected_again (the job parks for the operator)", ch == {"sc_bath": "rejected_again"}, ch)
with tempfile.TemporaryDirectory() as t:
    job, d = make_job(t); apr.prepare(job, d, [2], [], deps(P))
    ch = apr.record_outcome(job, ["sc_bath"], [], [], [2])
    check("S9 alternative clip flagged -> rejected_again (flags always go to the operator)", ch == {"sc_bath": "rejected_again"}, ch)
with tempfile.TemporaryDirectory() as t:
    job, d = make_job(t); apr.prepare(job, d, [2], [], deps(P))
    ch = apr.record_outcome(job, [], ["sc_bath"], [], [])
    check("S10 alternative clip not generated -> failed", ch == {"sc_bath": "failed"}, ch)

def parked(label, job_kw=None, rejected=[2], flagged=[], dps=None, env=None, expect=""):
    with tempfile.TemporaryDirectory() as t:
        job, d = make_job(t, **(job_kw or {}))
        old = os.environ.get("PVS_AUTO_ALT_PHOTO")
        if env is not None: os.environ["PVS_AUTO_ALT_PHOTO"] = env
        try: out = apr.prepare(job, d, rejected, flagged, dps or deps(P))
        finally: os.environ["PVS_AUTO_ALT_PHOTO"] = old
        untouched = (d / "images" / "sc_bath.jpg").read_bytes() == b"OLD-sc_bath" and not (d / "rejected_photos").exists()
        check(label, out["scene_ids"] == [] and expect in out["reason"] and untouched, (out, untouched))
        return job

parked("S11 no alternative photo of this room (single-photo kitchen case) -> park, reason kept, files untouched", dps=deps(None, "no other photo of this room"), expect="no other photo")
j = parked("S12 alternative photo cannot be downloaded (expired partner URL) -> park", dps=deps(P, data=None), expect="not downloadable")
check("S13 the reason is recorded in the job for the operator", j["alt_photo"]["sc_bath"]["status"] == "none" and "downloadable" in j["alt_photo"]["sc_bath"]["reason"], j.get("alt_photo"))
parked("S14 rework budget used up -> park", dps=deps(P, allowed=False), expect="budget")
parked("S15 a flagged scene in the same stop -> the operator decides everything", flagged=[0], expect="flagged")
parked("S16 scene rejected only once (not in auto_reworked) -> not tried", job_kw={"auto": ()}, expect="not rejected twice")
parked("S17 switch off (default) -> nothing", env="0", expect="switch off")
parked("S18 no reject -> nothing", rejected=[], expect="no reject")
parked("S19 reject index outside the scenes -> park", rejected=[9], expect="no scene_id")
calls = []
with tempfile.TemporaryDirectory() as t:
    job, d = make_job(t, auto=("sc_kit", "sc_bath"))
    out = apr.prepare(job, d, [1, 2], [], deps(P, calls=calls))
    check("S20 two scenes rejected twice -> both get an alternative, the second pick excludes the first url (never the same photo twice)", out["scene_ids"] == ["sc_kit", "sc_bath"] and calls[1][1] == [P["url"]], (out, calls))
with tempfile.TemporaryDirectory() as t:
    job, d = make_job(t, auto=("sc_kit", "sc_bath"))
    n = {"i": 0}
    def pick2(rep, cat, excl):
        n["i"] += 1
        return {"photo": P if n["i"] == 1 else None, "reason": "no other photo of this room"}
    dps = types.SimpleNamespace(pick=pick2, fetch=lambda u: b"NEW", evaluate=lambda j, ids: {"allowed": True, "reasons": []})
    out = apr.prepare(job, d, [1, 2], [], dps)
    check("S21 all or nothing: one scene has no alternative -> no file moved, the job parks as before", out["scene_ids"] == [] and (d / "images" / "sc_kit.jpg").read_bytes() == b"OLD-sc_kit" and not (d / "rejected_photos").exists(), out)

# wiring (source checks, same style as test_rework_qc.py)
src = Path("api_server.py").read_text()
i = src.index("async def _run_redo(")
body = src[i:src.index("async def run_redo_scene(")]
g = src[src.index("async def _rework_qc_gate("):i]
check("S22 the gate records the outcome and tries the alternative BEFORE it parks; an exception there never blocks (falls back to parking)",
      g.index("record_outcome(") < g.index("_apr.prepare") < g.index('"status": "awaiting_approval"') and "non-fatal, the job parks as before" in g)
check("S23 only a pure-reject stop is tried (no flagged scene) and only with the switch on", 'qc["rejected"] and not qc["flagged"] and _apr.enabled()' in g)
check("S24 the runner repeats ITSELF (one runner, no second path) and returns; 'alt' is handled before the parking branch",
      body.index('gate == "alt"') < body.index("if gate:") and 'label="Rework foto alternativa"' in body and body.count("run_reassemble_only(job_id)") == 1)
check("S25 the alternative photo comes from the shared selection step and the one download function", "_ls.pick_alternative_photo" in src and "_ls.fetch_photo_bytes(url, timeout=20)" in src)
print("%d/%d PASS" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
