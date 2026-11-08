"""listing_registry.py + the duplicate guard (2026-11-08): both folders, measured resolution, 360p does not block 1080p. Run: python3 test_listing_registry.py"""
import os, sys, json, tempfile, subprocess
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import listing_registry as lr
import gial_start as gs
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); fails += 0 if c else 1
def clip(path, w, h):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s={w}x{h}:d=0.5:r=8", "-pix_fmt", "yuv420p", str(path)], check=True)
prod, test = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
def mk(root, name, status, ref, created="2026-11-08T10:00:00", size=None, field=None):
    d = root / name; d.mkdir()
    m = {"status": status, "external_ref": f"T-{ref}-abc123", "created_at": created}
    if field: m["luma_resolution"] = field
    (d / "job_meta.json").write_text(json.dumps(m))
    if size: clip(d / "clips" / "sc_1.mp4", *size)
mk(prod, "p1337hi", "done", "1337", "2026-10-29T10:00:00", size=(1080, 1920))
mk(test, "t1337lo", "done", "1337", size=(360, 640))
mk(test, "t1312lo", "done", "1312", size=(640, 360))
mk(test, "t1312new", "draft", "1312")
mk(test, "t1254", "draft", "1254")
mk(test, "t1290gone", "done", "1290", "2026-11-08T09:00:00")              # clips cleaned: estimated by date
mk(test, "t1291f", "done", "1291", "2026-11-08T09:00:00", field="1080p")  # field wins over the date
recs = lr.scan([("prod", prod), ("test", test)])
by = {r["job_id"]: r for r in recs}
check("R1 resolution is MEASURED from the clips (short side), portrait and landscape", by["p1337hi"]["resolution"] == "1080p" and by["t1337lo"]["resolution"] == "360p" and by["t1312lo"]["resolution"] == "360p" and by["t1337lo"]["source"] == "measured", by)
check("R2 no clips: the job field, else the date (estimated)", by["t1291f"]["resolution"] == "1080p" and by["t1291f"]["source"] == "field" and by["t1290gone"]["resolution"] == "360p" and by["t1290gone"]["source"] == "estimated", by)
check("R3 a 360p video blocks a 360p run but NOT a 1080p run", [r["job_id"] for r in lr.finished_blocking("1312", "360p", recs)] == ["t1312lo"] and lr.finished_blocking("1312", "1080p", recs) == [])
check("R4 a 1080p video blocks every run", [r["job_id"] for r in lr.finished_blocking("1337", "1080p", recs)] == ["p1337hi"] and sorted(r["job_id"] for r in lr.finished_blocking("1337", "360p", recs)) == ["p1337hi", "t1337lo"])
check("R5 a draft or failed job never blocks; the job itself is excluded", lr.finished_blocking("1254", "360p", recs) == [] and lr.finished_blocking("1312", "360p", recs, exclude_job="t1312lo") == [])
# the guard: the draft lives in the TEST folder, the finished video in the PRODUCTION folder (the 2026-11-08 case)
lr.PROD_JOBS, lr.TEST_JOBS = prod, test
mk(test, "t1337draft", "draft", "1337")
check("G1 the draft is found in the test folder and the production video of the same listing is seen", gs.same_listing_done("t1337draft", None, "360p") == ["p1337hi", "t1337lo"] or sorted(gs.same_listing_done("t1337draft", None, "360p")) == ["p1337hi", "t1337lo"], gs.same_listing_done("t1337draft", None, "360p"))
check("G2 at 1080p only the 1080p video blocks", gs.same_listing_done("t1337draft", None, "1080p") == ["p1337hi"])
check("G3 1312 draft is NOT a duplicate for a 1080p run (only 360p exists), but is for a 360p run", gs.same_listing_done("t1312new", None, "1080p") == [] and gs.same_listing_done("t1312new", None, "360p") == ["t1312lo"])
check("G4 an unknown job id gives no duplicate", gs.same_listing_done("zzz", None, "360p") == [])
check("R6 best finished resolution per listing", lr.best_done(recs, "1337") == "1080p" and lr.best_done(recs, "1312") == "360p" and lr.best_done(recs, "1254") == "-")
src = open("listing_registry.py").read()
check("R7 read only: writes no file, no delete", not any(w in src for w in ("rmtree", "unlink", "os.remove", "shutil", "write_text", "open(")))
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
