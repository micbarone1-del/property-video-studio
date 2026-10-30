"""test_video_library.py - video library: classification by agency, copy-only, idempotent, review kept. Temp folders only."""
import hashlib, json, os, re, sys, tempfile
from pathlib import Path
import video_library as vl
fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def snap(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file(): h.update(str(p).encode()); h.update(p.read_bytes())
    return h.hexdigest()

tmp = Path(tempfile.mkdtemp())
jobs, agencies, out, scratch = tmp / "jobs", tmp / "agencies.json", tmp / "lib", tmp / "scratch"
jobs.mkdir()
agencies.write_text(json.dumps([{"agency_id": "a1", "name": "GIAL IMMOBILIARE"}, {"agency_id": "a2", "name": "GIAL IMMOBILIARE"}, {"agency_id": "a3", "name": "Altra Agenzia"}]))
def job(jid, status, agency_id, ref, with_video=True, cost=8.5):
    d = jobs / jid; d.mkdir()
    v = d / "Villa_Roma_final.mp4"
    if with_video: v.write_bytes(b"VIDEO" + jid.encode() * 100)
    (d / "job_meta.json").write_text(json.dumps({"status": status, "agency_id": agency_id, "external_ref": ref, "property_name": "Villa in vendita a Roma",
        "output_path": str(v), "created_at": "2026-10-29T19:14:00", "cost_actual": {"grand_total_eur": cost}, "upscale_images": False, "source": "relinx"}))
job("j1", "done", "a1", "T-1337-abc123")
job("j2", "done", "a2", "T-1290-def456")     # a different client record with the SAME name
job("j3", "done", "a3", "XYZ-9")
job("j4", "running", "a1", "T-1-x")           # not finished
job("j5", "done", "a1", "T-2-y", with_video=False)   # finished but the file is missing
src = [("test", jobs, agencies)]
before = snap(jobs)

e = vl.collect(src)
check("V1 only finished jobs with a real video file are found (3 of 5)", sorted(x["job_id"] for x in e) == ["j1", "j2", "j3"], [x["job_id"] for x in e])
check("V2 listing id is read from the T-<id>- reference, other refs are kept as they are", {x["job_id"]: x["listing_ref"] for x in e} == {"j1": "1337", "j2": "1290", "j3": "XYZ-9"})
new, _ = vl.run_copy(e, out, False)
check("V3 dry run writes nothing", new == 3 and not out.exists())
new, idx = vl.run_copy(e, out, True)
folders = sorted(p.name for p in out.iterdir() if p.is_dir())
check("V4 copy groups by agency NAME: the two GIAL client records share one folder", folders == ["altra-agenzia", "gial-immobiliare"], folders)
check("V5 three videos copied, each with its own card, and an index (json + html)", len(list(out.rglob("*.mp4"))) == 3 and len(list(out.rglob("j*.json"))) == 3 and (out / "index.json").exists() and (out / "index.html").exists())
check("V6 the copy is byte-identical to the source", (out / idx["j1"]["file"]).read_bytes() == (jobs / "j1" / "Villa_Roma_final.mp4").read_bytes())
check("V7 jobs/ untouched (same files, same bytes)", snap(jobs) == before)
vl.mark(out, "j1", "yes", "ok da riusare per GIAL")
new2, idx2 = vl.run_copy(e, out, True)
check("V8 a second run copies nothing and keeps Michele's review", new2 == 0 and idx2["j1"]["review"]["reusable"] is True and idx2["j1"]["review"]["note"] == "ok da riusare per GIAL")
check("V9 unreviewed videos start as to_review / reusable unknown", idx2["j2"]["review"] == {"status": "to_review", "reusable": None, "note": ""})
page = (out / "index.html").read_text(encoding="utf-8")
check("V10 html index lists each agency and links to the files", "GIAL IMMOBILIARE (2)" in page and "Altra Agenzia (1)" in page and idx2["j1"]["file"] in page)
url = vl.publish(out, "j2", scratch=scratch, public="https://example.test/ts/")
fn = url.rsplit("/", 1)[1]
check("V11 publish adds one file with a random name to the scratch folder and returns the https link", (scratch / fn).is_file() and fn.startswith("lib_j2_") and url.startswith("https://example.test/ts/") and len(fn) > 20)
src_text = open("video_library.py", encoding="utf-8").read()
check("V12 the tool has no delete or move calls", not re.search(r"os\.remove|os\.unlink|rmtree|\.unlink\(|shutil\.move|os\.rename|\.rename\(", src_text))
check("V13 the library folder is outside the repository and outside jobs/", str(vl.DEFAULT_OUT) == "/var/www/pvs_library")
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
