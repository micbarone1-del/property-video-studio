"""learning_replay.py - backtest of the learning loop on the past (2026-11-25). OFFLINE, READ-ONLY, not imported by production.
Walk-forward: scenes in time order. At each checkpoint the loop learns ONLY from the scenes before it (same method as learning_loop.py: job split,
rules found on train, kept only if they hold on the hold-out part of the past), then each rule is judged on the NEXT window it has never seen.
Also a NULL run: the labels are shuffled (fixed seed), so any rule found there is a false rule. This measures how often the method fools itself.
Run: python3 learning_replay.py jobs        Writes nothing (prints only)."""
import os
import random
import sys
from pathlib import Path

import learning_loop as ll

START, STEP = 40, 20
FUT_RATIO, FUT_GAP = ll.HOLDOUT_MIN_RATIO, ll.HOLDOUT_MIN_GAP


def _future_eval(rule, window, label):
    cond = tuple(tuple(c) for c in rule["cond"])
    sub = [x for x in window if ll._matches(x, cond)]
    k, n = ll._rate(sub, label)
    kb, nb = ll._rate(window, label)
    base = (kb / nb) if nb else None
    rate = (k / n) if n else None
    ok = bool(n >= 5 and base is not None and rate is not None and rate >= FUT_RATIO * base and rate - base >= FUT_GAP)
    return {"n": n, "bad": k, "rate": rate, "base": base, "confirmed": ok, "enough": n >= 5}


def replay(rows, label, features, start=START, step=STEP):
    """rows already in time order. Returns one record per checkpoint."""
    out = []
    k = start
    while k < len(rows):
        past, window = rows[:k], rows[k:k + step]
        train = [r for r in past if r["split"] == "train"]
        hold = [r for r in past if r["split"] == "holdout"]
        found = ll.find_rules(train, label, features)
        checked = ll.check_holdout(found["rules"], hold, label)
        holding = [r for r in checked["rules"] if r["status"] == "HOLDS"]
        rec = {"past": len(past), "window": len(window), "found": len(found["rules"]), "holding": len(holding), "found_eval": [], "holding_eval": []}
        for r in found["rules"]:
            rec["found_eval"].append({"cond": r["cond"], **_future_eval(r, window, label)})
        for r in holding:
            rec["holding_eval"].append({"cond": r["cond"], **_future_eval(r, window, label)})
        out.append(rec)
        k += step
    return out


def summarise(recs):
    """Counts DISTINCT rules (the same rule held at several checkpoints is one rule) and, for each, whether it was confirmed on the future at least once."""
    def agg(key):
        by = {}
        for r in recs:
            for e in r[key]:
                c = tuple(tuple(x) for x in e["cond"])
                d = by.setdefault(c, {"judged": 0, "confirmed": 0})
                if e["enough"]:
                    d["judged"] += 1
                    d["confirmed"] += 1 if e["confirmed"] else 0
        judged = [d for d in by.values() if d["judged"]]
        return {"rules": len(by), "judged_on_future": len(judged), "confirmed": sum(1 for d in judged if d["confirmed"]),
                "windows_judged": sum(d["judged"] for d in by.values()), "windows_confirmed": sum(d["confirmed"] for d in by.values())}
    return {"checkpoints": len(recs), "found": agg("found_eval"), "holding": agg("holding_eval")}


def details(recs, key="found_eval"):
    """Per distinct rule: every future window it was judged on (n scenes matching, how many bad, rate vs the window baseline, confirmed or not)."""
    by = {}
    for i, r in enumerate(recs):
        for e in r[key]:
            c = " & ".join(f"{a}={b}" for a, b in e["cond"])
            by.setdefault(c, []).append((i + 1, e))
    return by


def print_details(recs, key="found_eval"):
    for c, wins in sorted(details(recs, key).items()):
        line = " | ".join(f"cp{i}: {e['bad']}/{e['n']}" + (f" ({e['rate']:.2f} vs {e['base']:.2f})" if e["enough"] and e["base"] is not None else " (too few)") + (" CONFIRMED" if e["confirmed"] else "") for i, e in wins)
        print(f"    {c}: {line}")


def shuffled(rows, label, seed=7):
    rnd = random.Random(seed)
    vals = [r[label] for r in rows]
    rnd.shuffle(vals)
    return [{**r, label: v} for r, v in zip(rows, vals)]


def ordered_rows(risk_events, shadow_events, jobs):
    rows = ll.build_scene_rows(risk_events, shadow_events, jobs)
    ts = {}
    for e in risk_events:
        if e.get("stage") in (None, "first"):
            ts.setdefault((str(e.get("job")), str(e.get("scene"))), str(e.get("ts") or ""))
    return sorted(rows, key=lambda r: ts.get((r["job"], r["scene"]), ""))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    data = Path(os.getenv("PVS_DATA_DIR") or ll.HERE)
    jobs_dir = Path(argv[0]) if argv else Path(os.getenv("PVS_JOBS_DIR") or (ll.HERE / "jobs"))
    rows = ordered_rows(ll.load_jsonl(os.getenv("PVS_SCENE_RISK_FILE") or data / "scene_risk_events.jsonl"),
                        ll.load_jsonl(os.getenv("PVS_STANDARD_SHADOW_FILE") or data / "standard_shadow_events.jsonl"), ll.load_jobs(jobs_dir))
    print(f"scene rows in time order: {len(rows)} | checkpoints start {START}, step {STEP}")
    for lab in ("l_qc", "l_persistent"):
        usable = [r for r in rows if r.get(lab) is not None]
        if len(usable) <= START:
            print(f"{lab}: {len(usable)} labelled scenes, fewer than {START + STEP}: backtest not possible (not enough data)")
            continue
        real_recs = replay(usable, lab, ll.FEATURES)
        real = summarise(real_recs)
        null = summarise(replay(shuffled(usable, lab), lab, ll.FEATURES))
        print(f"== {lab} ({len(usable)} scenes)")
        for name, s in (("REAL data", real), ("NULL (labels shuffled)", null)):
            print(f"  {name}: checkpoints {s['checkpoints']} | rules found {s['found']['rules']} (judged {s['found']['judged_on_future']}, confirmed on the future {s['found']['confirmed']}; windows {s['found']['windows_confirmed']}/{s['found']['windows_judged']})"
                  f" | rules that HELD on the past hold-out {s['holding']['rules']} (judged {s['holding']['judged_on_future']}, confirmed {s['holding']['confirmed']}; windows {s['holding']['windows_confirmed']}/{s['holding']['windows_judged']})")
        if "-v" in argv:
            print("  rules found on the past, judged window by window on the future (REAL data):")
            print_details(real_recs)
    print("Rules are DISTINCT (the same rule at several checkpoints counts once). A chance pattern in the whole data stays visible before and after, so NULL can still show a few.")
    print("Reading: if NULL finds as many 'confirmed' rules as REAL, the data hold no signal the method can use. Rules are judged on windows of "
          f"{STEP} scenes, rule needs >=5 scenes there: small numbers, indicative only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
