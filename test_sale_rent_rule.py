"""2026-10-27: the 'in vendita' / 'in affitto' rule of the opening sentence is ONE shared helper and only applies when the listing says it.
Villa job e1dccbd4: the listing said neither -> 'must say' and 'says but listing does not' were both unsatisfiable. No network."""
import os, sys, re
sys.path.insert(0, os.getcwd())
import scene_script as ss

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

NEITHER = ss._norm("Palazzo storico completamente ristrutturato con giardino alberato di mille metri quadri")
SALE = ss._norm("Appartamento in vendita sull'Aventino, ristrutturato")
RENT = ss._norm("Appartamento in affitto a Roma, arredato")
f = ss.sale_rent_problems
check("S1 listing says neither: an opening WITHOUT sale/rent is accepted", f("l agenzia presenta questo palazzo", NEITHER, "scene 1:") == [])
check("S2 listing says neither: saying 'in vendita' is still rejected", f("l agenzia presenta in vendita", NEITHER, "scene 1:") == ["scene 1: says 'in vendita' but the listing text does not"])
check("S3 listing says sale: an opening without it is rejected", f("l agenzia presenta questo", SALE, "scene 1:") == ["scene 1: must say 'in vendita' or 'in affitto'"])
check("S4 listing says sale: 'in vendita' accepted; 'in affitto' rejected", f("presenta in vendita", SALE, "x") == [] and len(f("presenta in affitto", SALE, "x")) == 1)
check("S5 listing says rent: 'in affitto' accepted, nothing said rejected", f("presenta in affitto", RENT, "x") == [] and len(f("presenta qualcosa", RENT, "x")) == 1)
check("S6 messages keep their old wording (scene 1: ... / the first sentence ...)", f("a", SALE, "the first sentence") == ["the first sentence must say 'in vendita' or 'in affitto'"])

# the three validators use the SAME helper (no copy of the rule left)
src = open("scene_script.py", encoding="utf-8").read()
check("S7 one implementation: validate() and validate_free_text() call sale_rent_problems, no inline copy", src.count("sale_rent_problems(") == 3 and 'for k in ("vendita", "vendesi"' not in src)
SENT = ["L'agenzia Rossi presenta questo palazzo storico all'Aventino.", "Si sviluppa su cinque livelli con mille metri quadri.", "La cucina ha elettrodomestici.", "Le camere hanno finestre.", "I bagni hanno finiture.", "Il giardino è alberato, contattate l'agenzia Rossi."]
p = ss.validate(SENT, "Palazzo storico completamente ristrutturato con giardino alberato di mille metri quadri, cinque livelli, cucina con elettrodomestici, camere con finestre, bagni con finiture", "Rossi", None)
check("S8 validate(): the same opening is not rejected for sale/rent when the listing says neither", not any("vendita" in x or "affitto" in x for x in p), p)

# prompts tell the model what to do when the listing says neither
check("S9 the three prompts mention the 'says neither' case", src.count("if the listing says neither sale nor rent, say neither") == 3)
print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
