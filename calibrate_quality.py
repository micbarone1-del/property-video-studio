"""Calibration of the photo-quality judge (listing_scraper.assess_photo_quality) on the ORIGINAL photos of past jobs.
READ-ONLY on jobs/: it only opens files, never writes, moves or deletes anything there. Results go to --out (default /tmp/pvs_calibration).

  python3 calibrate_quality.py                      # DRY RUN (default): counts unique photos, shows the cost estimate, calls nothing
  python3 calibrate_quality.py --run --max 120      # real Claude calls (cents), stops by itself at --cap EUR
  python3 calibrate_quality.py --degrade-test 6          # DRY RUN of the control test (see below)
  python3 calibrate_quality.py --degrade-test 6 --run    # control test: 6 photos x (original + 3 deliberately damaged copies) = 24 calls

CONTROL TEST (--degrade-test N): the past photos contain no really blurred or blocky picture, so the judge cannot be checked on them.
So N photos are damaged on purpose (blur / pixelated / heavy JPEG compression, copies written to --out/degraded, never to jobs/) and
the judge must call the damaged copies soft or blocky and must NOT call the originals soft or blocky.

Output of a real run: verdicts.csv (job, file, size, verdict) and contact sheets sheet_<verdict>_N.jpg (thumbnails labelled with
job/file) so the verdicts can be compared by eye with the photos. Unique photos only (same bytes = one call)."""
import argparse, csv, hashlib, os, random, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import listing_scraper as ls

EXTS = {".jpg", ".jpeg", ".png", ".webp"}
EST_IN_TOKENS, EST_OUT_TOKENS = 1900, 5     # per photo: two 768 px images + the question (estimate; the real run prints the real figure)


def collect(jobs_dir: Path):
    """Unique usable original photos: [{"job","file","path","sha","w","h"}], plus counters. Reads files only."""
    seen, photos, stats = set(), [], {"files": 0, "duplicates": 0, "too_small_or_unreadable": 0}
    for img_dir in sorted(jobs_dir.glob("*/images")):
        for f in sorted(img_dir.iterdir()):
            if f.suffix.lower() not in EXTS or not f.is_file():
                continue
            stats["files"] += 1
            content = f.read_bytes()
            sha = hashlib.sha1(content).hexdigest()
            if sha in seen:
                stats["duplicates"] += 1
                continue
            seen.add(sha)
            u = ls.photo_usability(content)
            if not u["ok"]:
                stats["too_small_or_unreadable"] += 1
                continue
            photos.append({"job": img_dir.parent.name, "file": f.name, "path": f, "sha": sha, "w": u["width"], "h": u["height"]})
    return photos, stats


def pick(photos, n):
    """n photos spread over the jobs (round robin), deterministic."""
    if not n or n >= len(photos):
        return list(photos)
    by_job = {}
    for p in photos:
        by_job.setdefault(p["job"], []).append(p)
    rnd, out = random.Random(42), []
    for lst in by_job.values():
        rnd.shuffle(lst)
    while len(out) < n and any(by_job.values()):
        for lst in by_job.values():
            if lst and len(out) < n:
                out.append(lst.pop())
    return out


VARIANTS = ("blur", "pixelated", "jpegblocks")


def make_variants(content: bytes) -> dict:
    """Deliberately damaged copies of one photo, as JPEG bytes: blur (strong Gaussian), pixelated (shrunk to 1/6 and enlarged with big
    square pixels), jpegblocks (the same size saved at JPEG quality 3: visible 8x8 blocks and banding)."""
    import io
    from PIL import Image, ImageFilter
    im = Image.open(io.BytesIO(content)).convert("RGB")
    w, h = im.size
    out = {}

    def jpeg(img, q):
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=q); return buf.getvalue()
    out["blur"] = jpeg(im.filter(ImageFilter.GaussianBlur(radius=max(6, w // 150))), 90)
    out["pixelated"] = jpeg(im.resize((max(1, w // 6), max(1, h // 6)), Image.BILINEAR).resize((w, h), Image.NEAREST), 90)
    out["jpegblocks"] = jpeg(im, 3)
    return out


def degrade_test(photos, n, run, cap, out_dir):
    chosen = pick(photos, n)
    calls = len(chosen) * (1 + len(VARIANTS))
    est = ls.claude_cost_eur(EST_IN_TOKENS * calls, EST_OUT_TOKENS * calls)
    print(f"CONTROL TEST: {len(chosen)} photos x (original + {len(VARIANTS)} damaged copies) = {calls} calls, estimated cost about {est:.3f} EUR (cap {cap:.2f} EUR)")
    if not run:
        print("DRY RUN: no call was made, nothing was written. Add --run to spend.")
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    deg_dir = out_dir / "degraded"; deg_dir.mkdir(parents=True, exist_ok=True)
    ls.reset_claude_usage()
    items = []
    for p in chosen:
        content = p["path"].read_bytes()
        items.append({**p, "variant": "original", "bytes": content, "path": p["path"]})
        for name, data in make_variants(content).items():
            f = deg_dir / f"{p['sha'][:8]}_{name}.jpg"
            f.write_bytes(data)
            items.append({**p, "variant": name, "bytes": data, "path": f, "file": f.name})
    stop = False

    def one(it):
        nonlocal stop
        if stop:
            return None
        r = ls.assess_photo_quality(it["bytes"], label=f"{it['variant']}/{it['sha'][:8]}")
        if ls.get_claude_cost()["cost_eur"] >= cap:
            stop = True
        return {**it, "verdict": r["verdict"], "overlay": r.get("overlay", ""), "call_ok": r.get("call_ok", True)}

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = [r for r in ex.map(one, items) if r]
    caught = sum(1 for r in results if r["variant"] != "original" and r["verdict"] in ls.PHOTO_QUALITY_POOR)
    damaged = sum(1 for r in results if r["variant"] != "original")
    false_alarms = sum(1 for r in results if r["variant"] == "original" and r["verdict"] in ls.PHOTO_QUALITY_POOR)
    originals = sum(1 for r in results if r["variant"] == "original")
    with open(out_dir / "degrade_test.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["photo", "variant", "verdict", "overlay"])
        for r in results:
            w.writerow([r["sha"][:8], r["variant"], r["verdict"], r["overlay"]])
    print("\nphoto     variant      verdict  overlay")
    for r in results:
        print(f"{r['sha'][:8]}  {r['variant']:<11}  {r['verdict']:<7}  {r['overlay']}")
    by_variant = {}
    for r in results:
        if r["variant"] != "original":
            by_variant.setdefault(r["variant"], [0, 0])
            by_variant[r["variant"]][1] += 1
            by_variant[r["variant"]][0] += r["verdict"] in ls.PHOTO_QUALITY_POOR
    print(f"\nDAMAGED copies recognised as soft/blocky: {caught} of {damaged}  ({', '.join(f'{k} {v[0]}/{v[1]}' for k, v in by_variant.items())})")
    print(f"ORIGINALS wrongly called soft/blocky (false alarms): {false_alarms} of {originals}")
    cost = ls.get_claude_cost()
    failed = sum(1 for r in results if not r["call_ok"])
    print(f"REAL Claude cost: {cost['cost_eur']:.4f} EUR ({cost['calls']} calls){' - stopped at the cap' if stop else ''} | model: {ls.MODEL}")
    if failed:
        print(f"WARNING: {failed} of {len(results)} judge calls FAILED (verdict unknown): wrong model name or no access? Results are not usable.")
    for r in results:
        r["verdict"] = f"{r['variant']}_judged_{r['verdict']}"
        r["w"], r["h"] = r.get("w"), r.get("h")
    made = sheets(results, out_dir)
    print(f"written: {out_dir}/degrade_test.csv, damaged copies in {deg_dir}, {len(made)} contact sheet(s):")
    for p in made:
        print("  ", p)


def sheets(results, out_dir: Path):
    from PIL import Image, ImageDraw
    groups = {}
    for r in results:
        groups.setdefault(r["verdict"], []).append(r)
    made = []
    for verdict, lst in groups.items():
        if verdict == "ok":
            lst = random.Random(1).sample(lst, min(len(lst), 24))
        for page, i in enumerate(range(0, len(lst), 12), 1):
            chunk = lst[i:i + 12]
            cols, tw, th, cap = 4, 420, 300, 34
            rows = (len(chunk) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * tw, rows * (th + cap)), "white")
            d = ImageDraw.Draw(sheet)
            for k, r in enumerate(chunk):
                im = Image.open(r["path"]).convert("RGB"); im.thumbnail((tw, th))
                x, y = (k % cols) * tw, (k // cols) * (th + cap)
                sheet.paste(im, (x, y))
                d.text((x + 4, y + th + 4), f"{verdict}  {r['job'][:8]}/{r['file']}  {r['w']}x{r['h']}", fill="black")
            p = out_dir / f"sheet_{verdict}_{page}.jpg"
            sheet.save(p, quality=88); made.append(p)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs-dir", default=os.getenv("PVS_JOBS_DIR") or str(Path(__file__).resolve().parent / "jobs"))
    ap.add_argument("--out", default="/tmp/pvs_calibration")
    ap.add_argument("--max", type=int, default=0, help="at most N unique photos (spread over the jobs); 0 = all")
    ap.add_argument("--run", action="store_true", help="really call Claude (without it: dry run, nothing is sent)")
    ap.add_argument("--cap", type=float, default=0.50, help="stop when the real Claude cost reaches this many EUR")
    ap.add_argument("--degrade-test", type=int, default=0, metavar="N", help="control test on N photos damaged on purpose (see top of file)")
    ap.add_argument("--model", default="", help="judge with another Claude model FOR THIS RUN ONLY (e.g. claude-haiku-5-5); the production model is not changed")
    a = ap.parse_args()
    if a.model:
        ls.MODEL = a.model      # this process only: calls AND the cost formula use it (claude_cost_eur reads MODEL at call time)

    photos, stats = collect(Path(a.jobs_dir))
    if a.degrade_test:
        print(f"unique usable photos: {len(photos)} | model: {ls.MODEL}")
        degrade_test(photos, a.degrade_test, a.run, a.cap, Path(a.out))
        return
    chosen = pick(photos, a.max)
    est = ls.claude_cost_eur(EST_IN_TOKENS * len(chosen), EST_OUT_TOKENS * len(chosen))
    print(f"files read: {stats['files']} | duplicates skipped: {stats['duplicates']} | too small/unreadable skipped: {stats['too_small_or_unreadable']}")
    print(f"unique usable photos: {len(photos)} | selected for this run: {len(chosen)} | model: {ls.MODEL}")
    print(f"ESTIMATED Claude cost: about {est:.3f} EUR (cap {a.cap:.2f} EUR)")
    if not a.run:
        print("DRY RUN: no call was made, nothing was written. Add --run to spend.")
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    out_dir = Path(a.out); out_dir.mkdir(parents=True, exist_ok=True)
    ls.reset_claude_usage()
    results, stop = [], False

    def one(p):
        nonlocal stop
        if stop:
            return None
        r = ls.assess_photo_quality(p["path"].read_bytes(), label=f"{p['job'][:8]}/{p['file']}")
        if ls.get_claude_cost()["cost_eur"] >= a.cap:
            stop = True
        return {**p, "verdict": r["verdict"], "overlay": r.get("overlay", "")}

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = [r for r in ex.map(one, chosen) if r]
    cost = ls.get_claude_cost()
    with open(out_dir / "verdicts.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["job", "file", "width", "height", "verdict", "overlay"])
        for r in results:
            w.writerow([r["job"], r["file"], r["w"], r["h"], r["verdict"], r["overlay"]])
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    made = sheets(results, out_dir)
    print(f"\nphotos judged: {len(results)} of {len(chosen)}{' (stopped at the cap)' if stop else ''}")
    print("verdicts:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"REAL Claude cost: {cost['cost_eur']:.4f} EUR ({cost['calls']} calls, {cost['input_tokens']} in / {cost['output_tokens']} out tokens)")
    print(f"written: {out_dir}/verdicts.csv and {len(made)} contact sheet(s):")
    for p in made:
        print("  ", p)


if __name__ == "__main__":
    main()
