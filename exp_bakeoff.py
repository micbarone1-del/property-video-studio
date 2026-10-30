"""
exp_bakeoff.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-10-30).

Compares the generators of the END frame on the same scenes, with the SAME objective checks (no impressions):
  nb2      Nano Banana 2 on fal (today's choice, the reference)
  qwen     Qwen Image Edit 2511 Multiple Angles on fal (explicit camera control: zoom sweep 6, 7, 8; fixed seeds)
  kontext  FLUX.1 Kontext Max on fal
  uni1     Luma uni-1 image edit (same account as the video; its output is about twice the size, here scaled DOWN to the start frame's size)
  depth    the project's depth_renderer (depth-anything depth + depth-weighted warp, no generative model: every pixel comes from the photo);
           used ONLY to make one still end frame, not a video (the video use was rejected by Michele). dz sweep 1.2, 1.7, 2.2
Per run it measures: scale, rotation, expansion point, share inside the start view (exp_geometry), the geometry gate of exp_director, and,
when the gate passes, the Claude check (invented/changed objects, visual artefacts). The plan (target, scale, prompt) is the one the director
already wrote for the scene (jobs/_test_scratch/endd_<job>_s<scene>_log.json): the same prompt for every model.
Outputs only in jobs/_test_scratch (never in a job). Generation runs 4 at a time.

  python3 exp_bakeoff.py JOB SCENES [--models nb2,qwen,kontext,uni1,depth] [--runs 3] [--jobs-dir DIR]     plan only
  python3 exp_bakeoff.py JOB SCENES ... --go                                                                  spends (about USD 2 for 2 scenes, 3 runs, 5 models)
"""
import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_endframe as ef
import exp_director as dr
import exp_geometry as geo

MODELS = ("nb2", "qwen", "kontext", "uni1", "depth")
QWEN_ZOOMS = (6.0, 7.0, 8.0)
DEPTH_DZ = (1.2, 1.7, 2.2)
EST = {"nb2": "USD 0.08 / image", "qwen": "about USD 0.04 / image (the LoRA endpoint price is not listed: check the invoice)",
       "kontext": "USD 0.08 / image", "uni1": "15 credits / image (about EUR 0.04 if 400 credits = EUR 1.1)", "depth": "about EUR 0.001 / scene (depth map)"}


def _fal_run(endpoint: str, args: dict) -> bytes:
    import fal_client
    res = fal_client.subscribe(endpoint, arguments=args)
    return requests.get(res["images"][0]["url"], timeout=60).content


def gen_nb2(ctx, run):
    return ef.run_fal("fal-ai/nano-banana-2/edit", ctx["photo"], ctx["prompt"]), ""


def gen_qwen(ctx, run):
    z = QWEN_ZOOMS[run % len(QWEN_ZOOMS)]
    raw = _fal_run("fal-ai/qwen-image-edit-2511-multiple-angles", {
        "image_urls": [ctx["fal_url"]], "horizontal_angle": 0, "vertical_angle": 0, "zoom": z, "lora_scale": 1,
        "output_format": "jpeg", "num_images": 1, "seed": 1000 + run,
        "additional_prompt": "The same room, everything exactly as in the original, completely still."})
    return raw, f"zoom {z:g}"


def gen_kontext(ctx, run):
    raw = _fal_run("fal-ai/flux-pro/kontext/max", {"prompt": ctx["prompt"], "image_url": ctx["fal_url"], "output_format": "jpeg",
                                                   "num_images": 1, "safety_tolerance": "5"})
    return raw, ""


def gen_uni1(ctx, run):
    rec = {}
    raw = ef.run_luma("uni-1", ctx["source_url"], ctx["prompt"], rec)
    return raw, f"luma id {str(rec.get('generation_id'))[:8]}"


def gen_depth(ctx, run):
    import cv2
    import depth_renderer as dp
    img = cv2.imread(str(ctx["photo"]))
    depth = cv2.resize(ctx["depth"], (img.shape[1], img.shape[0]))
    dz = DEPTH_DZ[run % len(DEPTH_DZ)]
    warped, hole = dp._reproject_frame(img, depth, 0.0, 0.0, dz)
    out = dp._fill_holes(warped, hole)
    return cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes(), f"dz {dz:g}"


GENERATORS = {"nb2": gen_nb2, "qwen": gen_qwen, "kontext": gen_kontext, "uni1": gen_uni1, "depth": gen_depth}


def load_plan(job: str, scene: int) -> dict:
    p = ef.OUT_DIR / f"endd_{job}_s{scene}_log.json"
    if not p.is_file():
        raise SystemExit(f"plan not found: {p} (run exp_director.py for this scene first)")
    return json.load(open(p))["director"]


def sheet(photo: Path, rows: list, out: Path, models: list, runs: int):
    from PIL import Image, ImageDraw
    tw, th = 400, 225
    W, H = tw * (len(models) + 1), (th + 22) * (runs + 1)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    img.paste(Image.open(photo).convert("RGB").resize((tw, th)), (0, 22))
    d.text((4, 4), "ORIGINALE", fill="black")
    for mi, m in enumerate(models):
        d.text((tw * (mi + 1) + 4, 4), m, fill="black")
        for r in [x for x in rows if x["model"] == m and x.get("file")]:
            y = 22 + (th + 22) * r["run"]
            if r["run"] >= runs:
                continue
            try:
                img.paste(Image.open(ef.OUT_DIR / r["file"]).convert("RGB").resize((tw, th)), (tw * (mi + 1), y))
            except Exception:
                continue
            g = r.get("geometry") or {}
            tag = f"r{r['run']} x{g.get('scale')} {r['status']}"
            d.text((tw * (mi + 1) + 4, y + th + 4), tag, fill="black")
    img.save(out, quality=88)


def run_scene(jobs_dir: str, job: str, scene: int, models: list, runs: int, usage: dict) -> dict:
    from PIL import Image
    photo = dr.start_frame(jobs_dir, job, scene)
    plan = load_plan(job, scene)
    prompt, _ = dr.prompt_for(plan, 1)
    tag = f"{job}_s{scene}"
    ef.OUT_DIR.mkdir(parents=True, exist_ok=True)
    src_copy = ef.OUT_DIR / f"endf_src_{tag}{photo.suffix.lower()}"
    shutil.copyfile(photo, src_copy)
    ctx = {"photo": photo, "plan": plan, "prompt": prompt, "source_url": ef.PUBLIC + src_copy.name}
    if any(m in models for m in ("qwen", "kontext")):
        import fal_client
        ctx["fal_url"] = fal_client.upload_file(str(photo))
    if "depth" in models:
        import depth_renderer as dp
        ctx["depth"] = dp.estimate_depth(str(photo))
        if ctx["depth"] is None:
            print("  depth map failed: the depth model is skipped")
            models = [m for m in models if m != "depth"]
    start_size = Image.open(photo).size

    def job_fn(task):
        model, run = task
        row = {"model": model, "run": run, "scene": scene, "status": "ERROR"}
        try:
            raw, info = GENERATORS[model](ctx, run)
            raw_path = ef.OUT_DIR / f"bake_{tag}_{model}_r{run}_raw.jpg"
            Image.open(BytesIO(raw)).convert("RGB").resize(start_size, Image.LANCZOS).save(raw_path, quality=94)
            if model == "depth":
                final = raw_path
            else:
                final = ef.OUT_DIR / f"bake_{tag}_{model}_r{run}.jpg"
                ef.match_colour(raw_path, photo, final)
            row.update({"file": final.name, "info": info, "status": "generated"})
        except Exception as e:
            row["error"] = str(e)[:300]
        return row

    tasks = [(m, r) for m in models for r in range(runs)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(job_fn, tasks))
    for row in rows:                                   # measurements and Claude check, one at a time
        if row["status"] != "generated":
            print(f"  {row['model']:8s} r{row['run']} ERROR: {row.get('error')}")
            continue
        final = ef.OUT_DIR / row["file"]
        g = geo.analyse(photo, final)
        row["geometry"] = g
        problems = dr.gate_problems(g, plan)
        row["gate_problems"] = problems
        if problems:
            row["status"] = "gate FAIL"
            continue
        intent = (f"the camera ends at: {plan.get('end_position')}; target: {plan.get('target')} about {plan.get('target_scale')} times larger; "
                  f"what leaves the frame: {plan.get('leaves_the_frame')}")
        try:
            qc = dr.ask_claude(dr.QC_PROMPT.format(intent=intent, target=plan.get("target")), [photo, final], usage)
        except Exception as e:
            qc = {"verdict": "error", "reasons": [str(e)[:200]]}
        row["qc"] = qc
        row["status"] = "PASS" if str(qc.get("verdict")).lower() == "pass" else ("QC error" if qc.get("verdict") == "error" else "QC FAIL")
    sheet_path = ef.OUT_DIR / f"bake_{tag}_confronto.jpg"
    sheet(photo, rows, sheet_path, models, runs)
    return {"scene": scene, "photo": str(photo), "plan_target": plan.get("target"), "rows": rows, "sheet": sheet_path.name}


def report(res: dict):
    print(f"=== scena {res['scene']} | bersaglio: {res['plan_target']} ===")
    for r in sorted(res["rows"], key=lambda x: (x["model"], x["run"])):
        g = r.get("geometry") or {}
        qc = r.get("qc") or {}
        inv = qc.get("invented_or_changed") or []
        art = qc.get("artifacts") or []
        link = ef.PUBLIC + r["file"] if r.get("file") else "-"
        print(f"  {r['model']:8s} r{r['run']} {r['status']:9s} | scala {g.get('scale')} | espansione ({g.get('foe_x')}, {g.get('foe_y')}) | rot {g.get('rotation_deg')} | "
              f"dentro {g.get('inside')} | inventati {len(inv)} | artefatti {len(art)} | {r.get('info', '')} | {link}")
        for i in inv[:2]:
            print(f"        inventato/cambiato: {str(i)[:160]}")
        if r["status"] == "gate FAIL":
            print(f"        gate: {' '.join(r.get('gate_problems') or [])[:140]}")
    print("  --- riepilogo per modello ---")
    for m in dict.fromkeys(x["model"] for x in res["rows"]):
        rs = [x for x in res["rows"] if x["model"] == m]
        gen = [x for x in rs if x.get("geometry")]
        scales = [x["geometry"]["scale"] for x in gen if x["geometry"].get("ok")]
        print(f"  {m:8s} prove {len(rs)} | generate {len(gen)} | gate ok {sum(1 for x in gen if not x['gate_problems'])} | "
              f"PASS {sum(1 for x in rs if x['status'] == 'PASS')} | scala media {round(sum(scales) / len(scales), 2) if scales else None}")
    print("  CONFRONTO:", ef.PUBLIC + res["sheet"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("scenes")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--jobs-dir", default=ef.JOBS_DEFAULT)
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    bad = [m for m in models if m not in GENERATORS]
    scenes = [int(x) for x in a.scenes.split(",") if x.strip()]
    if bad or not models or a.runs < 1 or a.runs > 3:
        raise SystemExit(f"models must be among {MODELS}; runs 1-3")
    n_img = len(models) * a.runs * len(scenes)
    print(f"{len(scenes)} scene(s) x {len(models)} model(s) x {a.runs} run(s) = {n_img} images; Claude check only when the geometry gate passes")
    for m in models:
        print(f" - {m}: {EST[m]}")
    if not a.go:
        print("PLAN ONLY (nothing spent). Add --go to run.")
        return
    usage, out = {}, []
    t0 = time.time()
    for s in scenes:
        print(f"... scena {s}", flush=True)
        res = run_scene(a.jobs_dir, a.job_id, s, models, a.runs, usage)
        out.append(res)
        report(res)
        sys.stdout.flush()
    cost = round((usage.get("in", 0) * dr.PRICE_IN + usage.get("out", 0) * dr.PRICE_OUT) / 1e6, 3)
    print(f"Claude tokens in/out {usage.get('in')}/{usage.get('out')} (~USD {cost}); total time {time.time() - t0:.0f} s")
    (ef.OUT_DIR / f"bake_{a.job_id}_log.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
