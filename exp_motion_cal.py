"""exp_motion_cal.py - FREE objective measures of a clip (no Claude, no Luma) calibrated on Michele's blind labels (2026-11-04).
Why: the Claude judge missed a rotating clip (ley) and false-alarmed others; rotation, sideways drift and rushing are MOTION facts that can be measured locally.
For every labelled clip it takes the measures already in the repo (exp_clipeval.summarise: sideways / vertical drift of the picture centre, zig-zag, zoom rate,
acceleration; clip_speed_probe.speed: motion energy, and that energy relative to the median of the clips of the SAME scene), prints the mean per class (bad / part / ok)
and, for each measure, the best single threshold between bad and ok with how many bad clips it catches and how many ok clips it would flag. No decision is taken here.

  python3 exp_motion_cal.py [--labels motion_labels.json]      PVS_VOLUME_SCRATCH = where the runs are
  python3 exp_motion_cal.py report RUN_ID|last                FREE (after exp_judge run): the loop's report: share of flagged clips per configuration (judge + motion extremes), the winner by the stated rule, the clips Michele should watch
  python3 exp_motion_cal.py ensemble                          FREE, after the above: judge verdict and motion measures TOGETHER on the labelled clips (needs the saved judge answers of the runs)
"""
import json
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (HERE / "jobs" / "_test_scratch"))
OUT = SCRATCH / "facade"
METRICS = ("drift_x_std_px_s", "drift_y_std_px_s", "wobble_x_reversals", "wobble_y_reversals", "accel_last_over_first", "jerk", "zoom_rate_mean_per_s", "e_all", "rel_e")


def load_labels(path) -> list:
    """[(run, code, class)]"""
    d = json.loads(Path(path).read_text())
    return [(run, code, cls) for run, v in d.items() if isinstance(v, dict) for cls in ("bad", "part", "ok") for code in v.get(cls, [])]


def best_threshold(bad: list, ok: list):
    """(threshold, caught share of bad, flagged share of ok) for 'value >= threshold is a defect', maximising caught - flagged. None when a class is empty."""
    if not bad or not ok:
        return None
    best = None
    for t in sorted(set(bad + ok)):
        caught = sum(1 for v in bad if v >= t) / len(bad)
        flagged = sum(1 for v in ok if v >= t) / len(ok)
        score = caught - flagged
        if best is None or score > best[0] + 1e-9:
            best = (score, t, caught, flagged)
    return best[1], best[2], best[3]


def clip_measures(path) -> dict:
    import exp_clipeval as ce
    import clip_speed_probe as sp
    frames, fps = ce.read_frames(path)
    m = ce.summarise(frames, fps) if len(frames) >= 24 else {}
    out = {k: m.get(k) for k in METRICS if k != "e_all" and k != "rel_e"}
    out["e_all"] = sp.speed(path).get("e_all")
    return out


def main(labels_file):
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    rows = []
    cases = {}
    for run, code, cls in load_labels(labels_file):
        p = OUT / run / f"{code}.mp4"
        if not p.is_file():
            print(f"{run}/{code}: clip not found"); continue
        try:
            key = {k["code"]: k["case"] for k in json.loads((OUT / f"key_{run}.json").read_text())}
        except Exception:
            key = {}
        m = clip_measures(p)
        m.update(run=run, code=code, cls=cls, case=key.get(code))
        rows.append(m)
        print(f"{run} {code} {cls:4s} " + " ".join(f"{k}={m.get(k)}" for k in METRICS if k != "rel_e"), flush=True)
    # speed relative to the median of the clips of the same scene in the same run (all clips of the run, not only the labelled ones, are the better base but are not loaded here)
    by = {}
    for r in rows:
        by.setdefault((r["run"], r["case"]), []).append(r["e_all"])
    for r in rows:
        vs = [v for v in by[(r["run"], r["case"])] if v]
        r["rel_e"] = round(r["e_all"] / statistics.median(vs), 2) if r.get("e_all") and len(vs) >= 3 else None
    print("=" * 20, "MEAN PER CLASS")
    for k in METRICS:
        parts = []
        for cls in ("bad", "part", "ok"):
            v = [r[k] for r in rows if r["cls"] == cls and r.get(k) is not None]
            parts.append(f"{cls} {round(statistics.mean(v), 2) if v else '-'} (n {len(v)})")
        print(f"{k:24s} " + " | ".join(parts))
    print("=" * 20, "BEST SINGLE THRESHOLD bad vs ok (value >= threshold is a defect)")
    for k in METRICS:
        bad = [r[k] for r in rows if r["cls"] == "bad" and r.get(k) is not None]
        ok = [r[k] for r in rows if r["cls"] == "ok" and r.get(k) is not None]
        b = best_threshold(bad, ok)
        print(f"{k:24s} " + (f"threshold {b[0]} catches {round(b[1] * 100)}% of bad, flags {round(b[2] * 100)}% of ok" if b else "not enough data"))
    (OUT / "motion_calibration.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"(all numbers saved in {OUT}/motion_calibration.json)")
    return 0


# thresholds from the calibration above (IN-SAMPLE: optimistic). Extremes = almost no false alarms; drift / rel_e = broader.
RULES = {
    "judge":            lambda r: r["judge"] in ("review", "fail"),
    "motion_extremes":  lambda r: (r.get("accel_last_over_first") or 0) >= 11.8 or (r.get("drift_y_std_px_s") or 0) >= 4.5,
    "motion_broad":     lambda r: (r.get("rel_e") or 0) >= 1.1 or (r.get("drift_x_std_px_s") or 0) >= 3.6,
}


def judge_by_code(run) -> dict:
    """{code: verdict} from the saved answers of exp_judge (calibrate or run); {} when none was saved."""
    out = {}
    for name in (f"judge_calibration_{run}.json", f"judge_run_{run}.json"):
        try:
            for r in json.loads((OUT / name).read_text()):
                out.setdefault(r["code"], r["verdict"])
        except Exception:
            pass
    return out


def evaluate(rows, combos) -> dict:
    """{combo name: {'bad': n, 'caught': k, 'ok': n, 'flagged': k}} on the rows that have a judge verdict. A combo is a tuple of RULES names (OR)."""
    out = {}
    for combo in combos:
        d = {"bad": 0, "caught": 0, "ok": 0, "flagged": 0}
        for r in rows:
            if r["cls"] not in ("bad", "ok") or not r.get("judge"):
                continue
            hit = any(RULES[n](r) for n in combo)
            d[r["cls"]] += 1
            d["caught" if r["cls"] == "bad" else "flagged"] += 1 if hit else 0
        out["+".join(combo)] = d
    return out


def ensemble():
    rows = json.loads((OUT / "motion_calibration.json").read_text())
    j = {run: judge_by_code(run) for run in {r["run"] for r in rows}}
    for r in rows:
        r["judge"] = j[r["run"]].get(r["code"])
    have = [r for r in rows if r.get("judge")]
    print(f"{len(have)} labelled clips have a judge verdict (of {len(rows)} with motion numbers)")
    combos = [("judge",), ("motion_extremes",), ("motion_broad",), ("judge", "motion_extremes"), ("judge", "motion_broad"), ("judge", "motion_extremes", "motion_broad")]
    for name, d in evaluate(rows, combos).items():
        print(f"{name:42s} catches {d['caught']}/{d['bad']} bad, flags {d['flagged']}/{d['ok']} ok")
    missed = [f"{r['run'][-6:]}/{r['code']}" for r in have if r["cls"] == "bad" and not any(RULES[n](r) for n in ("judge", "motion_extremes", "motion_broad"))]
    print("bad clips none of the rules catches:", " ".join(missed) or "none")
    return 0


LINK_BASE = os.environ.get("PVS_LINK_BASE", "http://187.77.196.94:8000/test-scratch")
CLOSENESS = {"C3": 4, "C2": 3, "C1": 2, "C0": 1}      # how close a configuration is to what Luma's support recommended: the tie-break (2026-11-04: "usare tutte le raccomandazioni")
TIE_MARGIN = 0.08                                      # configurations within 8 percentage points of the best count as tied


def is_flagged(judge, measures: dict) -> bool:
    """The detector chosen on Michele's labels: the judge says review / fail, or the motion extremes (end acceleration, vertical drift)."""
    return judge in ("review", "fail") or RULES["motion_extremes"](measures)


def pick_winner(rates: dict, closeness: dict = CLOSENESS, margin: float = TIE_MARGIN):
    """(winner, explanation). Lowest flagged share; configurations within `margin` of it are tied and the one closest to Luma's recommendation wins."""
    best = min(rates.values())
    tied = [k for k, v in rates.items() if v <= best + margin + 1e-9]
    win = sorted(tied, key=lambda k: (-closeness.get(k, 0), rates[k]))[0]
    why = f"lowest share {min(rates, key=rates.get)} {round(best * 100)}%; tied within {round(margin * 100)} points: {', '.join(sorted(tied))}; closest to Luma's recommendation: {win}"
    return win, why


def rank_worst(rows) -> list:
    """Flagged clips, worst first: judge fail > review; motion extremes add to it."""
    def score(r):
        return {"fail": 3, "review": 2}.get(r.get("judge"), 0) + (1 if RULES["motion_extremes"](r) else 0)
    return sorted([r for r in rows if r["flag"]], key=lambda r: -score(r))


def report(run_id):
    import random
    import exp_judge as ej
    run_id = ej.resolve_run(run_id)
    key = {k["code"]: k for k in json.loads((OUT / f"key_{run_id}.json").read_text())}
    judged = {r["code"]: r["verdict"] for r in json.loads((OUT / f"judge_run_{run_id}.json").read_text())}
    rows = []
    for code, k in key.items():
        p = OUT / run_id / f"{code}.mp4"
        if not k.get("ok") or not p.is_file():
            continue
        m = clip_measures(p)
        r = dict(m, code=code, case=k["case"], variant=k["variant"], judge=judged.get(code))
        r["flag"] = is_flagged(r["judge"], r)
        rows.append(r)
    by = {}
    for r in rows:
        by.setdefault(r["variant"], []).append(r)
    rates = {v: sum(1 for r in rs if r["flag"]) / len(rs) for v, rs in by.items()}
    print("=" * 20, "REPORT", run_id, f"({len(rows)} clips; flagged = judge review/fail OR motion extremes; the detector has about 40% false alarms, so compare configurations, not absolute values)")
    for v in sorted(by):
        rs = by[v]
        print(f"{v}: n {len(rs)} | flagged {sum(1 for r in rs if r['flag'])} ({round(rates[v] * 100)}%) | judge fail {sum(1 for r in rs if r['judge'] == 'fail')} review {sum(1 for r in rs if r['judge'] == 'review')} | extremes {sum(1 for r in rs if RULES['motion_extremes'](r))} | mean speed e_all {round(statistics.mean([r['e_all'] for r in rs if r.get('e_all')]), 1)}")
    win, why = pick_winner(rates)
    print(f"WINNER by the stated rule: {win} ({why})")
    print("per scene (flagged / clips per configuration):")
    for c in sorted({r["case"] for r in rows}):
        print(f"  {c}: " + " | ".join(f"{v} {sum(1 for r in by[v] if r['case'] == c and r['flag'])}/{sum(1 for r in by[v] if r['case'] == c)}" for v in sorted(by)))
    mine = [r for r in rows if r["variant"] == win]
    watch = rank_worst(mine)[:3] + random.Random(7).sample([r for r in mine if not r["flag"]], min(3, sum(1 for r in mine if not r["flag"])))
    print("WATCH LIST (3 worst of the winner, then 3 random clips it passed):")
    for r in watch:
        job, scene = r["case"].split(":")
        print(f"  {r['code']} {r['case']} judge={r['judge']} flag={r['flag']} -> {LINK_BASE}/lum_{run_id}_{job}_{scene}.mp4")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "report":
        sys.exit(report(a[1] if len(a) > 1 else "last"))
    if a and a[0] == "ensemble":
        sys.exit(ensemble())
    sys.exit(main(a[a.index("--labels") + 1] if "--labels" in a else str(HERE / "motion_labels.json")))
