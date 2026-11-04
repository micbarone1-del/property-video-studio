"""exp_judge.py - Claude-vision judge of PRODUCED clips, to pre-select what Michele has to watch (2026-11-04: "metti il QC Luma per analizzare output e io vedo versione pre selezionata").
EXPERIMENT TOOL, NOT PRODUCTION. Reuses the existing pieces (exp_clipeval.keyframes = 6 key frames; exp_director.ask_claude = the vision call), no new QC path.

One call per clip, 6 key frames in time order. The judge answers: things invented or animated (new structures, arches, people, flashes), people/vehicles moving, direction of the camera,
speed, and a verdict pass / review / fail. Codes only (the variant stays hidden) unless --reveal.

  python3 exp_judge.py calibrate RUN_ID [--labels judge_labels_1104_144423.json] [--cap 1.5]   judges the clips Michele already labelled and prints how often the judge agrees
  python3 exp_judge.py run RUN_ID [--cap 2.0] [--reveal]                                      judges every clip of a run; flagged ones first, with the video link of each scene
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

JUDGE_PROMPT = """These {n} frames are in time order from a 5 second real-estate video made from ONE still photo (frame 1 is the photo). The camera may glide slowly forward or stay still; everything else in the scene must stay exactly as in frame 1: nothing may appear, disappear, move, animate, flash or deform.
Judge the clip like a strict quality inspector for a real-estate agency:
- invented: anything NOT in frame 1 that shows up later (new buildings or parts of buildings, arches, garages, balconies, doors, windows, staircases, signs, people, animals, black or white flashes). Do not count things that merely come into view at the edges as the camera moves.
- animated: people, vehicles, curtains, flags, water or leaves that MOVE or change.
- direction: where the camera travels, one of "toward_main_subject" (the building / room feature that dominates frame 1 gets closer), "along_street_or_path", "sideways", "backward", "downward", "upward", "static".
- speed: "static", "slow", "fast", "very_fast" (fast = the picture changes a lot within one second).
- verdict: "fail" if something is invented, or people/vehicles animate, or the camera goes away from the main subject, backward or downward, or it is very fast; "review" if the camera drifts sideways/along a path, is fast, or you are unsure; otherwise "pass".
Answer with JSON only: {{"invented": [{{"frames": "3-5", "what": "short"}}], "animated": [{{"frames": "2-6", "what": "short"}}], "direction": "...", "speed": "...", "verdict": "pass", "reason": "one short sentence"}}"""


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
    s = score(rows)
    print("=" * 20, "CALIBRATION", run_id, f"spent about {spend_usd(usage)} USD")
    for cls in ("bad", "part", "ok"):
        print(f"Michele {cls}: {s[cls]}")
    print(f"bad clips caught (judge says review or fail): {s['bad_caught']} | bad clips MISSED (judge says pass): {s['bad_missed']}")
    print(f"ok clips flagged by mistake: {s['ok_false_alarm']} (of which fail: {s['ok_fail']})")
    return 0


def run(run_id, cap, reveal):
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
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


if __name__ == "__main__":
    a = sys.argv[1:]

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    if len(a) >= 2 and a[0] == "calibrate":
        sys.exit(calibrate(a[1], opt("--labels", str(HERE / "judge_labels_1104_144423.json")), float(opt("--cap", "1.5"))))
    if len(a) >= 2 and a[0] == "run":
        sys.exit(run(a[1], float(opt("--cap", "2.0")), "--reveal" in a))
    print(__doc__)
