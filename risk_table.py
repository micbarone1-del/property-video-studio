"""risk_table.py - FREE (no Luma, no Claude): which SCENES are risky, from every clip already produced (all runs of 2026-11-04).
Why (Michele, 2026-11-04): the discards are mostly tied to the scene, not to the prompt; prevention first, so the selector needs a list of risky scenes/features.
Per scene: clips made, share flagged (Michele's label when the clip was labelled, otherwise the detector: judge review/fail OR motion extremes), in how many
different configurations it was flagged, plus category and plan type (static / forward). Then the same share per category and per plan type.
No decision is taken here; it only shows what could predict risk.

  python3 risk_table.py        PVS_VOLUME_SCRATCH = where the runs are, PVS_JOBS_DIR = where the jobs are
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (HERE / "jobs" / "_test_scratch"))
OUT = SCRATCH / "facade"
JOBS = Path(os.environ.get("PVS_JOBS_DIR") or (HERE / "jobs"))


def plan_type(plan) -> str:
    p = str(plan or "").lower()
    return "static" if p.startswith("static") else ("forward" if p.startswith("forward") else "other")


def flag_of(label, detector_flag: bool) -> bool:
    """Michele's label wins: bad = flagged, ok = not flagged; 'part' or no label = the detector."""
    if label == "bad":
        return True
    if label == "ok":
        return False
    return bool(detector_flag)


def aggregate(rows) -> dict:
    """rows: dicts with case, variant, flag, cat, ptype. -> {case: {n, flagged, variants, cat, ptype}}"""
    out = {}
    for r in rows:
        s = out.setdefault(r["case"], {"n": 0, "flagged": 0, "variants": set(), "cat": r.get("cat"), "ptype": r.get("ptype")})
        s["n"] += 1
        if r["flag"]:
            s["flagged"] += 1
            s["variants"].add(r["variant"])
    return out


def group_rate(rows, field) -> dict:
    g = {}
    for r in rows:
        a = g.setdefault(r.get(field) or "?", [0, 0])
        a[0] += 1
        a[1] += 1 if r["flag"] else 0
    return {k: (v[0], v[1], round(v[1] / v[0], 2)) for k, v in g.items()}


def collect():
    import exp_motion_cal as mc
    labels = {(r, c): k for r, c, k in mc.load_labels(HERE / "motion_labels.json")}
    rows, cats = [], {}
    for kf in sorted(OUT.glob("key_*.json")):
        run = kf.stem[4:]
        judged = mc.judge_by_code(run)
        try:
            key = json.loads(kf.read_text())
        except Exception:
            continue
        for k in key:
            p = OUT / run / f"{k.get('code')}.mp4"
            if not (k.get("ok") and p.is_file() and k.get("case")):
                continue
            m = mc.clip_measures(p)
            job, _, sc = str(k["case"]).partition(":")
            if job not in cats:
                try:
                    cats[job] = json.loads((JOBS / job / "job_meta.json").read_text()).get("scenes_config") or []
                except Exception:
                    cats[job] = []
            try:
                sc_cat = str(cats[job][int(sc)].get("category") or cats[job][int(sc)].get("room") or "?").lower()
            except Exception:
                sc_cat = "?"
            det = mc.is_flagged(judged.get(k["code"]), m)
            rows.append({"run": run, "code": k["code"], "case": k["case"], "variant": k.get("variant"), "cat": sc_cat,
                         "ptype": plan_type(k.get("plan")), "flag": flag_of(labels.get((run, k["code"])), det)})
    return rows


def main():
    rows = collect()
    sc = aggregate(rows)
    print(f"RISK TABLE: {len(rows)} clips, {len(sc)} scenes (flag = Michele's label if any, else judge/motion detector; configurations differ, so rates are indicative)")
    print("scene | category | plan | clips | flagged | configurations with a flag")
    for case, s in sorted(sc.items(), key=lambda kv: (-kv[1]["flagged"] / kv[1]["n"], kv[0])):
        print(f"  {case} | {s['cat']} | {s['ptype']} | {s['n']} | {s['flagged']} ({round(100 * s['flagged'] / s['n'])}%) | {len(s['variants'])}")
    for field in ("cat", "ptype"):
        print(f"by {field}: " + " | ".join(f"{k} {v[1]}/{v[0]} ({round(v[2] * 100)}%)" for k, v in sorted(group_rate(rows, field).items(), key=lambda kv: -kv[1][2])))


if __name__ == "__main__":
    sys.exit(main())
