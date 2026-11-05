"""exp_qc_combo.py - FREE: judge + motion extremes + new_frac (rotation / new content) TOGETHER on the labelled clips (2026-11-05). EXPERIMENT TOOL, NOT PRODUCTION.
Reads the files the other tools already saved: motion_calibration.json (exp_motion_cal), rotation_calibration.json (exp_rotation) and the judge answers (exp_judge).
No clip is read, nothing is spent. In-sample thresholds: the numbers are optimistic.
  python3 exp_qc_combo.py          PVS_VOLUME_SCRATCH = where the runs are
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (HERE / "jobs" / "_test_scratch"))
OUT = SCRATCH / "facade"
THRESHOLDS = (0.1, 0.15, 0.2, 0.3)


def extremes(r: dict) -> bool:
    """the motion_extremes rule of exp_motion_cal (acceleration or vertical drift)."""
    return (r.get("accel_last_over_first") or 0) >= 11.8 or (r.get("drift_y_std_px_s") or 0) >= 4.5


def merge(motion_rows, rot_rows, judge) -> list:
    """one dict per labelled clip that has all three: motion measures, new_frac and a judge verdict."""
    rot = {(r["run"], r["code"]): r for r in rot_rows}
    out = []
    for m in motion_rows:
        k = (m["run"], m["code"])
        if k in rot and m["code"] in judge.get(m["run"], {}):
            out.append(dict(m, new_frac=rot[k]["new_frac"], jv=judge[m["run"]][m["code"]]))
    return out


def rules(thr) -> dict:
    return {
        "judge": lambda r: r["jv"] in ("review", "fail"),
        "extremes": extremes,
        f"new_frac>={thr}": lambda r: r["new_frac"] >= thr,
    }


def evaluate(rows, combo) -> dict:
    bad = [r for r in rows if r["cls"] == "bad"]
    ok = [r for r in rows if r["cls"] == "ok"]
    f = lambda r: any(fn(r) for fn in combo)
    return {"bad": len(bad), "caught": sum(1 for r in bad if f(r)), "ok": len(ok), "flagged": sum(1 for r in ok if f(r)),
            "missed": [f"{r['run']}/{r['code']}" for r in bad if not f(r)]}


def main() -> int:
    import exp_motion_cal as mc
    motion = json.loads((OUT / "motion_calibration.json").read_text())
    rot = json.loads((OUT / "rotation_calibration.json").read_text())
    judge = {run: mc.judge_by_code(run) for run in {r["run"] for r in motion}}
    rows = merge(motion, rot, judge)
    print(f"{len(rows)} labelled clips with judge + motion + new_frac ({sum(1 for r in rows if r['cls'] == 'bad')} bad, {sum(1 for r in rows if r['cls'] == 'ok')} ok)")
    base = rules(0.2)
    for name, combo in (("judge", [base["judge"]]), ("judge + extremes", [base["judge"], base["extremes"]])):
        e = evaluate(rows, combo)
        print(f"  {name:34s} catches {e['caught']}/{e['bad']} bad, flags {e['flagged']}/{e['ok']} ok")
    for t in THRESHOLDS:
        R = rules(t)
        e = evaluate(rows, [R["judge"], R["extremes"], R[f"new_frac>={t}"]])
        print(f"  judge + extremes + new_frac>={t:<5} catches {e['caught']}/{e['bad']} bad, flags {e['flagged']}/{e['ok']} ok")
        if t == 0.15:
            print("    bad clips still missed at 0.15:", " ".join(e["missed"]) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
