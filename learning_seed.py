"""learning_seed.py - phase 1b of the learning loop (2026-11-25): Michele's blind labels of the test clips as EXTRA, clearly separate rows. OFFLINE, READ-ONLY.
Sources (all existing, nothing new is written): motion_labels.json (run -> bad / part / ok per blind code), jobs/_test_scratch/facade/key_<run>.json
(code -> case "JOB:SCENE_INDEX", plan, ok), jobs/<job>/job_meta.json (scene fields). Same locations as risk_table.py / exp_motion_cal.py.
Rules, written before looking at the data:
  - one row per SCENE (job, scene), never per clip: a scene seen in many prompt variants is one row (the loop's own LEARNING_LOOP.md risk);
  - only 'bad' and 'ok' clips count ('part' = passable, left out); a scene needs >= 2 labelled clips; l_qc = share of 'bad' >= 0.5;
  - 'move' and 'tier' are unknown here ('?', so no rule can use them): the test clips used different movements than the scene's own plan;
    plan_kind comes from the plan of the clips (majority); cat, anchor_kind, depth come from job_meta;
  - a scene that is already a production row is skipped (no double counting); rows carry src="seed" and the job's real id, so the job split stays consistent.
The seed is for LOOKING (do the same patterns appear with cleaner labels?). learning_loop.py does not export rules from a run that uses it."""
import json
import os
from pathlib import Path

import scene_kinds
from learning_loop import split_of

MIN_LABELLED = 2
BAD_SHARE = 0.5


def _plan_kind(plan):
    p = str(plan or "").lower()
    return "static" if p.startswith("static") else ("forward" if p.startswith("forward") else "?")


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def seed_rows(scratch, jobs, labels_file, skip=()):
    """scratch = the folder that holds 'facade/'; jobs = {job_id: job_meta} as learning_loop.load_jobs returns; skip = set of (job, scene_id) already production rows."""
    labels = _load(labels_file, {})
    per = {}      # (job, idx) -> {"bad": n, "ok": n, "plans": []}
    stats = {"runs": 0, "clips_labelled": 0, "clips_unmapped": 0, "part_left_out": 0}
    for run, d in labels.items():
        if not isinstance(d, dict) or not {"bad", "ok"} <= set(d):
            continue
        key = {k.get("code"): k for k in _load(Path(scratch) / "facade" / f"key_{run}.json", []) if isinstance(k, dict)}
        stats["runs"] += 1
        for cls in ("bad", "ok", "part"):
            for code in d.get(cls) or []:
                k = key.get(code)
                if not k or not k.get("case"):
                    stats["clips_unmapped"] += 1
                    continue
                if cls == "part":
                    stats["part_left_out"] += 1
                    continue
                job, _, idx = str(k["case"]).partition(":")
                try:
                    idx = int(idx)
                except ValueError:
                    stats["clips_unmapped"] += 1
                    continue
                e = per.setdefault((job, idx), {"bad": 0, "ok": 0, "plans": []})
                e[cls] += 1
                e["plans"].append(_plan_kind(k.get("plan")))
                stats["clips_labelled"] += 1
    rows, no_job, skipped = [], 0, 0
    for (job, idx), e in sorted(per.items()):
        if e["bad"] + e["ok"] < MIN_LABELLED:
            continue
        meta = jobs.get(job)
        sc_list = (meta or {}).get("scenes_config") or []
        if not (0 <= idx < len(sc_list)) or not isinstance(sc_list[idx], dict):
            no_job += 1
            continue
        sc = sc_list[idx]
        sid = str(sc.get("scene_id") or sc.get("id") or "")
        if (job, sid) in skip or (job, f"scene_{idx:03d}") in skip:
            skipped += 1
            continue
        plans = [p for p in e["plans"] if p != "?"]
        pk = max(set(plans), key=plans.count) if plans else "?"
        f = scene_kinds.scene_features(sc, "?", sc.get("category") or sc.get("space_type"), None)
        f["tier"] = "?"
        f["plan_kind"] = pk
        rows.append({"job": job, "scene": sid or f"seed_{idx}", "split": split_of(job), **f, "src": "seed",
                     "l_qc": (e["bad"] / (e["bad"] + e["ok"])) >= BAD_SHARE, "l_persistent": None, "l_detector": None,
                     "n_clips": e["bad"] + e["ok"]})
    stats.update(scenes=len(rows), scenes_without_job_meta=no_job, scenes_already_in_production=skipped)
    return rows, stats
