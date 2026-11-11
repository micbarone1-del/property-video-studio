"""gial_consolidate.py -- puts every GIAL job under the ONE production GIAL agency, marks it "keep" (never cleaned automatically) and brings the test
instance's GIAL jobs into the production app (2026-11-02, Michele: "inserisci i job GIAL come agenzia GIAL cosi non li cancelliamo e li ritroviamo").

NOTHING IS EVER DELETED OR OVERWRITTEN: jobs are COPIED (shutil.copytree, skipped if the destination exists); every job_meta.json / properties.json this
script changes is first saved next to itself as <name>.bak_p28. Without --apply it only prints what it WOULD do.

  python3 gial_consolidate.py                         plan for the three scopes (dry run)
  python3 gial_consolidate.py --scope done            dry run for one scope
  python3 gial_consolidate.py --scope useful --apply  do it.  Scopes: done = finished videos | useful = done + drafts that passed the check | all = everything
Run on the server from /var/www/property-video-studio with the venv; production data = the default folder, test data = /var/www/pvs_test_state/data.
After --apply restart the production AND the test instance (they load jobs from disk at start); the script refuses to run while a job is running.
"""
import argparse
import json
import os
import re
import shutil
import datetime as _dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCOPES = {"done": ("done",), "useful": ("done", "draft"), "all": None}
GIAL = "gial"


def _read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _write_atomic(p, data, backup_suffix=".bak_p28"):
    p = Path(p)
    if p.exists() and not Path(str(p) + backup_suffix).exists():
        shutil.copy2(p, str(p) + backup_suffix)
    tmp = Path(str(p) + ".tmp_p28")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def listing_ref(meta, job_id):
    """The Relinx listing number (T-<id>-...) from external_ref or the message; else the first 8 chars of the job id."""
    for txt in (meta.get("external_ref"), meta.get("message")):
        m = re.search(r"T-(\d{3,5})-", str(txt or ""))
        if m:
            return m.group(1)
    return job_id[:8]


def prod_gial_agency(agencies):
    """The production GIAL agency: the one with a logo if several, else the first. None if there is none."""
    g = [a for a in agencies if GIAL in str(a.get("name", "")).lower()]
    g.sort(key=lambda a: (not a.get("logo_path"), ))
    return g[0] if g else None


def scan(jobs_dir, gial_agency_ids):
    out = []
    for p in sorted(Path(jobs_dir).glob("*/job_meta.json")):
        try:
            m = _read(p)
        except Exception:
            continue
        if m.get("agency_id") in gial_agency_ids:
            out.append((p.parent.name, m))
    return out


def in_scope(meta, scope):
    allowed = SCOPES[scope]
    return True if allowed is None else meta.get("status") in allowed


def busy(*jobs_dirs):
    found = []
    for d in jobs_dirs:
        for p in Path(d).glob("*/job_meta.json"):
            try:
                if _read(p).get("status") in ("running", "queued"):
                    found.append((str(d), p.parent.name))
            except Exception:
                pass
    return found


def run(prod_jobs, test_jobs, prod_agencies, test_agencies, scope, apply, create_property, keep_test=True, out=print, only=None):
    prod_g = prod_gial_agency(prod_agencies)
    if not prod_g:
        out("ERRORE: nessuna agenzia GIAL nella produzione"); return 2
    test_ids = {a["agency_id"] for a in test_agencies if GIAL in str(a.get("name", "")).lower()}
    prod_ids = {a["agency_id"] for a in prod_agencies if GIAL in str(a.get("name", "")).lower()}
    out(f"Agenzia GIAL di produzione: {prod_g['agency_id']} ({prod_g['name']}, logo: {bool(prod_g.get('logo_path'))})")
    in_prod = scan(prod_jobs, prod_ids | test_ids)
    in_test = scan(test_jobs, test_ids | prod_ids)
    prod_names = {n for n, _ in in_prod}
    todo_copy = [(n, m) for n, m in in_test if n not in prod_names and in_scope(m, scope) and (only is None or n in only)]
    if only is not None:      # 2026-11-02: --only copies exactly the named test jobs and touches nothing else in production
        in_prod = [(n, m) for n, m in in_prod if n in only]
    todo_update = [(n, m) for n, m in in_prod if m.get("agency_id") != prod_g["agency_id"] or not m.get("keep")]
    out(f"Ambito '{scope}': copio in produzione {len(todo_copy)} job dal test; aggiorno agenzia/keep di {len(todo_update)} job gia' in produzione; "
        f"marco keep su {len([1 for n, m in in_test if not m.get('keep')]) if keep_test else 0} originali del test")
    by = {}
    for n, m in todo_copy:
        by[m.get("status")] = by.get(m.get("status"), 0) + 1
    out("  da copiare per stato:", by)
    for n, m in todo_copy[:60]:
        out(f"    COPIA {n} | {m.get('status')} | {m.get('property_name')} | annuncio {listing_ref(m, n)}")
    for n, m in todo_update:
        out(f"    AGGIORNA (gia' in produzione) {n} | agenzia {m.get('agency_id')} -> {prod_g['agency_id']} | keep -> True | {m.get('status')}")
    if not apply:
        out("DRY RUN: non e' stato scritto niente. Aggiungi --apply per eseguire."); return 0
    b = busy(prod_jobs, test_jobs)
    if b:
        out("STOP: job in corso, non faccio niente:", b); return 3
    props_file = None
    for n, m in todo_copy:
        dst = Path(prod_jobs) / n
        if dst.exists():
            out(f"  salto {n}: esiste gia' in produzione"); continue
        shutil.copytree(Path(test_jobs) / n, dst)
        mp = dst / "job_meta.json"
        txt = mp.read_text(encoding="utf-8").replace(str(test_jobs), str(prod_jobs))
        mp.write_text(txt, encoding="utf-8")
        out(f"  copiato {n}")
    names = [n for n, _ in todo_copy if (Path(prod_jobs) / n).exists()] + [n for n, _ in todo_update]
    for n in dict.fromkeys(names):
        mp = Path(prod_jobs) / n / "job_meta.json"
        m = _read(mp)
        prop = create_property(f"{m.get('property_name') or 'Annuncio'} · {listing_ref(m, n)}", prod_g["agency_id"])
        m["agency_id"] = prod_g["agency_id"]
        m["property_id"] = prop["property_id"]
        m["keep"] = True
        m["gial_consolidated"] = _dt.date.today().isoformat()
        if n in {c for c, _ in todo_copy} and not m.get("luma_resolution"):    # 2026-11-11: copies carry the MEASURED resolution (360p is never confused with 1080p)
            import listing_registry as _lr
            m["luma_resolution"] = _lr.resolution_of(Path(prod_jobs) / n, m)[0]
        _write_atomic(mp, m)
    if keep_test:
        for n, m in in_test:
            if not m.get("keep"):
                mp = Path(test_jobs) / n / "job_meta.json"
                mm = _read(mp); mm["keep"] = True
                _write_atomic(mp, mm)
    out("FATTO. Riavvia produzione e test (./start.sh e ./start_test.sh).")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=list(SCOPES))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default="", help="comma list of test job ids: copy ONLY these (with --scope all)")
    ap.add_argument("--prod-jobs", default="/var/www/property-video-studio/jobs")
    ap.add_argument("--test-jobs", default="/var/www/pvs_test_jobs")
    ap.add_argument("--test-data", default="/var/www/pvs_test_state/data")
    a = ap.parse_args()
    import cost_model
    prod_agencies = cost_model.list_agencies()
    test_agencies = _read(Path(a.test_data) / "agencies.json")
    if a.apply and not a.scope:
        print("--apply richiede --scope"); return 2
    if a.apply:
        pf = cost_model.PROPERTIES_FILE
        if pf.exists() and not Path(str(pf) + ".bak_p28").exists():
            shutil.copy2(pf, str(pf) + ".bak_p28")
    only = {x.strip() for x in a.only.split(',') if x.strip()} or None
    rc = 0
    for sc in ([a.scope] if a.scope else list(SCOPES)):
        print(f"\n===== AMBITO {sc} =====")
        rc = run(Path(a.prod_jobs), Path(a.test_jobs), prod_agencies, test_agencies, sc, a.apply, cost_model.create_property,
                 keep_test=not only, only=only)
    return rc


if __name__ == "__main__":
    sys.exit(main())
