import listing_scraper as ls
fails = 0
def check(n, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + n); fails += 0 if ok else 1
raw = '```json\n[\n  "Edificio con accesso da strada privata",\n  "Soggiorno con angolo cottura",\n  "Soggiorno con angolo cottura e accesso esterno",\n  "Camera da letto con armadio",\n  "Camera da letto con armadio",\n  "Bagno con vasca"\n]\n```'
f = ls.parse_scene_facts(raw, 6)
check("R1 the real de122695 reply is usable now", f is not None)
check("R2 room words are kept in a fact", f and f[1] == "Soggiorno con angolo cottura" and f[5] == "Bagno con vasca")
check("R3 a kind of place (strada) is still blanked", f and f[0] == "")
check("R4 a material is still banned", ls.parse_scene_facts('["Cucina con pavimento in legno","","","","",""]', 6) is None)
check("R5 a deduction stem is still banned", ls.parse_scene_facts('["Cucina ideale per cenare","","","","",""]', 6) is None)
print("FAILS:", fails)
