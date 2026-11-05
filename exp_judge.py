"""exp_judge.py - Claude-vision judge of PRODUCED clips, to pre-select what Michele has to watch (2026-11-04: "metti il QC Luma per analizzare output e io vedo versione pre selezionata").
EXPERIMENT TOOL, NOT PRODUCTION. Reuses the existing pieces (exp_clipeval.keyframes = 6 key frames; exp_director.ask_claude = the vision call), no new QC path.

One call per clip, 6 key frames in time order. The judge answers: things invented or animated (new structures, arches, people, flashes), people/vehicles moving, direction of the camera,
speed, and a verdict pass / review / fail. Codes only (the variant stays hidden) unless --reveal.

  python3 exp_judge.py calibrate RUN_ID [--labels judge_labels_1104_144423.json] [--cap 1.5]   judges the clips Michele already labelled and prints how often the judge agrees
  python3 exp_judge.py run RUN_ID [--cap 2.0] [--reveal]                                      judges every clip of a run; flagged ones first, with the video link of each scene
  python3 exp_judge.py summary RUN_ID|last                                                       FREE: reads the saved answers of `run` and counts verdicts and directions per VARIANT (reveals them)
  python3 exp_judge.py show RUN_ID|last CODE1,CODE2,...                                           FREE: variant, plan, measured speed, judge verdict and the real prompt of the given clips
  PVS_VOLUME_SCRATCH = where the runs are (production scratch, port 8000)
Cost: a few cents per clip (tokens are counted; the cap stops the run). Nothing is written into a job.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (HERE / "jobs" / "_test_scratch"))
OUT = SCRATCH / "facade"
IN_USD_PER_M, OUT_USD_PER_M = 3.0, 15.0        # Sonnet-class list price, only to estimate the spend of this tool

from clip_standard import JUDGE_PROMPT   # moved to production 2026-11-05 (one copy)


def spend_usd(usage: dict) -> float:
    return round((usage.get("in", 0) * IN_USD_PER_M + usage.get("out", 0) * OUT_USD_PER_M) / 1e6, 3)


def judge_clip(path, label, usage, ask=None, frames=None):
    """The judge's JSON for one clip (verdict normalised to pass / review / fail)."""
    if ask is None:
        import exp_director as dr
        ask = dr.ask_claude
    if frames is None:
        import exp_clipeval as ce
        frames = ce.keyframes(path, f"judge_{label}", 6)
    r = ask(JUDGE_PROMPT.format(n=len(frames)), frames, usage)
    v = str(r.get("verdict") or "").lower()
    r["verdict"] = v if v in ("pass", "review", "fail") else "review"
    return r


def load_labels(path) -> dict:
    d = json.loads(Path(path).read_text())
    return {code: cls for cls in ("bad", "part", "ok") for code in d.get(cls, [])}


def score(rows) -> dict:
    """rows: [(label class, judge verdict)] -> agreement numbers. flagged = review or fail."""
    out = {}
    for cls in ("bad", "part", "ok"):
        mine = [v for c, v in rows if c == cls]
        out[cls] = {"n": len(mine), "fail": mine.count("fail"), "review": mine.count("review"), "pass": mine.count("pass")}
    nb, no = out["bad"]["n"], out["ok"]["n"]
    out["bad_caught"] = (out["bad"]["fail"] + out["bad"]["review"]) / nb if nb else None
    out["bad_missed"] = out["bad"]["pass"]
    out["ok_false_alarm"] = (out["ok"]["fail"] + out["ok"]["review"]) / no if no else None
    out["ok_fail"] = out["ok"]["fail"]
    return out


def order_flagged(results) -> list:
    """fail first, then review, then pass (stable inside each)."""
    rank = {"fail": 0, "review": 1, "pass": 2}
    return sorted(results, key=lambda r: rank.get(r["verdict"], 1))


def resolve_run(run_id: str) -> str:
    """'last' = the run whose key file is the newest."""
    if run_id != "last":
        return run_id
    keys = sorted(OUT.glob("key_*.json"), key=lambda p: p.stat().st_mtime)
    if not keys:
        raise SystemExit(f"no key_*.json in {OUT}")
    return keys[-1].stem[len("key_"):]


def _save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def _clip_path(run_id, code):
    return OUT / run_id / f"{code}.mp4"


def calibrate(run_id, labels_file, cap):
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    labels = load_labels(labels_file)
    usage, rows, detail = {}, [], []
    for code, cls in labels.items():
        p = _clip_path(run_id, code)
        if not p.is_file():
            print(f"{code}: clip not found ({p})"); continue
        if spend_usd(usage) > cap:
            print(f"cap {cap} USD reached: stopped"); break
        try:
            r = judge_clip(p, code, usage)
        except Exception as e:
            print(f"{code}: judge error {str(e)[:120]}"); continue
        rows.append((cls, r["verdict"]))
        detail.append((code, cls, r))
        print(f"{code} Michele={cls:4s} judge={r['verdict']:6s} dir={r.get('direction')} speed={r.get('speed')} | {r.get('reason')}")
    _save(f"judge_calibration_{run_id}.json", [{"code": c, "michele": cls, **r} for c, cls, r in detail])
    s = score(rows)
    print("=" * 20, "CALIBRATION", run_id, f"spent about {spend_usd(usage)} USD")
    for cls in ("bad", "part", "ok"):
        print(f"Michele {cls}: {s[cls]}")
    print(f"bad clips caught (judge says review or fail): {s['bad_caught']} | bad clips MISSED (judge says pass): {s['bad_missed']}")
    print(f"ok clips flagged by mistake: {s['ok_false_alarm']} (of which fail: {s['ok_fail']})")
    print("bad clips the judge PASSED:", " ".join(c for c, cls, r in detail if cls == "bad" and r["verdict"] == "pass") or "none")
    print("ok clips the judge FAILED :", " ".join(c for c, cls, r in detail if cls == "ok" and r["verdict"] == "fail") or "none")
    print(f"(all answers saved in {OUT}/judge_calibration_{run_id}.json)")
    return 0


def run(run_id, cap, reveal):
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    run_id = resolve_run(run_id)
    key = json.loads((OUT / f"key_{run_id}.json").read_text())
    usage, results = {}, []
    for k in key:
        p = _clip_path(run_id, k["code"])
        if not k.get("ok") or not p.is_file():
            continue
        if spend_usd(usage) > cap:
            print(f"cap {cap} USD reached: stopped"); break
        try:
            r = judge_clip(p, k["code"], usage)
        except Exception as e:
            print(f"{k['code']}: judge error {str(e)[:120]}"); continue
        r.update(code=k["code"], case=k["case"], variant=k["variant"])
        results.append(r)
    _save(f"judge_run_{run_id}.json", results)
    print("=" * 20, "JUDGE", run_id, f"spent about {spend_usd(usage)} USD, {len(results)} clips")
    for r in order_flagged(results):
        print(f"{r['verdict']:6s} {r['code']} {r['case']} dir={r.get('direction')} speed={r.get('speed')} | {r.get('reason')}" + (f" | variant {r['variant']}" if reveal else ""))
    if reveal:
        by = {}
        for r in results:
            by.setdefault(r["variant"], []).append(r["verdict"])
        for v, vs in sorted(by.items()):
            print(f"variant {v}: pass {vs.count('pass')} review {vs.count('review')} fail {vs.count('fail')}")
    return 0


def summarise(results) -> dict:
    """{variant: {'n', 'pass', 'review', 'fail', 'directions': {...}, 'speeds': {...}}} from saved judge answers."""
    out = {}
    for r in results:
        v = out.setdefault(r.get("variant", "?"), {"n": 0, "pass": 0, "review": 0, "fail": 0, "directions": {}, "speeds": {}})
        v["n"] += 1
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
        for fld, key in (("directions", "direction"), ("speeds", "speed")):
            k = str(r.get(key))
            v[fld][k] = v[fld].get(k, 0) + 1
    return out


def summary(run_id):
    run_id = resolve_run(run_id)
    results = json.loads((OUT / f"judge_run_{run_id}.json").read_text())
    print("=" * 20, "SUMMARY BY VARIANT", run_id, f"({len(results)} clips; judge answers, no new cost)")
    for var, v in sorted(summarise(results).items()):
        print(f"variant {var}: n {v['n']} | pass {v['pass']} review {v['review']} fail {v['fail']} | directions {v['directions']} | speeds {v['speeds']}")
    cases = {}
    for r in results:
        cases.setdefault(r["case"], {}).setdefault(r["variant"], []).append(r["verdict"])
    print("per scene (verdicts of the 2 repetitions):")
    for c, d in cases.items():
        print(f"  {c}: " + " | ".join(f"{var} {' '.join(vs)}" for var, vs in sorted(d.items())))
    print("fails and reviews with variant:")
    for r in order_flagged(results):
        if r["verdict"] != "pass":
            print(f"  {r['verdict']:6s} {r['code']} {r['case']} variant {r['variant']} dir={r.get('direction')} | {r.get('reason')}")
    return 0


def show(run_id, codes):
    run_id = resolve_run(run_id)
    key = {k["code"]: k for k in json.loads((OUT / f"key_{run_id}.json").read_text())}
    try:
        judged = {r["code"]: r for r in json.loads((OUT / f"judge_run_{run_id}.json").read_text())}
    except Exception:
        judged = {}
    for c in codes:
        k = key.get(c)
        if not k:
            print(f"{c}: not in run {run_id}"); continue
        j = judged.get(c, {})
        sp = k.get("speed") or {}
        print(f"=== {c} {k['case']} variant {k['variant']} rep{k['rep']} | speed e_all {sp.get('e_all')} | judge {j.get('verdict')} dir={j.get('direction')}")
        print(f"    plan: {k.get('plan')}")
        print(f"    prompt: {str(k.get('prompt'))[:700]}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    if len(a) >= 2 and a[0] == "calibrate":
        sys.exit(calibrate(a[1], opt("--labels", str(HERE / "judge_labels_1104_144423.json")), float(opt("--cap", "1.5"))))
    if len(a) >= 3 and a[0] == "show":
        sys.exit(show(a[1], [c for c in a[2].split(",") if c]))
    if len(a) >= 2 and a[0] == "summary":
        sys.exit(summary(a[1]))
    if len(a) >= 2 and a[0] == "run":
        sys.exit(run(a[1], float(opt("--cap", "2.0")), "--reveal" in a))
    print(__doc__)
