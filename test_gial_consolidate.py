"""gial_consolidate.py (2026-11-02): dry run writes nothing; apply copies, never deletes/overwrites; one GIAL agency; keep flag; idempotent. Temp folders only."""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_DATA_DIR"] = str(tmp / "proddata")
import cost_model as cm
import gial_consolidate as gc
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}"))
    fails += 0 if c else 1

P, T = tmp / "prodjobs", tmp / "testjobs"
P.mkdir(); T.mkdir()
prod_ag = [{"agency_id": "ag_prod", "name": "GIAL IMMOBILIARE", "logo_path": "/x/logo.png"}, {"agency_id": "ag_other", "name": "Roma Immobili"}]
test_ag = [{"agency_id": f"ag_t{i}", "name": "GIAL IMMOBILIARE"} for i in range(3)] + [{"agency_id": "ag_tx", "name": "Altra"}]
def mk(base, name, agency, status, msg="", extra=""):
    d = base / name; (d / "images").mkdir(parents=True); (d / "images" / "a.jpg").write_bytes(b"x")
    meta = {"agency_id": agency, "status": status, "property_name": "Appartamento Albano Laziale", "message": msg, "narration_path": f"{base}/{name}/narration.mp3"}
    (d / "job_meta.json").write_text(json.dumps(meta)); return d
mk(P, "pj1", "ag_prod", "failed"); mk(P, "pj2", "ag_t1", "done")                               # already in production (one with a test agency id)
mk(T, "tj1", "ag_t0", "done", "Ricevuto da Relinx (external_ref=T-1186-2c91ff)"); mk(T, "tj2", "ag_t1", "draft"); mk(T, "tj3", "ag_t2", "failed")
mk(T, "pj2", "ag_t1", "done"); mk(T, "other", "ag_tx", "done")
before = {p: p.read_bytes() for p in list(P.rglob("*")) + list(T.rglob("*")) if p.is_file()}
lines = []
rc = gc.run(P, T, prod_ag, test_ag, "useful", False, cm.create_property, out=lambda *a: lines.append(" ".join(map(str, a))))
after = {p: p.read_bytes() for p in list(P.rglob("*")) + list(T.rglob("*")) if p.is_file()}
check("G1 dry run writes nothing (every file identical, nothing new)", rc == 0 and before == after and not (P / "tj1").exists() and not (tmp / "proddata" / "properties.json").exists())
check("G2 the plan names what it would copy for 'useful' (done + draft), not failed ones, not other agencies", any("COPIA tj1" in l for l in lines) and any("COPIA tj2" in l for l in lines) and not any("tj3" in l and "COPIA" in l for l in lines) and not any("other" in l for l in lines), lines)
(T / "tj2" / "job_meta.json").write_text(json.dumps({"agency_id": "ag_t1", "status": "running"}))
rcb = gc.run(P, T, prod_ag, test_ag, "useful", True, cm.create_property, out=lambda *a: None)
check("G3 apply refuses while a job is running (STOP, nothing copied)", rcb == 3 and not (P / "tj1").exists())
(T / "tj2" / "job_meta.json").write_text(json.dumps({"agency_id": "ag_t1", "status": "draft", "property_name": "Appartamento Albano Laziale", "message": "Ricevuto da Relinx (external_ref=T-1235-aa)", "narration_path": f"{T}/tj2/narration.mp3"}))
rc = gc.run(P, T, prod_ag, test_ag, "useful", True, cm.create_property, out=lambda *a: None)
m1 = json.loads((P / "tj1" / "job_meta.json").read_text()); m2 = json.loads((P / "tj2" / "job_meta.json").read_text())
check("G4 copies exist in production with the production agency, keep=True and a property per listing", rc == 0 and m1["agency_id"] == "ag_prod" and m1["keep"] is True and m2["agency_id"] == "ag_prod" and m1["property_id"] != m2["property_id"], (m1, m2))
props = {p["name"]: p for p in cm.list_properties()}
check("G5 properties are named by listing number and belong to the GIAL agency", "Appartamento Albano Laziale · 1186" in props and "Appartamento Albano Laziale · 1235" in props and all(p["agency_id"] == "ag_prod" for p in props.values()), list(props))
check("G6 absolute paths inside the copied job point to production, not to the test folder", str(P) in m1["narration_path"] and str(T) not in m1["narration_path"], m1["narration_path"])
check("G7 the copy is a real copy: the original in the test folder still exists untouched (images, and its meta only gained keep)", (T / "tj1" / "images" / "a.jpg").exists() and json.loads((T / "tj1" / "job_meta.json").read_text())["keep"] is True)
check("G8 jobs already in production were updated (pj1 -> production agency, pj2 test agency -> production), keep=True", json.loads((P / "pj1" / "job_meta.json").read_text())["keep"] is True and json.loads((P / "pj2" / "job_meta.json").read_text())["agency_id"] == "ag_prod")
check("G9 a backup of each changed job_meta.json exists (.bak_p28) and holds the ORIGINAL", json.loads((P / "pj2" / "job_meta.json.bak_p28").read_text())["agency_id"] == "ag_t1")
check("G10 a failed test job and another agency's job were not copied", not (P / "tj3").exists() and not (P / "other").exists())
snap = {p: p.read_bytes() for p in P.rglob("*") if p.is_file()}
rc2 = gc.run(P, T, prod_ag, test_ag, "useful", True, cm.create_property, out=lambda *a: None)
check("G11 running it again changes nothing (idempotent)", rc2 == 0 and snap == {p: p.read_bytes() for p in P.rglob("*") if p.is_file()} and len(cm.list_properties()) == 4)
src = open("gial_consolidate.py").read()
check("G12 the script contains no delete call at all", not any(w in src for w in ("rmtree", ".unlink", "os.remove", "os.rmdir", "rm -")))
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
