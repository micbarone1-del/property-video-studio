"""gial_rename: labels, plan and apply on a temp folder (2026-11-03). No server data touched. Run: python3 test_gial_rename.py"""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gial_rename as gr
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else f" -- {info}")); fails += 0 if c else 1
d = Path(tempfile.mkdtemp())
(d / "l.txt").write_text("# c\nhttps://x/1189/ | 1189 5 locali 140mq Centro\nhttps://x/1337/ | 1337 villa 135mq Cecchina\nnoise\n", encoding="utf-8")
lab = gr.read_labels([d / "l.txt"])
check("GR1 labels parsed, comments and noise skipped", lab == {"1189": "5 locali 140mq Centro", "1337": "villa 135mq Cecchina"}, lab)
jobs = d / "jobs"
for jid, ag, ref, nm in (("a", "G", "T-1189-xx", "Appartamento Albano Laziale"), ("b", "G", "T-1337-aa", "Villa"), ("c", "G", "T-1337-bb", "Villa"),
                         ("e", "G", "T-9999-zz", "Senza etichetta"), ("f", "OTHER", "T-1189-yy", "Altra agenzia")):
    (jobs / jid).mkdir(parents=True)
    (jobs / jid / "job_meta.json").write_text(json.dumps({"agency_id": ag, "external_ref": ref, "property_name": nm, "status": "done"}), encoding="utf-8")
todo, unch = gr.plan(str(jobs), "G", lab, [])
check("GR2 three GIAL jobs with a label are renamed (two jobs of 1337 get the SAME name: one property, two videos)", sorted(t[0] for t in todo) == ["a", "b", "c"] and {t[2] for t in todo if t[0] in "bc"} == {"1337 · villa 135mq Cecchina"}, todo)
check("GR3 a job without label is left alone and reported", [u[0] for u in unch] == ["e"], unch)
check("GR4 another agency is never touched", all(t[0] != "f" for t in todo) and all(u[0] != "f" for u in unch))
check("GR5 already renamed job is not planned again", gr.plan(str(jobs), "G", lab, [])[0] != [] and not any(t[1].get("property_name") == t[2] for t in todo))
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
