"""test_spoken_name.py - agency names reach the narration prompt in normal capitals (2026-11-13)."""
import sys
import scene_script as ss
fails = []
def check(n, ok):
    print(("PASS " if ok else "FAIL ") + n)
    if not ok: fails.append(n)
check("SN1 GIAL IMMOBILIARE -> Gial Immobiliare", ss.spoken_name("GIAL IMMOBILIARE") == "Gial Immobiliare")
check("SN2 THRINAKIE GROUP -> Thrinakie Group", ss.spoken_name("THRINAKIE GROUP") == "Thrinakie Group")
check("SN3 mixed case is left alone", ss.spoken_name("Engel & Völkers Roma") == "Engel & Völkers Roma")
check("SN4 None and empty are unchanged", ss.spoken_name(None) is None and ss.spoken_name("") == "")
check("SN5 a one-letter word is unchanged", ss.spoken_name("A CASA") == "A Casa")
labels = ["soggiorno"] * 6
for fn in (ss.build_prompt, ss.build_anchored_prompt):
    t = fn("Bel appartamento", "Roma", "BUILDINGCASE BOLOGNA IMMOBILIARE", labels)
    check("SN6 %s: capitals not in prompt, normal name is" % fn.__name__, "BUILDINGCASE" not in t and "Buildingcase Bologna Immobiliare" in t)
t = ss.build_tighten_prompt(["Una frase molto lunga di prova per la scena uno del video"], [(0, 2.0)], "x", "ETICASI")
check("SN7 tighten prompt has no capitals name", "ETICASI" not in t)
check("SN8 validation still finds the agency in a sentence written in normal capitals",
      not [p for p in ss.validate_free_text("Gial Immobiliare presenta in vendita una casa. Contatta Gial Immobiliare.", [], "casa in vendita", "GIAL IMMOBILIARE") if "name the agency" in p])
sys.exit(1 if fails else 0)
