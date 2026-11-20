"""exp_res_compare.py: plan, blind codes, score, free dry run and the hard spend cap (no Luma call is ever made here). 2026-11-20."""
import json, os, random, sys, tempfile, types
from pathlib import Path
tmp = tempfile.mkdtemp(prefix="rescmp_")
os.environ["PVS_JOBS_DIR"] = tmp
os.environ["PVS_VOLUME_SCRATCH"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_res_compare as x
R = []
def chk(n, c):
    R.append(bool(c)); print(("PASS " if c else "FAIL ") + n)

rows = x.plan_rows()
chk("R1 default plan: 4 scenes x (3 + 2) = 20 clips", len(rows) == 20 and sum(1 for r in rows if r["res"] == "360p") == 12 and sum(1 for r in rows if r["res"] == "1080p") == 8)
chk("R2 the cost is 4 x (3 x 0.06 + 2 x 1.20) = 10.32 USD", x.total_usd(rows) == 10.32)
coded = x.assign_codes(rows, random.Random(1))
chk("R3 20 unique 3-letter codes", len({r["code"] for r in coded}) == 20 and all(len(r["code"]) == 3 and r["code"].isalpha() for r in coded))
res_runs = sum(1 for a, b in zip(coded, coded[1:]) if a["res"] != b["res"])
chk("R4b the order mixes the resolutions (many switches between neighbours)", res_runs >= 5)
lab = {}
for r in coded:
    if r["job"] == "5dc50e0a":   # a scene bad at both resolutions
        lab[r["code"]] = "bad"
    elif r["job"] == "ac81fedd":  # bad only at 360p
        lab[r["code"]] = "bad" if r["res"] == "360p" else "ok"
    elif r["scene"] == 0:         # fine everywhere
        lab[r["code"]] = "ok"
    else:                         # bad only at 1080p
        lab[r["code"]] = "part" if r["res"] == "1080p" else "ok"
keyrows = [dict(r, ok=True) for r in coded]
s = x.score(keyrows, lab)
t = {(a["job"], a["scene"]): a for a in s["table"]}
chk("R5 per-scene counts are right", t[("5dc50e0a", 4)]["360p"] == {"n": 3, "defect": 3, "bad": 3} and t[("5dc50e0a", 4)]["1080p"]["defect"] == 2 and t[("ac81fedd", 5)]["1080p"]["defect"] == 0)
rd = s["reading"]
chk("R6 the 2x2 reading: 1 risky at both, 1 at 360p only, 1 at 1080p only, 1 safe", (rd["risky_both"], rd["risky_360_only"], rd["risky_1080_only"], rd["safe_both"]) == (1, 1, 1, 1) and rd["scenes"] == 4)
keyrows[0]["ok"] = False
s2 = x.score(keyrows, dict(lab, **{coded[1]["code"]: None}))
chk("R7 failed or unlabelled clips are left out and counted", s2["skipped"] == 2)
os.environ.pop("PVS_LUMA_RESOLUTION", None)
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = x.run(11.0, False)
chk("R8 plan without --go spends nothing, writes nothing, never touches the resolution switch", rc == 0 and x.spent() == 0.0 and not x.OUT.exists() and "PVS_LUMA_RESOLUTION" not in os.environ and "10.32" in buf.getvalue())
with contextlib.redirect_stdout(buf):
    rc = x.run(5.0, True)
chk("R9 a cap below the plan refuses to start (nothing spent)", rc == 1 and x.spent() == 0.0)
# the hard cap inside generate(): stub the production function
calls = []
vgm = types.ModuleType("video_generation")
def gen(img, dur, out, **kw):
    calls.append(out); Path(out).write_bytes(b"x"); return True
vgm.generate_video_single = gen
sys.modules["video_generation"] = vgm
x.ev.scene_args = lambda job, i: ("img.jpg", {}, {"category": "bath"})
run_dir = Path(tmp) / "r"; run_dir.mkdir()
row = {"job": "j", "scene": 1, "res": "1080p", "rep": 1, "code": "abc"}
x.add_spend(10.0, "test")
r1 = x.generate(row, run_dir, 11.0)            # 10.0 + 1.20 > 11.0 -> refused
chk("R10 the cap is hard: a clip that would pass it is not started", r1["ok"] is False and r1["why"].startswith("cap reached") and not calls and x.spent() == 10.0)
r2 = x.generate(dict(row, res="360p", code="abd"), run_dir, 11.0)
chk("R11 a cheaper clip under the cap is generated and counted", r2["ok"] is True and len(calls) == 1 and abs(x.spent() - 10.06) < 1e-9)
print("\nRESULT: %d PASS / %d FAIL" % (sum(R), len(R) - sum(R)))
sys.exit(0 if all(R) else 1)
