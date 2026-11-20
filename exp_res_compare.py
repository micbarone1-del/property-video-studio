"""exp_res_compare.py - is the 360p draft a filter for the 1080p clip? (2026-11-20; the test was proposed by Douglas at Luma). EXPERIMENT TOOL, NOT PRODUCTION.

Question: do the scenes that go wrong at 360p (0.06 USD a clip) also go wrong at 1080p (1.20 USD a clip)? Luma has no seed, so every generation differs: for each scene we
make 3 clips at 360p and 2 at 1080p, all through the REAL production function (video_generation.generate_video_single, production arguments of the scene, same prompt,
original photo of the scene). Michele watches them BLIND (shuffled, only a code on screen, never the resolution) and labels each code bad / part / ok.
Then `score` compares, per scene, the share of defective clips at 360p and at 1080p. Nothing is written into any job; nothing is deleted.

  python3 exp_res_compare.py plan                       FREE: the scenes, the number of clips, the exact cost
  python3 exp_res_compare.py run  [--cap 11] [--go]     without --go: same as plan. With --go: spends real money (about 10.3 USD for the default 4 scenes)
  python3 exp_res_compare.py score RUN_ID LABELS.json   FREE: LABELS.json = {"bad": [codes], "part": [codes], "ok": [codes]}; prints the table per scene and the reading
  python3 exp_res_compare.py reveal RUN_ID              FREE: code -> scene / resolution (only after the labels are given)
Environment: PVS_JOBS_DIR = where the drafts are (test instance: /var/www/pvs_test_jobs), PVS_VOLUME_SCRATCH = where the videos go (production scratch, served on :8000).
Own spend file with a hard cap: every STARTED clip counts (failed ones too); the run stops starting clips once spent + the next clip would pass the cap.
"""
import json
import os
import random
import string
import sys
import threading
import time
from pathlib import Path

import exp_volume as ev

# (job, scene index, why it was picked). Source: scene_risk_events.jsonl of the 360p test instance, scenes with >= 2 non-pass QC verdicts, four different room categories.
SCENES = [("5dc50e0a", 4, "bagno, 3 rifiuti"), ("ac81fedd", 5, "esterno giardino, 2 rifiuti"), ("50567a81", 0, "esterno, 2 rifiuti"), ("50567a81", 4, "camera, 1 rifiuto 1 segnalata")]
N_DRAFT, N_FINAL = 3, 2
USD = {"360p": 0.06, "1080p": 1.20}
PER_VIDEO = 5
OUT = ev.SCRATCH / "rescompare"
SPEND = OUT / "spend.json"
_lock = threading.RLock()


def plan_rows(scenes=SCENES, n_draft=N_DRAFT, n_final=N_FINAL):
    """One row per clip to generate: job, scene, resolution, repeat number."""
    rows = []
    for job, i, why in scenes:
        rows += [{"job": job, "scene": i, "res": "360p", "rep": r + 1, "why": why} for r in range(n_draft)]
        rows += [{"job": job, "scene": i, "res": "1080p", "rep": r + 1, "why": why} for r in range(n_final)]
    return rows


def total_usd(rows):
    return round(sum(USD[r["res"]] for r in rows), 2)


def assign_codes(rows, rng=None):
    """A unique 3-letter code per clip and a shuffled review order. The code reveals nothing."""
    rng = rng or random.Random()
    seen, out = set(), []
    for r in rows:
        while True:
            c = "".join(rng.choice(string.ascii_lowercase) for _ in range(3))
            if c not in seen:
                seen.add(c)
                break
        out.append(dict(r, code=c))
    rng.shuffle(out)
    return out


def score(rows, labels):
    """rows: key rows (job, scene, res, code, ok). labels: code -> bad|part|ok. Per scene: defective share at 360p and at 1080p
    (defective = bad or part; strict = bad only). Clips that failed to generate or were not labelled are left out and counted."""
    per = {}
    skipped = 0
    for r in rows:
        lab = labels.get(r["code"])
        if not r.get("ok") or lab not in ("bad", "part", "ok"):
            skipped += 1
            continue
        d = per.setdefault((r["job"], r["scene"]), {"360p": [], "1080p": []})
        d[r["res"]].append(lab)
    table = []
    for (job, i), d in sorted(per.items()):
        row = {"job": job, "scene": i}
        for res in ("360p", "1080p"):
            v = d[res]
            row[res] = {"n": len(v), "defect": sum(1 for x in v if x != "ok"), "bad": sum(1 for x in v if x == "bad")}
        table.append(row)
    return {"table": table, "skipped": skipped, "reading": reading(table)}


def reading(table):
    """The 2x2: a scene is 'risky' at a resolution when at least half of its labelled clips there are defective. Needs >= 1 clip at both resolutions."""
    both = [t for t in table if t["360p"]["n"] and t["1080p"]["n"]]
    rk = lambda t, res: t[res]["defect"] * 2 >= t[res]["n"]
    a = sum(1 for t in both if rk(t, "360p") and rk(t, "1080p"))
    b = sum(1 for t in both if rk(t, "360p") and not rk(t, "1080p"))
    c = sum(1 for t in both if not rk(t, "360p") and rk(t, "1080p"))
    d = sum(1 for t in both if not rk(t, "360p") and not rk(t, "1080p"))
    return {"scenes": len(both), "risky_both": a, "risky_360_only": b, "risky_1080_only": c, "safe_both": d,
            "note": "n is tiny (a handful of scenes): this is an indication to report to Luma, not a statistic. No scene known to be SAFE is in the set, so false alarms are not measured."}


def spent():
    try:
        return float(json.loads(SPEND.read_text()).get("total_usd", 0.0))
    except Exception:
        return 0.0


def add_spend(usd, note):
    with _lock:
        OUT.mkdir(parents=True, exist_ok=True)
        try:
            d = json.loads(SPEND.read_text())
        except Exception:
            d = {"total_usd": 0.0, "runs": []}
        d["total_usd"] = round(d["total_usd"] + usd, 4)
        d["runs"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "usd": usd, "note": note})
        SPEND.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def generate(row, run_dir, cap):
    import video_generation as vg
    img, kw, scene = ev.scene_args(row["job"], row["scene"])
    clip = run_dir / f"{row['code']}.mp4"
    row = dict(row, ok=False, clip=str(clip), category=scene.get("category") or scene.get("room") or "")
    if not img:
        row["why"] = "no photo found"
        return row
    with _lock:                      # check and count in ONE step: parallel workers can never pass the cap together
        if spent() + USD[row["res"]] > cap:
            row["why"] = "cap reached, not generated"
            return row
        add_spend(USD[row["res"]], f"{row['job']} scene {row['scene']} {row['res']}")
    try:
        ok = vg.generate_video_single(str(img), 5, str(clip), **kw)
    except Exception as e:
        row["why"] = f"error {e}"
        return row
    row["ok"] = bool(ok and clip.exists())
    if not row["ok"]:
        row["why"] = "generation failed"
    ev.say(f"{row['code']}: {'ok' if row['ok'] else 'FAILED'} ({row['job']} scene {row['scene']} {row['res']} rep {row['rep']})")
    return row


def run(cap, go):
    rows = plan_rows()
    ev.say(f"{len(SCENES)} scenes, {len(rows)} clips ({N_DRAFT} x 360p + {N_FINAL} x 1080p per scene): {total_usd(rows)} USD. Cap {cap} USD, already spent {spent():.2f}.")
    for job, i, why in SCENES:
        ev.say(f"   {job} scene {i}: {why}")
    if not go:
        ev.say("Nothing done (no --go).")
        return 0
    if total_usd(rows) + spent() > cap:
        ev.say(f"STOP: plan {total_usd(rows)} + already spent {spent():.2f} is over the cap {cap}.")
        return 1
    from dotenv import load_dotenv
    load_dotenv(ev.HERE / ".env")
    import video_generation as vg
    vg.FAL_FALLBACK_ENABLED = False          # a failed Luma call must not silently become a pricier fal.ai clip
    run_id = time.strftime("%m%d_%H%M%S")
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    coded = assign_codes(rows)
    from concurrent.futures import ThreadPoolExecutor
    done = {}
    for res in ("360p", "1080p"):               # one resolution at a time: the environment variable is read at call time
        os.environ["PVS_LUMA_RESOLUTION"] = res
        batch = [r for r in coded if r["res"] == res]
        with ThreadPoolExecutor(max_workers=3) as ex:
            for r in ex.map(lambda r: generate(r, run_dir, cap), batch):
                done[r["code"]] = r
        ev.say(f"{res} done, spent so far {spent():.2f} USD")
    key = [done[r["code"]] for r in coded]            # shuffled order = review order
    (OUT / f"key_{run_id}.json").write_text(json.dumps(key, ensure_ascii=False, indent=1))
    names = []
    ok_rows = [r for r in key if r["ok"]]
    for n in range(0, len(ok_rows), PER_VIDEO):
        parts = []
        for r in ok_rows[n:n + PER_VIDEO]:
            lab = run_dir / f"lab_{r['code']}.mp4"
            if ev.label_clip(Path(r["clip"]), lab, f"CODE {r['code']}"):
                parts.append(lab)
        name = f"rescmp_{run_id}_{n // PER_VIDEO + 1}.mp4"
        if parts and ev.concat(parts, ev.SCRATCH / name):
            names.append((name, [r["code"] for r in ok_rows[n:n + PER_VIDEO]]))
    ev.say("=" * 30, "RUN", run_id, f"spent total {spent():.2f} USD, clips ok {len(ok_rows)} of {len(key)}")
    for name, codes in names:
        ev.say(f"  {ev.LINK_BASE}/{name}    codes in order: {' '.join(codes)}")
    ev.say(f"Watch them in this order and label every code: bad (hallucination / wrong movement), part, ok. Then: score {run_id} LABELS.json")
    return 0


def main(argv):
    def opt(name, default):
        return type(default)(argv[argv.index(name) + 1]) if name in argv else default
    cmd = argv[1] if len(argv) > 1 else "plan"
    if cmd in ("plan", "run"):
        return run(opt("--cap", 11.0), cmd == "run" and "--go" in argv)
    key = json.loads((OUT / f"key_{argv[2]}.json").read_text())
    if cmd == "score":
        lab = json.loads(Path(argv[3]).read_text())
        labels = {c: k for k, v in lab.items() for c in v}
        s = score(key, labels)
        print(f"{'scena':<16}{'360p: difetti/clip':<22}{'1080p: difetti/clip':<22}")
        for t in s["table"]:
            print(f"{t['job']} idx {t['scene']:<4}  {t['360p']['defect']}/{t['360p']['n']} (bad {t['360p']['bad']})".ljust(38) + f"{t['1080p']['defect']}/{t['1080p']['n']} (bad {t['1080p']['bad']})")
        print("clip non generati o senza etichetta:", s["skipped"])
        print(json.dumps(s["reading"], ensure_ascii=False, indent=1))
        return 0
    if cmd == "reveal":
        for r in key:
            print(r["code"], r["job"], r["scene"], r["res"], "rep", r["rep"], "ok" if r["ok"] else "FAILED")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
