"""video_library.py - a library of the finished videos, sorted by agency, so test videos can be reused later (2026-10-30).

Reads the jobs of the production and the test instance (read-only), and COPIES every finished video into
/var/www/pvs_library/<agency>/<job>_<property>.mp4 with one metadata file per video and a master index (index.json + index.html).
Nothing is ever deleted or moved, and jobs/ is never written to (the only write near it is --publish, which ADDS one file to the test-scratch folder).

  python3 video_library.py                    # dry run: what would be copied (default, writes nothing)
  python3 video_library.py --copy             # copy new videos, refresh the index
  python3 video_library.py --mark JOB --reusable yes|no [--note "text"]     # Michele's review of one video (index only)
  python3 video_library.py --publish JOB      # copy one video to the test-scratch folder under a random name, print the https link

Agencies are grouped by NAME (the test instance created one GIAL IMMOBILIARE client per listing); the review fields survive re-runs.
"""
import argparse, html, json, re, secrets, shutil, sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_OUT = Path("/var/www/pvs_library")
SOURCES = [("prod", BASE / "jobs", BASE / "agencies.json"),
           ("test", Path("/var/www/pvs_test_jobs"), Path("/var/www/pvs_test_state/data/agencies.json"))]
SCRATCH = BASE / "jobs" / "_test_scratch"
PUBLIC = "https://api.propertyvideostudioai.com/test-scratch/"


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "senza-nome"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def collect(sources):
    """Pure-ish: [{job_id, instance, agency, listing_ref, property_name, ...}] for every finished job that has its video file."""
    out = []
    for label, jobs_dir, agencies_file in sources:
        names = {a.get("agency_id"): a.get("name") for a in load_json(agencies_file, []) if isinstance(a, dict)}
        if not Path(jobs_dir).is_dir():
            continue
        for d in sorted(Path(jobs_dir).iterdir()):
            meta = load_json(d / "job_meta.json", None)
            if not isinstance(meta, dict) or meta.get("status") != "done":
                continue
            video = Path(meta.get("output_path") or "")
            if not video.is_absolute():
                video = d / video.name if video.name else video
            if not video.is_file():
                cands = sorted(d.glob("*_final.mp4"))
                video = cands[-1] if cands else None
            if not video or not Path(video).is_file():
                continue
            ref = str(meta.get("external_ref") or "")
            m = re.match(r"^T-(\d+)-", ref)
            cost = meta.get("cost_actual")
            out.append({
                "job_id": d.name, "instance": label,
                "agency": names.get(meta.get("agency_id")) or meta.get("agency_name") or "Senza agenzia",
                "listing_ref": m.group(1) if m else (ref or None),
                "property_name": meta.get("property_name") or "",
                "source": meta.get("source") or meta.get("partner_id") or "",
                "created_at": meta.get("created_at") or "",
                "cost_eur": cost.get("grand_total_eur") if isinstance(cost, dict) else None,
                "upscale_images": meta.get("upscale_images"),
                "src_video": str(video),
            })
    return out


def target_path(out_dir: Path, e: dict) -> Path:
    return out_dir / slug(e["agency"]) / f"{e['job_id']}_{slug(e['property_name'])[:50]}.mp4"


def write_html(out_dir: Path, index: dict):
    rows = {}
    for jid, e in sorted(index.items(), key=lambda kv: (slug(kv[1]["agency"]), kv[1].get("created_at", ""))):
        rows.setdefault(e["agency"], []).append((jid, e))
    parts = ["<!doctype html><meta charset=utf-8><title>Libreria video</title><body style='font-family:sans-serif'><h1>Libreria video</h1>"]
    for agency, items in rows.items():
        parts.append(f"<h2>{html.escape(agency)} ({len(items)})</h2><table border=1 cellpadding=4><tr><th>job</th><th>annuncio</th><th>immobile</th><th>istanza</th><th>data</th><th>costo EUR</th><th>upscale</th><th>riutilizzabile</th><th>nota</th></tr>")
        for jid, e in items:
            rv = e.get("review", {})
            link = html.escape(e["file"])
            parts.append(f"<tr><td><a href='{link}'>{jid}</a></td><td>{html.escape(str(e.get('listing_ref') or ''))}</td><td>{html.escape(e['property_name'])}</td>"
                         f"<td>{e['instance']}</td><td>{html.escape(e.get('created_at','')[:16])}</td><td>{e.get('cost_eur') if e.get('cost_eur') is not None else ''}</td>"
                         f"<td>{e.get('upscale_images')}</td><td>{html.escape(str(rv.get('reusable')))}</td><td>{html.escape(rv.get('note',''))}</td></tr>")
        parts.append("</table>")
    (out_dir / "index.html").write_text("".join(parts), encoding="utf-8")


def run_copy(entries, out_dir: Path, do_copy: bool):
    index = load_json(out_dir / "index.json", {})
    new = 0
    for e in entries:
        tgt = target_path(out_dir, e)
        rec = index.get(e["job_id"], {})
        review = rec.get("review") or {"status": "to_review", "reusable": None, "note": ""}
        if not tgt.exists():
            new += 1
            if not do_copy:
                print(f"  would copy: {e['job_id']} [{e['instance']}] {e['agency']} / {e['property_name']} -> {tgt}")
                continue
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(e["src_video"], tgt)
        if do_copy:
            card = {k: v for k, v in e.items() if k != "src_video"}
            card.update({"file": str(tgt.relative_to(out_dir)), "review": review, "size_mb": round(tgt.stat().st_size / 1e6, 1)})
            index[e["job_id"]] = card
            (tgt.with_suffix(".json")).write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    if do_copy:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        write_html(out_dir, index)
    return new, index


def mark(out_dir: Path, job_id: str, reusable: str, note: str):
    index = load_json(out_dir / "index.json", {})
    if job_id not in index:
        raise SystemExit(f"job {job_id} is not in the library index (run --copy first)")
    index[job_id].setdefault("review", {}).update({"status": "reviewed", "reusable": reusable == "yes", "note": note or index[job_id]["review"].get("note", "")})
    (out_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / index[job_id]["file"]).with_suffix(".json").write_text(json.dumps(index[job_id], indent=2, ensure_ascii=False), encoding="utf-8")
    write_html(out_dir, index)


def publish(out_dir: Path, job_id: str, scratch: Path = SCRATCH, public: str = PUBLIC) -> str:
    index = load_json(out_dir / "index.json", {})
    if job_id not in index:
        raise SystemExit(f"job {job_id} is not in the library index (run --copy first)")
    name = f"lib_{job_id}_{secrets.token_urlsafe(9).replace('-', 'x').replace('_', 'y')}.mp4"
    scratch.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out_dir / index[job_id]["file"], scratch / name)
    return public + name


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--copy", action="store_true")
    ap.add_argument("--mark"); ap.add_argument("--reusable", choices=["yes", "no"]); ap.add_argument("--note", default="")
    ap.add_argument("--publish")
    a = ap.parse_args(argv)
    out_dir = Path(a.out)
    if a.mark:
        if not a.reusable:
            raise SystemExit("--mark needs --reusable yes|no")
        mark(out_dir, a.mark, a.reusable, a.note); print("marked", a.mark); return 0
    if a.publish:
        print(publish(out_dir, a.publish)); return 0
    entries = collect(SOURCES)
    new, index = run_copy(entries, out_dir, a.copy)
    by_agency = {}
    for e in entries:
        by_agency[e["agency"]] = by_agency.get(e["agency"], 0) + 1
    print(f"finished videos found: {len(entries)} | new for the library: {new} | {'COPIED' if a.copy else 'dry run, nothing written'}")
    for ag, n in sorted(by_agency.items()):
        print(f"  {ag}: {n}")
    if a.copy:
        print(f"library: {out_dir}  (index.json, index.html)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
