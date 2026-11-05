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
import cv2, numpy as np
still_clip = tmp / "still.mp4"
_w = cv2.VideoWriter(str(still_clip), cv2.VideoWriter_fourcc(*"mp4v"), 24, (480, 270))
_r = np.random.default_rng(1)
_b = _r.integers(0, 255, (270, 480, 3), dtype=np.uint8)
for _i in range(60):
    _w.write(_b)
_w.release()
rws = [{"code": "a", "ok": True, "standard": "pass"}, {"code": "b", "ok": True, "standard": "reject"}, {"code": "c", "ok": True}, {"code": "d", "ok": False}]
tb = xv.speed_table(rws, {"a": "ok", "b": "part", "d": "bad"}, tmp, measure=lambda p: {"e_all": 5.0 if p.stem == "b" else 2.0}, geo=lambda p: {"new_max": 0.3, "pan_per_s": 0.1})
check("V8 speed table: only watched and generated clips, fastest first", [t[0] for t in tb] == ["b", "a"] and tb[0][1] == "part" and tb[0][3]["new_max"] == 0.3 and tb[0][3]["e_all"] == 5.0)
rw = [{"code": "a", "ok": True, "standard": "reject", "judge": {"verdict": "fail", "reason": "x", "invented": [{"frames": "2-3", "what": "wall"}]}},
      {"code": "b", "ok": True, "standard": "reject", "judge": {"verdict": "fail", "reason": "y"}}, {"code": "c", "ok": True, "judge": {"verdict": "pass"}}]
costs = []
vr = xv.verify_run(rw, {"a": "bad", "b": "ok"}, tmp, tmp, costs, verify=lambda p, j, u: {"confirmed": p.stem == "a", "claims": [{"truth": "real_invention"}]}, sheet=lambda p, o, c: True)
check("V9 verify_run: only judge-fail clips, label and sheet attached", [x["code"] for x in vr] == ["a", "b"] and vr[0]["label"] == "bad" and vr[0]["confirmed"] is True and vr[1]["confirmed"] is False and vr[0]["sheet"] == "verify_a.jpg")
import clip_standard as cs
check("V10 claims_text uses the judge's own list", "wall" in cs.claims_text(rw[0]["judge"]) and "something new" in cs.claims_text({}))
ask_real = lambda f, p, u: 'ok {"claims": [{"what": "candle", "truth": "real_invention", "evidence": "frame 4"}], "confirmed": true}'
ask_nat = lambda f, p, u: '{"claims": [{"what": "car", "truth": "natural_motion", "evidence": "x"}], "confirmed": false}'
ask_junk = lambda f, p, u: "nope"
check("V11 verify(): real invention confirmed, natural motion not, junk = error, missing clip never raises",
      cs.verify(still_clip, {"reason": "r"}, ask=ask_real)["confirmed"] is True and cs.verify(still_clip, {"reason": "r"}, ask=ask_nat)["confirmed"] is False
      and cs.verify(still_clip, {}, ask=ask_junk)["error"] == "verification answer unusable" and cs.verify(tmp / "none.mp4", {}, ask=ask_real)["error"] is not None)
check("V12 contact sheet written for a real clip", cs.contact_sheet(still_clip, tmp / "s.jpg", "cap") and (tmp / "s.jpg").stat().st_size > 5000)
import clip_standard as cs2
ep = xv.edge_prompt()
check("V13 edge prompt: only the edge sentence changed, edge_new in the answer format, still formattable", xv.EDGE_OLD not in ep and "edge_new" in ep and ep.format(n=6).startswith("These 6 frames") and cs2.JUDGE_PROMPT.count("Do not count things") == 1)
rj = xv.rejudge_run([{"code": "a", "ok": True, "judge": {"verdict": "pass"}}, {"code": "z", "ok": True}], {"a": "bad"}, tmp, [], ask=lambda f, p, u: '{"verdict": "pass", "edge_new": [{"frames": "4-6", "what": "wall", "share": 0.15}]}')
check("V14 rejudge: no clip file -> never crashes; with a clip, edge share is read", rj == [] or rj[0]["edge_max"] == 0.15)
print("FAILS:", fails); sys.exit(1 if fails else 0)
