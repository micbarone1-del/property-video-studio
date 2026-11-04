"""test_exp_judge.py - offline checks of exp_judge (no network, no spend)."""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_judge as ej
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
lab = ej.load_labels(Path(__file__).resolve().parent / "judge_labels_1104_144423.json")
check("J1 labels: every code in one class, 3-letter codes", all(len(c) == 3 for c in lab) and set(lab.values()) == {"bad", "part", "ok"} and lab["shy"] == "bad" and lab["xat"] == "ok" and lab["gra"] == "part")
usage = {}
def fake_ask(prompt, imgs, u):
    u["in"] = u.get("in", 0) + 3000; u["out"] = u.get("out", 0) + 300
    return {"verdict": "FAIL", "direction": "sideways", "speed": "fast", "reason": "x"}
r = ej.judge_clip("x.mp4", "abc", usage, ask=fake_ask, frames=["f1", "f2"])
check("J2 verdict is normalised to lower case and the prompt carries the frame count", r["verdict"] == "fail" and "2 frames" in ej.JUDGE_PROMPT.format(n=2))
check("J3 an unknown verdict becomes review (never silently pass)", ej.judge_clip("x", "a", {}, ask=lambda p, i, u: {"verdict": "maybe"}, frames=["f"])["verdict"] == "review")
check("J4 spend estimate from tokens", ej.spend_usd({"in": 1000000, "out": 100000}) == 4.5)
s = ej.score([("bad", "fail"), ("bad", "pass"), ("bad", "review"), ("ok", "pass"), ("ok", "pass"), ("ok", "review"), ("part", "fail")])
check("J5 score: bad caught 2/3, 1 missed, ok flagged 1/3", abs(s["bad_caught"] - 2 / 3) < 1e-9 and s["bad_missed"] == 1 and abs(s["ok_false_alarm"] - 1 / 3) < 1e-9 and s["ok_fail"] == 0)
o = ej.order_flagged([{"verdict": "pass", "code": "a"}, {"verdict": "fail", "code": "b"}, {"verdict": "review", "code": "c"}, {"verdict": "fail", "code": "d"}])
check("J6 flagged first: fail, review, pass; stable", [x["code"] for x in o] == ["b", "d", "c", "a"])
import tempfile
ej.OUT = Path(tempfile.mkdtemp())
(ej.OUT / "key_a.json").write_text("[]"); import time; time.sleep(0.02); (ej.OUT / "key_b.json").write_text("[]")
check("J7 'last' picks the newest run, a given id is kept", ej.resolve_run("last") == "b" and ej.resolve_run("a") == "a")
sm = ej.summarise([{"variant": "P", "verdict": "fail", "direction": "backward", "speed": "slow"}, {"variant": "P", "verdict": "pass", "direction": "toward_main_subject", "speed": "slow"},
                   {"variant": "L", "verdict": "pass", "direction": "static", "speed": "static"}])
check("J8 summary counts verdicts and directions per variant", sm["P"]["n"] == 2 and sm["P"]["fail"] == 1 and sm["P"]["pass"] == 1 and sm["P"]["directions"]["backward"] == 1 and sm["L"]["speeds"] == {"static": 1})
import io, contextlib
(ej.OUT / "key_s.json").write_text(json.dumps([{"code": "abc", "case": "j:1", "variant": "E2", "rep": 1, "plan": "forward -> the wall", "prompt": "P" * 900, "speed": {"e_all": 5.5}}]))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ej.show("s", ["abc", "zzz"])
out = buf.getvalue()
check("J9 show prints variant, plan, speed and a cut prompt, and says when a code is missing", "variant E2" in out and "forward -> the wall" in out and "e_all 5.5" in out and out.count("P") <= 720 and "zzz: not in run" in out)
sys.exit(1 if fails else 0)
