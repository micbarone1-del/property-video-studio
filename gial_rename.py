"""gial_rename.py -- gives the GIAL jobs and their history entries (properties) a readable name: "<listing number> · <short description>" (2026-11-03,
Michele: "job GIAL in produzione sotto GIAL in cronologia con nome proprieta aggiornato").

  python3 gial_rename.py            dry run: prints what it would rename, writes nothing
  python3 gial_rename.py --apply    does it (refuses while a job is running)

The short description comes from the label next to each URL ("URL | 1189 5 locali 140mq Centro") in relinx_listings*.txt / gial_*.txt / golden_batch*.txt; without a manual
label it is built from the URL's own words ("appartamento 70mq 3 locali Cecchina"). A listing whose URL is in none of those files keeps its current name (listed at the end). Only jobs of the production GIAL agency are touched. NOTHING IS DELETED: properties.json and every job_meta.json are
copied to <name>.bak_p39 before the first change. Run from /var/www/property-video-studio with the venv active.
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


URL_RE = re.compile(r"relinx\.it/it/immobili/([a-z0-9-]+)/([a-z0-9-]+?)-(\d{3,5})/?")


def slug_label(zone_seg: str, slug: str) -> str:
    """'appartamento-vendita-70-mq-3-locali' + 'albano-laziale-cecchina' -> 'appartamento 70mq 3 locali Cecchina' (2026-11-03: the URL itself says what the listing is)."""
    kind = slug.split("-vendita")[0].split("-affitto")[0].replace("-", " ").strip() or "annuncio"
    mq = re.search(r"-(\d+)-mq", slug)
    loc = re.search(r"-(\d+(?:-\d)?)-locali", slug)
    zone = zone_seg
    for pre in ("albano-laziale-", "castel-gandolfo-", "roma-"):
        if zone.startswith(pre):
            zone = zone[len(pre):]
    zone = zone.replace("-", " ").strip().title()
    parts = [kind]
    if mq: parts.append(f"{mq.group(1)}mq")
    if loc: parts.append(f"{loc.group(1).replace('-', ',')} locali")
    if zone: parts.append(zone)
    return " ".join(parts)


def read_labels(paths):
    """{listing number: short label}. A manual label ('URL | 1189 5 locali 140mq Centro') wins; otherwise the label is built from the URL's own words."""
    out, manual = {}, {}
    for p in paths:
        try:
            lines = Path(p).read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for ln in lines:
            if ln.strip().startswith("#") or "|" not in ln:
                continue
            left, right = ln.split("|", 1)
            m = re.match(r"\s*(\d{3,5})\s+(.+?)\s*$", right)
            if m:
                manual[m.group(1)] = m.group(2)
            u = URL_RE.search(left)
            if u and u.group(3) not in out:
                out[u.group(3)] = slug_label(u.group(1), u.group(2))
    out.update(manual)
    return out


def listing_ref(meta):
    for txt in (meta.get("external_ref"), meta.get("message")):
        m = re.search(r"T-(\d{3,5})-", str(txt or ""))
        if m:
            return m.group(1)
    return None


def new_name(ref, label):
    return f"{ref} · {label}"


def plan(jobs_dir, agency_id, labels, props):
    """[(job_id, meta, new_name)] for jobs with a known label whose name differs; [(job_id, ref, name)] for the ones left unchanged."""
    todo, unchanged = [], []
    for f in sorted(glob.glob(os.path.join(jobs_dir, "*", "job_meta.json"))):
        try:
            m = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        if m.get("agency_id") != agency_id:
            continue
        jid = os.path.basename(os.path.dirname(f))
        ref = listing_ref(m)
        if ref and ref in labels:
            nn = new_name(ref, labels[ref])
            if m.get("property_name") != nn:
                todo.append((jid, m, nn))
        else:
            unchanged.append((jid, ref, m.get("property_name")))
    return todo, unchanged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--jobs", default="/var/www/property-video-studio/jobs")
    ap.add_argument("--agency", default="")
    a = ap.parse_args()
    import cost_model
    ag = a.agency
    if not ag:
        gs = [x for x in cost_model.list_agencies() if "gial" in str(x.get("name", "")).lower()]
        gs.sort(key=lambda x: (not x.get("logo_path"),))
        if not gs:
            print("ERRORE: nessuna agenzia GIAL"); return 2
        ag = gs[0]["agency_id"]
    labels = read_labels(sorted(set(glob.glob(str(HERE / "relinx_listings*.txt")) + glob.glob(str(HERE / "gial_*.txt")) + glob.glob(str(HERE / "golden_batch*.txt")))))
    props = cost_model.list_properties()
    todo, unchanged = plan(a.jobs, ag, labels, props)
    print(f"Agenzia {ag}: {len(todo)} job da rinominare, {len(unchanged)} senza etichetta (nome invariato)")
    for jid, m, nn in todo:
        print(f"  {jid} | {m.get('property_name')!r} -> {nn!r}")
    for jid, ref, name in unchanged:
        print(f"  invariato {jid} | annuncio {ref} | {name!r}")
    if not a.apply:
        print("DRY RUN: non e' stato scritto niente. Aggiungi --apply."); return 0
    running = [os.path.basename(os.path.dirname(f)) for f in glob.glob(os.path.join(a.jobs, "*", "job_meta.json"))
               if json.loads(Path(f).read_text(encoding="utf-8")).get("status") in ("running", "queued")]
    if running:
        print("STOP: job in corso:", running); return 3
    pf = Path(cost_model.PROPERTIES_FILE)
    if pf.exists() and not Path(str(pf) + ".bak_p39").exists():
        shutil.copy2(pf, str(pf) + ".bak_p39")
    props = cost_model.list_properties()
    byid = {p["property_id"]: p for p in props}
    for jid, m, nn in todo:
        mp = Path(a.jobs) / jid / "job_meta.json"
        if not Path(str(mp) + ".bak_p39").exists():
            shutil.copy2(mp, str(mp) + ".bak_p39")
        m["property_name"] = nn
        tmp = Path(str(mp) + ".tmp_p39")
        tmp.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, mp)
        if m.get("property_id") in byid:
            byid[m["property_id"]]["name"] = nn
    cost_model._save(cost_model.PROPERTIES_FILE, props)
    print("FATTO. Riavvia la produzione (./start.sh): carica nomi e proprieta dal disco all'avvio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
