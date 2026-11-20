import os, re, sys
import scene_script as ss
ok = True
def chk(n, c):
    global ok; print(("PASS" if c else "FAIL"), n); ok &= bool(c)
DESC = "Attico al terzo piano a Albano Laziale, soggiorno, cucina a vista, camera matrimoniale, bagno."
def probs(sentence, agency, flag):
    os.environ["PVS_FACT_MASK_AGENCY"] = flag
    d = ss._norm(DESC)
    return ss._fact_problems(sentence, "t", ss._norm(sentence), d, ss._number_tokens(DESC), set(), agency)
S = "Casa Nuova presenta in vendita un attico ad Albano Laziale."
chk("FM1 switch OFF (default): agency 'Casa Nuova' is flagged as before", any("nuov" in p for p in probs(S, "CASA NUOVA", "0")))
chk("FM2 switch unset behaves as OFF", (os.environ.pop("PVS_FACT_MASK_AGENCY", None), any("nuov" in p for p in ss._fact_problems(S, "t", ss._norm(S), ss._norm(DESC), set(), set(), "CASA NUOVA")))[1])
chk("FM3 switch ON: the agency name is not a claim, no problem", probs(S, "CASA NUOVA", "1") == [])
chk("FM4 switch ON: a REAL claim in the sentence is still caught", any("nuov" in p for p in probs("Casa Nuova presenta un attico di nuova costruzione.", "CASA NUOVA", "1")))
chk("FM5 switch ON: name with ampersand and accents", probs("Engel & Völkers Roma presenta un attico ad Albano Laziale.", "Engel & Völkers Roma", "1") == [])
chk("FM6 switch ON: 'Mare Blu Immobiliare' masked, 'con vista sul mare' in the same sentence still caught",
    probs("Mare Blu Immobiliare presenta un attico.", "MARE BLU IMMOBILIARE", "1") == []
    and any("mare" in p for p in probs("Mare Blu Immobiliare presenta un attico con vista sul mare.", "MARE BLU IMMOBILIARE", "1")))
chk("FM7 switch ON: a number inside the agency name is not checked against the listing", probs("Studio 2000 presenta un attico ad Albano Laziale.", "Studio 2000", "1") == [])
chk("FM8 switch ON, no agency name: unchanged", any("nuov" in p for p in probs(S, None, "1")))
os.environ["PVS_FACT_MASK_AGENCY"] = "1"
six = ["Casa Nuova presenta in vendita un attico ad Albano Laziale.", "L'attico e' al terzo piano con soggiorno.", "La cucina e' a vista sul soggiorno.", "Sono presenti una camera matrimoniale e un bagno.", "Il soggiorno e' al terzo piano.", "Contatta Casa Nuova per informazioni."]
v_on = [p for p in ss.validate(six, DESC, "CASA NUOVA", None, split_fn=None) if "nuov" in p]
os.environ["PVS_FACT_MASK_AGENCY"] = "0"
v_off = [p for p in ss.validate(six, DESC, "CASA NUOVA", None, split_fn=None) if "nuov" in p]
chk("FM9 validate(): ON -> no 'nuov' problem, OFF -> the two sentences naming the agency are flagged", v_on == [] and len(v_off) == 2)
src = open("scene_script.py", encoding="utf-8").read()
chk("FM10 both callers pass agency_name to the ONE shared check", src.count("price_numbers, agency_name))") == 2)
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
