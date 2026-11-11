import os, re, json, tempfile, importlib
from pathlib import Path
fails = 0
def check(n, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + n); fails += 0 if ok else 1
import video_generation as vg
old = os.environ.pop("PVS_LUMA_RESOLUTION", None)
check("L1 default is 1080p", vg.luma_resolution() == "1080p")
os.environ["PVS_LUMA_RESOLUTION"] = "360p"; check("L2 360p when set", vg.luma_resolution() == "360p")
os.environ["PVS_LUMA_RESOLUTION"] = "  "; check("L3 blank means 1080p", vg.luma_resolution() == "1080p")
if old is None: os.environ.pop("PVS_LUMA_RESOLUTION", None)
else: os.environ["PVS_LUMA_RESOLUTION"] = old
n = {f: len(re.findall(r"PVS_LUMA_RESOLUTION", open(f).read())) for f in ("video_generation.py", "api_server.py", "gial_start.py")}
check("L4 the environment variable is read in ONE place only (video_generation.py)", n["api_server.py"] == 0 and n["gial_start.py"] == 0 and n["video_generation.py"] <= 3)
check("L5 run_pipeline writes the flag on the job", 'JOBS[job_id]["luma_resolution"] = luma_resolution()' in open("api_server.py").read())
import listing_registry as lr
with tempfile.TemporaryDirectory() as d:
    check("L6 the registry reads the flag when there are no clips", lr.resolution_of(Path(d), {"luma_resolution": "360p"}) == ("360p", "field"))
print("FAILS:", fails)
