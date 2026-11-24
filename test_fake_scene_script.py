"""2026-11-24: the fake Claude answers the per-scene script prompt with a script that passes the REAL fact check (scene_script.validate),
so a fake draft is no longer refused by the auto start (C2/C10). Pure: no network, no server."""
import os, sys
os.environ["PVS_FACT_MASK_AGENCY"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_script as ss, fake_providers as fp
from narration import split_into_sentences
ok = True
def chk(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name); ok = ok and bool(cond)
DESCS = ["Appartamento in vendita di 100 mq con cucina abitabile e balcone, zona Cecchina.", "Villa in affitto con giardino e piscina.", "Immobile luminoso in zona centrale."]
for ag in ("Gial Immobiliare", "PVS DRYRUN", "Casa Nuova"):
    for d in DESCS:
        pr = ss.build_prompt(d, "Via Roma 1", ag, ["Soggiorno", "Cucina", "Camera", "Bagno", "Balcone", "Esterno"])
        out = ss.parse(fp._fake_claude_text(pr, 1024))
        chk("F1 %s | %s: six sentences, fact check passes" % (ag, d[:22]), out is not None and ss.validate(out, d, ag, None, split_fn=split_into_sentences) == [])
pr = ss.build_prompt(DESCS[2], "", "Gial Immobiliare", ["Soggiorno"] * 6)
chk("F2 a listing that says neither sale nor rent: the opening says neither", "vendita" not in fp._fake_scene_script(pr) and "affitto" not in fp._fake_scene_script(pr))
chk("F3 the closing invites to contact", "contatt" in fp._fake_scene_script(pr).lower())
print("RESULT:", "ALL PASS" if ok else "FAILURES"); sys.exit(0 if ok else 1)
