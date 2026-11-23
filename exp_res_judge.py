"""exp_res_judge.py - the production clip judge (clip_standard.evaluate) on the 20 clips of an exp_res_compare run. 2026-11-20. EXPERIMENT TOOL.
  python3 exp_res_judge.py RUN_ID            without --go: counts the clips, spends nothing
  python3 exp_res_judge.py RUN_ID --go       judges every generated clip (a few cents each), writes judge_RUN_ID.json, prints per scene: verdicts at 360p vs 1080p
  python3 exp_res_judge.py RUN_ID LABELS.json   FREE (needs the file written by --go): judge vs Michele's labels, code by code
Needs PVS_JOBS_DIR / PVS_VOLUME_SCRATCH like exp_res_compare.py. Never touches a job."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import exp_res_compare as x


def table(rows):
    per = {}
    for r in rows:
        d = per.setdefault((r["job"], r["scene"]), {"360p": [], "1080p": []})
        d[r["res"]].append(r.get("standard") or "n/a")
    return per


def show(rows):
    print(f"{'scena':<16}{'360p':<30}{'1080p':<30}")
    for (job, i), d in sorted(table(rows).items()):
        print(f"{job} idx {i:<4}  ".ljust(16) + (" ".join(d["360p"])).ljust(30) + " ".join(d["1080p"]))


def main(argv, evaluate=None):
    run_id = argv[1]
    key = [r for r in json.loads((x.OUT / f"key_{run_id}.json").read_text()) if r.get("ok")]
    out = x.OUT / f"judge_{run_id}.json"
    if len(argv) > 2 and argv[2].endswith(".json"):
        lab = json.loads(Path(argv[2]).read_text())
        labels = {c: k for k, v in lab.items() for c in v}
        rows = json.loads(out.read_text())
        print("codice  giudice Claude        tuo giudizio   scena            risoluzione")
        agree = 0
        for r in rows:
            mine = labels.get(r["code"], "?")
            j = r.get("standard") or "n/a"
            agree += (j == "reject") == (mine in ("bad", "part"))
            print(f"{r['code']}     {j:<20}  {mine:<12}   {r['job']}:{r['scene']:<4}   {r['res']}")
        print(f"accordo sul 'difettoso o no': {agree} su {len(rows)}")
        return 0
    print(f"{len(key)} clip da giudicare (costo: pochi centesimi ciascuno).")
    if "--go" not in argv:
        print("Nulla fatto (manca --go).")
        return 0
    if evaluate is None:
        from dotenv import load_dotenv
        load_dotenv(x.ev.HERE / ".env")
        import clip_standard as cs
        evaluate = cs.evaluate

    def one(r):
        u = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cost_eur": 0.0}
        e = evaluate(r["clip"], usage_out=u)
        return {k: r[k] for k in ("code", "job", "scene", "res")} | {"standard": e.get("standard_verdict"), "reasons": e.get("reasons"),
                "new_max": (e.get("geo") or {}).get("new_max"), "cost_eur": u.get("cost_eur"), "error": e.get("error")}
    with ThreadPoolExecutor(max_workers=3) as ex:
        rows = list(ex.map(one, key))
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"costo misurato: {sum(r.get('cost_eur') or 0 for r in rows):.2f} EUR per {len(rows)} clip")
    show(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
