"""Read-only evaluation: Claude room recognition vs the saved (Florence) result, on photos of existing jobs.
Usage (from the repo root): python3 eval_rooms.py <job_id> [<job_id> ...]
Never writes under jobs/. Writes a TSV to /var/www/pvs_eval/rooms.tsv (or $PVS_EVAL_DIR)."""
import os, sys, json, glob
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
JOBS = os.environ.get("PVS_JOBS_DIR") or os.path.join(HERE, "jobs")
OUT = os.environ.get("PVS_EVAL_DIR", "/var/www/pvs_eval")

def main(job_ids):
    import vision_analysis as va
    os.makedirs(OUT, exist_ok=True)
    default = {"v7_space_type": "large", "suggested_movement": "walk_in_explore", "depth": "medium",
               "recommended_camera": "gentle_arc", "confidence": 0.0, "description": "", "room": None, "source": None, "error": None}
    rows, diff = [], []
    print("job      sc  categoria   salvato(Florence)  Florence_ora  Claude(room/size->spazio)")
    for jid in job_ids:
        mp = os.path.join(JOBS, jid, "job_meta.json")
        if not os.path.exists(mp):
            print(f"{jid}  job_meta.json non trovato"); continue
        meta = json.load(open(mp, encoding="utf-8"))
        for i, sc in enumerate(meta.get("scenes_config", [])):
            files = sorted(glob.glob(os.path.join(JOBS, jid, "images", f"scene_{i:03d}.*")))
            if not files:
                print(f"{jid}  {i:<3} immagine mancante"); continue
            c = va._classify_room_claude(files[0])
            f = va._analyse_input_florence(files[0], dict(default))
            claude_space = va._SPACE_MAP.get(va._space_from_room(c["room"], c["size"])) if c else "ERRORE"
            claude_txt = f'{c["room"]}/{c["size"]}->{claude_space}' if c else "ERRORE"
            saved = sc.get("space_type", "?")
            flor = f.get("v7_space_type") or "ERRORE"
            mark = "" if claude_space == flor else "  <-- DIVERSI"
            print(f'{jid} {i:<3} {sc.get("category","?"):<11} {saved:<18} {flor:<13} {claude_txt}{mark}', flush=True)
            rows.append([jid, i, sc.get("category", "?"), saved, flor, c["room"] if c else "", c["size"] if c else "", claude_space,
                         c["description"] if c else ""])
            if claude_space != flor:
                diff.append((jid, i))
    with open(os.path.join(OUT, "rooms.tsv"), "w", encoding="utf-8") as fh:
        fh.write("job\tscena\tcategoria\tsalvato\tflorence\tclaude_room\tclaude_size\tclaude_spazio\tdescrizione\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    print(f"\nscene valutate: {len(rows)}  | diverse tra Florence e Claude: {len(diff)}")
    print("da controllare a occhio nella UI:", ", ".join(f"{j}#{i}" for j, i in diff) or "nessuna")
    return rows

if __name__ == "__main__":
    main(sys.argv[1:])
