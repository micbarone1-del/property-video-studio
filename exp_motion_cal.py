"""exp_motion_cal.py - FREE objective measures of a clip (no Claude, no Luma) calibrated on Michele's blind labels (2026-11-04).
Why: the Claude judge missed a rotating clip (ley) and false-alarmed others; rotation, sideways drift and rushing are MOTION facts that can be measured locally.
For every labelled clip it takes the measures already in the repo (exp_clipeval.summarise: sideways / vertical drift of the picture centre, zig-zag, zoom rate,
acceleration; clip_speed_probe.speed: motion energy, and that energy relative to the median of the clips of the SAME scene), prints the mean per class (bad / part / ok)
and, for each measure, the best single threshold between bad and ok with how many bad clips it catches and how many ok clips it would flag. No decision is taken here.

  python3 exp_motion_cal.py [--labels motion_labels.json]      PVS_VOLUME_SCRATCH = where the runs are
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


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[a.index("--labels") + 1] if "--labels" in a else str(HERE / "motion_labels.json")))
