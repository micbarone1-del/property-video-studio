"""test_exp_validate.py - offline checks of exp_validate (no network, no spend)."""
import json, os, random, sys, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
os.environ["PVS_JOBS_DIR"] = str(tmp); os.environ["PVS_VOLUME_SCRATCH"] = str(tmp / "scratch")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_validate as xv, exp_facade as ef
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n); fails += 0 if c else 1
for j in ("j1", "j2"):
    (tmp / j).mkdir()
    (tmp / j / "job_meta.json").write_text(json.dumps({"scenes_config": [{"category": "living"}, {"category": "kitchen"}, {"category": "living"}, {"category": "exterior"}]}))
ef.OUT.mkdir(parents=True, exist_ok=True)
(ef.OUT / "key_old.json").write_text(json.dumps([{"case": "j1:0"}, {"case": "j2:3"}]))
check("V1 used cases read from earlier key files", xv.used_cases() == {"j1:0", "j2:3"})
s = xv.pick_fresh(["j1", "j2"], 100, xv.used_cases())
check("V2 fresh scenes: used ones excluded, all others taken", len(s) == 6 and ("j1", 0, "living") not in s and ("j2", 3, "exterior") not in s)
s2 = xv.pick_fresh(["j1", "j2"], 4, set())
check("V3 balanced round-robin over categories", len({c for _, _, c in s2}) == 3)
rows = [{"code": f"r{i}", "standard": "reject"} for i in range(4)] + [{"code": f"p{i}", "standard": "pass"} for i in range(40)]
w, rej, pick = xv.review_set(rows, 10, random.Random(1))
check("V4 every reject watched + 10 sampled passes, shuffled together", len(w) == 14 and set(rej) <= set(w) and len(pick) == 10)
lab = {f"r{i}": ("bad" if i < 3 else "ok") for i in range(4)}
lab.update({f"p{i}": ("bad" if i == 0 else "ok") for i in range(40)})
rows_s = xv.review_set(rows, 40, random.Random(2))   # watch every pass
sc = xv.score(rows, lab)
check("V5 score: 3 of 4 rejects bad, 1 bad among 40 passes -> estimated catch 3/4", sc["reject_bad"] == 3 and sc["pass_bad"] == 1 and sc["est_bad_caught"] == 0.75)
check("V6 score: false-reject rate = ok rejects / all ok", sc["est_false_reject_rate"] == round(1 / 40, 3))
check("V7 without --go nothing is spent and a too small budget refuses", xv.main(["--n", "4"]) == 0 and xv.main(["--n", "4", "--budget", "0.1"]) == 1)
rws = [{"code": "a", "ok": True, "standard": "pass"}, {"code": "b", "ok": True, "standard": "reject"}, {"code": "c", "ok": True}, {"code": "d", "ok": False}]
tb = xv.speed_table(rws, {"a": "ok", "b": "part", "d": "bad"}, tmp, measure=lambda p: {"e_all": 5.0 if p.stem == "b" else 2.0}, geo=lambda p: {"new_max": 0.3, "pan_per_s": 0.1})
check("V8 speed table: only watched and generated clips, fastest first", [t[0] for t in tb] == ["b", "a"] and tb[0][1] == "part" and tb[0][3]["new_max"] == 0.3 and tb[0][3]["e_all"] == 5.0)
print("FAILS:", fails); sys.exit(1 if fails else 0)
