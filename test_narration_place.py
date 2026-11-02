"""Narration prompt names the place and uses layout facts (2026-11-02, job de90cbaf). No network. Run: python3 test_narration_place.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_script as ss
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n); fails += 0 if c else 1
pr = ss.build_blocks_prompt("appartamento al piano terra, due bagni, corte esclusiva", "Appartamento Albano Laziale", "GIAL", ["salone", "cucina", "camera", "bagno", "corte", "esterno"],
                            ["living", "kitchen", "bedrooms", "bathrooms", "outdoor", "exterior"])
check("NP1 the address / title line is in the prompt", "Appartamento Albano Laziale" in pr)
check("NP2 the prompt demands the place in block 1 sentence 1", "PLACE" in pr and "never write only" in pr)
check("NP3 layout facts rule present", "LAYOUT FACTS" in pr and "due bagni" not in "LAYOUT FACTS")
check("NP4 floor of the whole property allowed, floor of a room not", "WHOLE property" in pr and "Do NOT tie a floor to a specific room" in pr)
bad = ["Lo spazio luminoso si trova vicino al centro.", "Gli ambienti mantengono proporzioni accoglienti e ben definite.", "La cucina riceve luce naturale dalle finestre.", "Ampie finestre con illuminazione diffusa."]
check("NP5 the four vague sentences of de90cbaf are rejected", all(ss.generic_problems([b]) for b in bad))
check("NP6 a concrete sentence passes", not ss.generic_problems(["Due bagni e una corte ad uso esclusivo al piano terra."]))
print("ALL PASS" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
