import scene_script as ss, italian_check as ic
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)
D = "Appartamento ben distribuito e accogliente con terrazzo."
chk("T1 filler stated by the listing is kept", ss.generic_problems(["Ambienti ben distribuiti."], D) == [])
chk("T2 one filler not in the listing is tolerated", ss.generic_problems(["Ambienti funzionali e luminosi."], "", ss.GENERIC_MIN_HITS) == [])
chk("T3 two fillers not in the listing are rejected", len(ss.generic_problems(["Ambienti funzionali. Spazi interessanti."], "", ss.GENERIC_MIN_HITS)) >= 1)
src = open("scene_script.py").read()
chk("T4 the live block validator and prompt have no max-rooms rule", "total_named > MAX_ROOMS_NAMED" not in src and "Name AT MOST {MAX_ROOMS_NAMED}" not in src)
chk("T5 proofreader told that numbers in one word are correct", "duemilaventi" in ic.SUSPECT_PROMPT)
print("FAILS", F)
