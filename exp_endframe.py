"""
exp_endframe.py -- EXPERIMENT TOOL, NOT PRODUCTION (2026-10-30).

Question it answers: can an image model produce a believable END FRAME for a clip, i.e. the same room seen from a
point a little further forward (a real new viewpoint, NOT a crop/zoom)? The end frame would then be given to Luma
as `end_frame`, so that Luma only interpolates between two coherent pictures instead of animating the scene.

Reads the job's original photo (read-only), asks up to four generators for the end frame, saves the results and a
side-by-side comparison in jobs/_test_scratch (served at https://api.propertyvideostudioai.com/test-scratch/).
Never touches anything else, never deletes, never writes inside a job folder.

Usage (from /var/www/property-video-studio, venv active):
  python3 exp_endframe.py JOB_ID SCENE_INDEX [--meters 1.0] [--gens nb2,nbpro,uni1] [--jobs-dir DIR] [--go]
Without --go it only prints the plan and the estimated cost (nothing is spent).

Generators: nb2 = fal-ai/nano-banana-2/edit (1K), nbpro = fal-ai/nano-banana-pro/edit (1K),
            uni1 / uni1max = Luma Agents API image_edit (same key and host as the video calls: LUMA_API_KEY).
Estimated cost per image (USD for fal, public price lists; the Luma figure is credits converted with an ASSUMPTION
that one 1080p clip = 400 credits = about EUR 1.1): nb2 0.08, nbpro 0.15, uni1 15 credits, uni1max 35 credits.
"""
import argparse
import json
import os
import shutil
import sys
import time
from io import BytesIO
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

JOBS_DEFAULT = "/var/www/pvs_test_jobs"
OUT_DIR = Path(os.environ.get("PVS_SCRATCH_DIR", "/var/www/property-video-studio/jobs/_test_scratch"))
PUBLIC = "https://api.propertyvideostudioai.com/test-scratch/"
LUMA_URL = "https://agents.lumalabs.ai/v1/generations"
MAX_GENS = 4

# name -> (kind, model id, estimated cost text)
GENERATORS = {
    "nb2":     ("fal",  "fal-ai/nano-banana-2/edit",   "~USD 0.08"),
    "nbpro":   ("fal",  "fal-ai/nano-banana-pro/edit", "~USD 0.15"),
    "uni1":    ("luma", "uni-1",                       "15 credits (~EUR 0.04 if 400 credits = EUR 1.1)"),
    "uni1max": ("luma", "uni-1-max",                   "35 credits (~EUR 0.10 if 400 credits = EUR 1.1)"),
}


def build_prompt(meters: float) -> str:
    unit = "metre" if meters == 1 else "metres"
    return (
        "Photorealistic real-estate photograph of exactly the same room as the input photo, taken with the same camera, "
        "lens, height, exposure and lighting. "
        f"The only change is the viewpoint: the camera has moved straight forward by about {meters:g} {unit} along the "
        "direction it was already pointing, keeping the same height and the same horizontal direction. "
        "Every object, wall, window, piece of furniture and decoration visible in the input stays exactly as it is in the "
        "input photo, with the same shapes, colours, positions and the same state of open or closed. "
        "The parts of the room that come into view at the edges are a plain, unremarkable continuation of the same room. "
        "The picture is completely still, like a frozen moment."
    )


def find_photo(jobs_dir: Path, job_id: str, scene: int) -> Path:
    job_dir = jobs_dir / job_id
    meta = json.load(open(job_dir / "job_meta.json"))
    sid = meta["scenes_config"][scene].get("scene_id")
    cands = []
    if sid:
        cands += [job_dir / "images" / f"{sid}{e}" for e in (".jpg", ".jpeg", ".png", ".webp")]
    cands += [job_dir / "images" / f"scene_{scene:03d}{e}" for e in (".jpg", ".jpeg", ".png", ".webp")]
    for c in cands:
        if c.is_file():
            return c
    raise SystemExit("photo not found, tried: " + ", ".join(str(c) for c in cands))


def run_fal(model: str, photo: Path, prompt: str) -> bytes:
    import fal_client
    src = fal_client.upload_file(str(photo))
    res = fal_client.subscribe(model, arguments={
        "prompt": prompt, "image_urls": [src], "resolution": "1K", "output_format": "jpeg", "num_images": 1})
    url = res["images"][0]["url"]
    return requests.get(url, timeout=60).content


def run_luma(model: str, source_url: str, prompt: str, record: dict) -> bytes:
    key = os.environ.get("LUMA_API_KEY")
    if not key:
        raise RuntimeError("LUMA_API_KEY not set")
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    r = requests.post(LUMA_URL, headers=h, timeout=30,
                      json={"type": "image_edit", "model": model, "prompt": prompt, "source": {"url": source_url}})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Luma create HTTP {r.status_code}: {r.text[:300]}")
    gid = r.json().get("id")
    record["generation_id"] = gid
    print(f"   luma generation id {gid}")
    waited = 0
    while waited < 300:
        time.sleep(4)
        waited += 4
        d = requests.get(f"{LUMA_URL}/{gid}", headers={"Authorization": f"Bearer {key}"}, timeout=30).json()
        if d.get("state") == "completed":
            return requests.get(d["output"][0]["url"], timeout=60).content
        if d.get("state") == "failed":
            raise RuntimeError(f"Luma failed: {d.get('failure_code')} {d.get('failure_reason')}")
    raise RuntimeError("Luma timeout after 300 s (generation may still be billed)")


def compare_sheet(photo: Path, results: dict, out: Path):
    from PIL import Image, ImageDraw
    tiles = [("ORIGINALE", Image.open(photo).convert("RGB"))]
    for name, path in results.items():
        tiles.append((name, Image.open(path).convert("RGB")))
    H = 540
    resized = []
    for label, im in tiles:
        w = max(1, round(im.width * H / im.height))
        resized.append((label, im.resize((w, H))))
    W = sum(im.width for _, im in resized)
    sheet = Image.new("RGB", (W, H + 30), "white")
    x = 0
    d = ImageDraw.Draw(sheet)
    for label, im in resized:
        sheet.paste(im, (x, 30))
        d.text((x + 6, 8), label, fill="black")
        x += im.width
    sheet.save(out, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("scene", type=int)
    ap.add_argument("--meters", type=float, default=1.0)
    ap.add_argument("--gens", default="nb2,nbpro,uni1")
    ap.add_argument("--jobs-dir", default=JOBS_DEFAULT)
    ap.add_argument("--go", action="store_true", help="really spend (default: plan only)")
    a = ap.parse_args()

    gens = [g.strip() for g in a.gens.split(",") if g.strip()]
    bad = [g for g in gens if g not in GENERATORS]
    if bad or not gens or len(gens) > MAX_GENS:
        raise SystemExit(f"generators must be 1-{MAX_GENS} of {sorted(GENERATORS)}; got {a.gens}")

    photo = find_photo(Path(a.jobs_dir), a.job_id, a.scene)
    prompt = build_prompt(a.meters)
    print("photo :", photo)
    print("prompt:", prompt)
    for g in gens:
        print(f" - {g}: {GENERATORS[g][1]}  cost {GENERATORS[g][2]}")
    if not a.go:
        print("PLAN ONLY (nothing spent). Add --go to run.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{a.job_id}_s{a.scene}"
    src_copy = OUT_DIR / f"endf_src_{tag}{photo.suffix.lower()}"
    shutil.copyfile(photo, src_copy)           # copy only; the job folder is never written
    source_url = PUBLIC + src_copy.name
    results, log = {}, {"job": a.job_id, "scene": a.scene, "meters": a.meters, "prompt": prompt, "runs": {}}
    for g in gens:
        kind, model, _ = GENERATORS[g]
        rec = {"model": model}
        log["runs"][g] = rec
        print(f">> {g} ({model}) ...")
        t0 = time.time()
        try:
            raw = run_fal(model, photo, prompt) if kind == "fal" else run_luma(model, source_url, prompt, rec)
            from PIL import Image
            out = OUT_DIR / f"endf_{tag}_{g}.jpg"
            Image.open(BytesIO(raw)).convert("RGB").save(out, quality=92)
            results[g] = out
            rec["file"] = out.name
            rec["secs"] = round(time.time() - t0, 1)
            print(f"   ok in {rec['secs']} s -> {PUBLIC}{out.name}")
        except Exception as e:
            rec["error"] = str(e)[:400]
            print(f"   FAILED: {rec['error']}")
    (OUT_DIR / f"endf_{tag}_log.json").write_text(json.dumps(log, indent=2))
    if results:
        sheet = OUT_DIR / f"endf_{tag}_confronto.jpg"
        compare_sheet(photo, results, sheet)
        print("CONFRONTO:", PUBLIC + sheet.name)


if __name__ == "__main__":
    main()
