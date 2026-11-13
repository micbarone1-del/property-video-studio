"""narration_battery.py -- LIVE check of the narration rules on real listings (Claude calls only: no video, no voice).
  python3 narration_battery.py LIST.txt | LISTING_ID ...     one PASS/FAIL line per rule, then the full text for Michele to read."""
import os, re, sys, json, time, subprocess
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, ".env"))
os.environ.setdefault("PVS_NARRATION_MODEL", "claude-sonnet-5-5")
import listing_registry as lr
import listing_scraper as ls
import narration
import scene_script as ss
SECOND = re.compile(r"\b(tu|ti|te|trovi|vedi|scopri|puoi|hai|sei|avrai|potrai|senti)\b", re.I)


def find(o, k):
    if isinstance(o, dict):
        if k in o:
            return o[k]
        for v in o.values():
            x = find(v, k)
            if x is not None:
                return x


def job_for(num):
    """The newest job of the listing (production or test) that still has its photos: (created_at, folder, meta) or None."""
    best = None
    for root in (lr.PROD_JOBS, lr.TEST_JOBS):
        for f in Path(root).glob("*/job_meta.json"):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if lr.listing_of(m, f.parent.name) != num or not m.get("scenes_config"):
                continue
            if not (f.parent / "images" / "scene_000.jpg").exists():
                continue
            key = str(m.get("created_at") or "")
            if not best or key > best[0]:
                best = (key, f.parent, m)
    return best


def checks(text, seq, desc):
    """-> (list of (rule, sentence number, what), sentences); None when the text is not one sentence per scene + the closing."""
    sents = narration.split_into_sentences(text)
    if len(sents) != len(seq) + 1:
        return None, sents
    nd = ss._norm(desc)
    out, named = [], 0
    for i, cat in enumerate(seq):
        s = sents[i]
        found = ss.named_rooms(s)
        named += len(found & {cat})
        wrong = sorted(w for w in found - {cat} if not (cat in found and ss._rooms_tied(nd, cat, w)))
        svc = [w for w in ss.service_spaces(s) if cat != "exterior" and not ss._service_tied(nd, cat, w)]
        ded = [st for st in ss._PROMO_STEMS if st in ss._norm(s) and st not in nd]
        for tag, bad in (("stanza su scena sbagliata", wrong), ("spazio di servizio", svc),
                         ("seconda persona", SECOND.findall(s)), ("deduzione", ded)):
            if bad:
                out.append((tag, i + 1, bad))
    return out, sents


def main(argv):
    items = []
    for a in argv[1:]:
        if a.endswith(".txt"):
            for ln in Path(a).read_text(encoding="utf-8").splitlines():
                if ln.strip() and not ln.startswith("#"):
                    items.append(lr.listing_of_url(ln.partition("|")[0].strip()))
        else:
            items.append(a)
    fails = 0
    for num in [i for i in items if i]:
        j = job_for(num)
        if not j:
            print("=== %s SALTATO: nessun job con le foto" % num, flush=True)
            continue
        _, jd, m = j
        seq = [s.get("category") for s in m["scenes_config"]]
        desc = find(m, "source_description") or ""
        srv = subprocess.Popen([sys.executable, "-m", "http.server", "38613", "--bind", "127.0.0.1", "--directory", str(jd / "images")],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        try:
            url = "http://127.0.0.1:38613/scene_%03d.jpg"
            photos = [{"url": url % i, "original_url": url % i} for i in range(len(seq))]
            r = ls.generate_narration_and_derive_scenes(desc, "", "", m.get("voice_id"), False, "GIAL IMMOBILIARE", None, seq, photos)
        finally:
            srv.terminate()
        text = r.get("narration_text") or ""
        res, sents = checks(text, seq, desc) if text else (None, [])
        print("=== %s job %s | modo %s | errore %s" % (num, jd.name, r.get("narration_mode"), r.get("error")), flush=True)
        if res is None:
            print("  NON VERIFICABILE: %d frasi per %d scene (serve il modo anchored)" % (len(sents), len(seq)))
        elif res:
            fails += len(res)
            for tag, n, bad in res:
                print("  FAIL %s (frase %s): %s" % (tag, n, bad))
        else:
            print("  PASS tutte le regole")
        print("  SCENE:", seq)
        print("  TESTO:", text, flush=True)
    print("TOTALE FAIL:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv) if len(sys.argv) > 1 else print(__doc__) or 2)
