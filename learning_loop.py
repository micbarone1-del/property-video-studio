"""learning_loop.py - 2026-11-24: the learning loop for video hallucinations (and, with the same machinery, for narration retries).

PHASE 1 = OFFLINE AND READ-ONLY. Nothing here is imported by api_server or the pipeline; it never writes into jobs/, never changes a prompt,
a selection, a rework or a job state. It JOINS what already exists (no second registry):
  scene_risk_events.jsonl      (scene_risk.py: job, scene, cat, move, tier, stage first/rework, verdict)
  standard_shadow_events.jsonl (clip_standard.py: new_max, judge, revealed_no, extended_scene, plan ...)
  jobs/<id>/job_meta.json      (scene fields: anchor, side, depth, reflective surface; narration mode and attempts)
and answers ONE question: which inputs (photo class, movement, anchor kind ...) are followed by bad outcomes MORE often than the baseline,
and does that still hold on jobs that were NOT used to find the rule.

Rules of the method (written BEFORE looking at data, see LEARNING_LOOP.md):
  * the split is by JOB (hash of the job id), never by clip: scenes of one listing are correlated, a clip split would leak;
  * a rule is FOUND on the train part and only KEPT if it HOLDS on the hold-out part (criteria in HOLDOUT_*);
  * with too little data the answer is "not enough data", never a rule;
  * several labels are reported SEPARATELY (QC non-pass, persistent after rework, detector candidate): they are never merged into one number.

  python3 learning_loop.py [jobs_dir]     prints the report and writes learning_report.json next to the event files
"""
import hashlib
import time
import json
import math
import os
import re
import sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOLDOUT_PCT = 30            # share of JOBS kept aside
MIN_TRAIN_N = 10            # a rule needs this many train scenes to be proposed
MIN_HOLD_N = 10             # ... and this many hold-out scenes to be judged
MIN_LIFT = 1.5              # train: rule rate / baseline rate
Z_TRAIN = 1.28              # Wilson lower bound (about 80% one-sided) must stay above the train baseline
HOLDOUT_MIN_RATIO = 1.3     # hold-out: rule rate >= 1.3 x hold-out baseline ...
HOLDOUT_MIN_GAP = 0.10      # ... and at least 10 points above it
FEATURES = ("cat", "move", "tier", "plan_kind", "anchor_kind", "depth")   # reflective_surface is NOT in the real job_meta (checked on the server 2026-11-25): removed
NARRATION_FEATURES = ("desc_len", "n_scenes", "source", "has_price")
from scene_kinds import GENERIC_ANCHORS, anchor_kind, plan_kind, scene_features   # one shared implementation (2026-11-25)
BAD_VERDICTS = ("flag", "reject", "failed")


# ── small helpers ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def wilson(k, n, z=1.28):
    """(low, high) Wilson interval of a rate k/n; (None, None) for n == 0."""
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - m) / d, 3), round((c + m) / d, 3))


def split_of(job_id, holdout_pct=HOLDOUT_PCT):
    """Deterministic: the same job is always train or hold-out (hash of the id)."""
    h = int(hashlib.md5(str(job_id).encode("utf-8")).hexdigest()[:8], 16) % 100
    return "holdout" if h < holdout_pct else "train"


def load_jsonl(path):
    out = []
    try:
        for ln in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ln)
                if isinstance(e, dict):
                    out.append(e)
            except Exception:
                pass
    except Exception:
        pass
    return out


def load_jobs(jobs_dir):
    """Read-only: {job_id: job_meta}. Folders starting with '_' (scratch) are skipped. Never raises."""
    out = {}
    try:
        for d in sorted(Path(jobs_dir).iterdir()):
            if d.name.startswith("_") or not d.is_dir():
                continue
            try:
                out[d.name] = json.loads((d / "job_meta.json").read_text(encoding="utf-8"))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _scene_index(scene_id):
    m = re.search(r"(\d+)\s*$", str(scene_id or ""))
    return int(m.group(1)) if m else None


def scene_of_job(job, scene_id):
    """The scene dict (scenes_config entry) a clip belongs to: by explicit id, else by the number in scene_NNN."""
    sc = (job or {}).get("scenes_config") or (job or {}).get("scenes") or []
    for s in sc:
        if isinstance(s, dict) and str(s.get("scene_id") or s.get("id") or "") == str(scene_id):
            return s
    i = _scene_index(scene_id)
    if i is not None and 0 <= i < len(sc) and isinstance(sc[i], dict):
        return sc[i]
    return {}


# ── dataset ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def build_scene_rows(risk_events, shadow_events, jobs):
    """One row per (job, scene) that has a FIRST-generation QC verdict. Labels (kept separate, None = not measurable):
       l_qc          first QC verdict is flag/reject/failed
       l_persistent  a rework QC exists and it is still flag/reject (None when the scene was never reworked)
       l_detector    candidate detector: (revealed or extended_scene) and new_max > 0.05 (None when the shadow event is missing)"""
    shadow = {}
    for e in shadow_events:
        shadow.setdefault((str(e.get("job")), str(e.get("scene"))), e)       # the FIRST shadow event of the scene
    firsts, reworks = {}, {}
    for e in risk_events:
        key = (str(e.get("job")), str(e.get("scene")))
        if e.get("stage") == "rework":
            reworks.setdefault(key, []).append(e)
        elif e.get("stage") in (None, "first"):
            firsts.setdefault(key, e)
    rows = []
    for (job, scene), e in firsts.items():
        sc = scene_of_job(jobs.get(job), scene)
        f = scene_features(sc, e.get("move"), e.get("cat"), e.get("tier"))
        sh = shadow.get((job, scene))
        det = None
        if sh is not None and sh.get("new_max") is not None and ("revealed_no" in sh or "extended_scene" in sh):
            det = bool(((sh.get("revealed_no") or 0) > 0 or sh.get("extended_scene") is True) and (sh.get("new_max") or 0) > 0.05)
        rw = reworks.get((job, scene))
        rows.append({"job": job, "scene": scene, "split": split_of(job), **f,
                     "l_qc": e.get("verdict") in BAD_VERDICTS,
                     "l_persistent": (None if not rw else any(r.get("verdict") in BAD_VERDICTS for r in rw)),
                     "l_detector": det})
    return rows


def _desc_len_bucket(job):
    n = len(str((job or {}).get("source_description") or ""))
    return "none" if n == 0 else ("short" if n < 400 else ("medium" if n < 1200 else "long"))


def build_narration_rows(jobs):
    """One row per job that has a narration mode. Outcome: l_fallback = the narration did NOT come out anchored (per_scene or single text);
       l_script_fallback = the job field narration_script_fallback is set (value format NOT verified: read as true/false); l_retries = 3 or more attempts (script_attempts is NOT in the real job_meta: label stays None). The REASON of each rejection is not stored in job_meta today: reported as missing data, not guessed."""
    rows = []
    for jid, j in jobs.items():
        n = j.get("narration") if isinstance(j.get("narration"), dict) else {}
        mode = j.get("narration_mode") or n.get("narration_mode")
        if not mode:
            continue
        att = j.get("script_attempts", n.get("script_attempts"))
        rows.append({"job": jid, "split": split_of(jid), "desc_len": _desc_len_bucket(j), "n_scenes": str(len(j.get("scenes_config") or [])),
                     "source": str(j.get("source") or "?"), "has_price": str(bool(j.get("source_price") or j.get("price"))),
                     "l_fallback": mode != "anchored", "l_script_fallback": bool(j.get("narration_script_fallback") or n.get("narration_script_fallback")),
                     "l_retries": (None if att is None else int(att) >= 3),
                     "has_reasons": bool(j.get("narration_rejections") or n.get("narration_rejections"))})
    return rows


# ── rule search and hold-out check ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _rate(rows, label):
    xs = [r[label] for r in rows if r.get(label) is not None]
    return (sum(1 for x in xs if x), len(xs))


def _matches(row, cond):
    return all(row.get(k) == v for k, v in cond)


def candidate_conditions(rows, features):
    seen = set()
    for r in rows:
        items = [(f, r[f]) for f in features if r.get(f) not in (None, "?")]
        for c in items:
            seen.add((c,))
        for a, b in combinations(items, 2):
            seen.add((a, b))
    return sorted(seen)


def find_rules(train_rows, label, features):
    """Rules found on the TRAIN part only: n >= MIN_TRAIN_N, lift >= MIN_LIFT and a Wilson lower bound above the train baseline."""
    k0, n0 = _rate(train_rows, label)
    if n0 < 2 * MIN_TRAIN_N or not k0:
        return {"baseline": (k0 / n0 if n0 else None), "n": n0, "rules": [], "note": "not enough data" if n0 < 2 * MIN_TRAIN_N else "no positive case"}
    base = k0 / n0
    out = []
    for cond in candidate_conditions(train_rows, features):
        sub = [r for r in train_rows if _matches(r, cond)]
        k, n = _rate(sub, label)
        if n < MIN_TRAIN_N:
            continue
        rate = k / n
        lo, _ = wilson(k, n, Z_TRAIN)
        if rate >= MIN_LIFT * base and lo is not None and lo > base:
            out.append({"cond": [list(c) for c in cond], "n": n, "bad": k, "rate": round(rate, 3), "lift": round(rate / base, 2), "wilson_low": lo})
    out.sort(key=lambda r: (-r["wilson_low"], -r["n"]))
    return {"baseline": round(base, 3), "n": n0, "rules": out, "note": ""}


def check_holdout(rules, hold_rows, label):
    """Each found rule is looked at on jobs it never saw. holds = enough scenes, rate clearly above the hold-out baseline."""
    k0, n0 = _rate(hold_rows, label)
    base = (k0 / n0) if n0 else None
    res = []
    for r in rules:
        cond = tuple(tuple(c) for c in r["cond"])
        sub = [x for x in hold_rows if _matches(x, cond)]
        k, n = _rate(sub, label)
        rate = (k / n) if n else None
        holds = bool(n >= MIN_HOLD_N and base is not None and rate is not None and rate >= HOLDOUT_MIN_RATIO * base and rate - base >= HOLDOUT_MIN_GAP)
        res.append({**r, "hold_n": n, "hold_bad": k, "hold_rate": (round(rate, 3) if rate is not None else None),
                    "hold_baseline": (round(base, 3) if base is not None else None), "hold_wilson": list(wilson(k, n, 1.0)),
                    "status": "HOLDS" if holds else ("not enough hold-out data" if n < MIN_HOLD_N else "DOES NOT HOLD")})
    return {"hold_baseline": (round(base, 3) if base is not None else None), "hold_n": n0, "rules": res}


def analyse(rows, labels, features):
    train = [r for r in rows if r["split"] == "train"]
    hold = [r for r in rows if r["split"] == "holdout"]
    out = {"rows": len(rows), "train_rows": len(train), "holdout_rows": len(hold), "labels": {}}
    for lab in labels:
        found = find_rules(train, lab, features)
        checked = check_holdout(found["rules"], hold, lab)
        out["labels"][lab] = {"train_baseline": found["baseline"], "train_n": found["n"], "note": found["note"], "found": len(found["rules"]),
                              "holding": [r for r in checked["rules"] if r["status"] == "HOLDS"], "all": checked["rules"],
                              "hold_baseline": checked["hold_baseline"], "hold_n": checked["hold_n"]}
    return out


def report(risk_events, shadow_events, jobs, extra_rows=None):
    rows = build_scene_rows(risk_events, shadow_events, jobs) + list(extra_rows or [])   # extra_rows: the seed (phase 1b), kept apart by src="seed"
    nrows = build_narration_rows(jobs)
    return {"video": analyse(rows, ("l_qc", "l_persistent", "l_detector"), FEATURES),
            "narration": {**analyse(nrows, ("l_fallback", "l_script_fallback", "l_retries"), NARRATION_FEATURES),
                          "jobs_with_rejection_reasons": sum(1 for r in nrows if r["has_reasons"]),
                          "missing_data": "the reason of each narration rejection is not stored in job_meta (phase 2 recording)" if nrows and not any(r["has_reasons"] for r in nrows) else ""},
            "criteria": {"holdout_pct": HOLDOUT_PCT, "min_train_n": MIN_TRAIN_N, "min_hold_n": MIN_HOLD_N, "min_lift": MIN_LIFT,
                         "holdout_min_ratio": HOLDOUT_MIN_RATIO, "holdout_min_gap": HOLDOUT_MIN_GAP}}


def _print(rep):
    for part in ("video", "narration"):
        p = rep[part]
        print(f"== {part.upper()}: {p['rows']} rows (train {p['train_rows']}, hold-out {p['holdout_rows']})")
        for lab, d in p["labels"].items():
            print(f"  {lab}: train baseline {d['train_baseline']} (n {d['train_n']}) | rules found {d['found']} | HOLD on hold-out: {len(d['holding'])}"
                  f"{' | ' + d['note'] if d['note'] else ''}")
            for r in d["holding"][:5]:
                print(f"     HOLDS {r['cond']}: train {r['bad']}/{r['n']} ({r['rate']}), hold-out {r['hold_bad']}/{r['hold_n']} ({r['hold_rate']} vs {r['hold_baseline']})")
            for r in [x for x in d["all"] if x["status"] != "HOLDS"][:3]:
                print(f"     {r['status']} {r['cond']}: train {r['bad']}/{r['n']} ({r['rate']}), hold-out {r['hold_bad']}/{r['hold_n']} ({r['hold_rate']})")
    if rep["narration"].get("missing_data"):
        print("  NOTE narration:", rep["narration"]["missing_data"])


def export_rules(rep):
    """Only the rules that HOLD on the hold-out, for learning_apply.py (the only bridge to production: a JSON file, no import)."""
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "rules": []}
    for lab, d in rep.get("video", {}).get("labels", {}).items():
        for r in d.get("holding", []):
            cond = [list(c) for c in r["cond"]]
            out["rules"].append({"id": lab + ":" + "&".join(f"{k}={v}" for k, v in cond), "label": lab, "cond": cond, "rate": r.get("rate"),
                                 "hold_rate": r.get("hold_rate"), "hold_baseline": r.get("hold_baseline"), "n": r.get("n"), "hold_n": r.get("hold_n")})
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    data = Path(os.getenv("PVS_DATA_DIR") or HERE)
    pos = [a for a in argv if not a.startswith("--")]
    jobs_dir = Path(pos[0]) if pos else Path(os.getenv("PVS_JOBS_DIR") or (HERE / "jobs"))
    risk = load_jsonl(os.getenv("PVS_SCENE_RISK_FILE") or data / "scene_risk_events.jsonl")
    shadow = load_jsonl(os.getenv("PVS_STANDARD_SHADOW_FILE") or data / "standard_shadow_events.jsonl")
    jobs = load_jobs(jobs_dir)
    seed = "--seed" in argv
    extra = None
    if seed:
        import learning_seed
        prod = {(r["job"], r["scene"]) for r in build_scene_rows(risk, shadow, jobs)}
        scratch = Path(os.getenv("PVS_VOLUME_SCRATCH") or (jobs_dir / "_test_scratch"))
        extra, st = learning_seed.seed_rows(scratch, jobs, HERE / "motion_labels.json", skip=prod)
        print("SEED (phase 1b, exploratory):", st)
    rep = report(risk, shadow, jobs, extra)
    _print(rep)
    if seed:
        print("SEED run: nothing is written (no learning_report.json, no learning_rules.json); rules found here are only a hint to check in shadow on production data.")
        return 0
    try:
        (data / "learning_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print("written:", data / "learning_report.json")
        (data / "learning_rules.json").write_text(json.dumps(export_rules(rep), ensure_ascii=False, indent=1), encoding="utf-8")
        print("written:", data / "learning_rules.json")
    except Exception as e:
        print("report not written:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
