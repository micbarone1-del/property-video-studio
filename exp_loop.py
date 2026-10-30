"""
exp_loop.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-10-30).

Measures what the single-shot bake-off could not: how often the director's REAL loop (up to 3 attempts, each failed attempt followed by a
written correction) ends with an end frame that passes, when the attempts alternate image models. It reuses exp_director.direct_one_scene
unchanged (one implementation of gate, correction and Claude check); only the generator and the model order are plugged in, and the
director's plan is the one already stored for the scene (endd_<job>_s<scene>_log.json), so only the image model varies between rounds.
Models: nb2 = Nano Banana 2 (fal), uni1 = Luma uni-1 image edit (scaled DOWN to the start frame's size). Default order: nb2, uni1, uni1.
Outputs only in jobs/_test_scratch (never in a job). The rounds of one scene run in parallel.

  python3 exp_loop.py JOB SCENES [--rounds 3] [--order nb2,uni1,uni1] [--jobs-dir DIR]      plan only
  python3 exp_loop.py JOB SCENES ... --go                                                    spends (max rounds x 3 images per scene)
"""
import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_endframe as ef
import exp_director as dr

NAMES = {"nb2": "fal-ai/nano-banana-2/edit", "uni1": "uni-1"}


def stored_plan(job, scene):
    p = ef.OUT_DIR / f"endd_{job}_s{scene}_log.json"
    if not p.is_file():
        raise SystemExit(f"plan not found: {p} (run exp_director.py for this scene first)")
    return json.load(open(p))["director"]


def make_gen(photo, tag):
    size = Image.open(photo).size
    src = ef.OUT_DIR / f"endf_src_{tag}{photo.suffix.lower()}"
    shutil.copyfile(photo, src)
    def gen(prompt, model):
        if model == NAMES["nb2"]:
            return ef.run_fal(model, photo, prompt)
        raw = ef.run_luma(model, ef.PUBLIC + src.name, prompt, {})
        buf = BytesIO()
        Image.open(BytesIO(raw)).convert("RGB").resize(size, Image.LANCZOS).save(buf, "JPEG", quality=94)
        return buf.getvalue()
    return gen


def make_ask(plan):
    def ask(prompt, images, usage):
        if prompt.startswith(dr.DIRECTOR_PROMPT[:200]):
            return plan                            # same plan in every round: only the image model varies
        return dr.ask_claude(prompt, images, usage)
    return ask


def one_round(job, scene, photo, plan, rnd):
    tag = f"{job}_s{scene}_L{rnd}"
    return rnd, dr.direct_one_scene(photo, tag, ask=make_ask(plan), gen=make_gen(photo, tag))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("scenes")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--order", default="nb2,uni1,uni1")
    ap.add_argument("--jobs-dir", default=ef.JOBS_DEFAULT)
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    order = [m.strip() for m in a.order.split(",")]
    scenes = [int(x) for x in a.scenes.split(",")]
    if len(order) != 3 or any(m not in NAMES for m in order) or not 1 <= a.rounds <= 4:
        raise SystemExit("--order needs 3 models among nb2,uni1; --rounds 1-4")
    dr.FAL_MODELS = tuple(NAMES[m] for m in order)
    n = len(scenes) * a.rounds
    print(f"{len(scenes)} scene(s) x {a.rounds} round(s) = {n} loops, each up to 3 attempts (order {order}); max {n * 3} images,"
          f" nb2 ~USD 0.08, uni-1 15 credits each; Claude check only after a passing geometry")
    if not a.go:
        print("PLAN ONLY (nothing spent). Add --go to run.")
        return
    ef.OUT_DIR.mkdir(parents=True, exist_ok=True)
    allres, t0 = {}, time.time()
    for s in scenes:
        photo = dr.start_frame(a.jobs_dir, a.job_id, s)
        plan = stored_plan(a.job_id, s)
        print(f"=== scena {s} | bersaglio: {plan.get('target')} | scala chiesta {plan.get('target_scale')}", flush=True)
        with ThreadPoolExecutor(max_workers=a.rounds) as ex:
            res = sorted(ex.map(lambda r: one_round(a.job_id, s, photo, plan, r), range(1, a.rounds + 1)))
        allres[s] = {}
        for rnd, log in res:
            allres[s][rnd] = {"final": log["final"], "attempts": [{"model": x.get("model"), "scale": (x.get("geometry") or {}).get("scale"),
                              "gate": x.get("gate_problems"), "verdict": (x.get("qc") or {}).get("verdict")} for x in log["attempts"]]}
            print(f"  giro {rnd}: {'PASS' if log['final']['pass'] else 'FAIL'} dopo {log['final']['attempts']} tentativo/i")
            for x in log["attempts"]:
                g = x.get("geometry") or {}
                q = x.get("qc") or {}
                inv = q.get("invented_or_changed") or []
                print(f"     t{x['n']} {x['model'].split('/')[-2] if '/' in x['model'] else x['model']:14s} scala {g.get('scale')} | espansione ({g.get('foe_x')}, {g.get('foe_y')}) | "
                      f"rot {g.get('rotation_deg')} | gate {'ok' if not x.get('gate_problems') else 'FAIL'} | QC {q.get('verdict')} | inventati {len(inv)} | {ef.PUBLIC + x['matched_file']}")
            print(f"     confronto: {ef.PUBLIC + log['sheet']}")
        ok = [r for r, l in res if l["final"]["pass"]]
        print(f"  --> scena {s}: {len(ok)}/{a.rounds} giri finiscono in PASS entro 3 tentativi (tentativi usati nei PASS: "
              f"{[l['final']['attempts'] for r, l in res if l['final']['pass']]})", flush=True)
    (ef.OUT_DIR / f"loop_{a.job_id}_log.json").write_text(json.dumps(allres, indent=2, default=str))
    print(f"tempo totale {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
