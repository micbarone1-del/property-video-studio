import scene_script as ss
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
chk("S1 interrato found", ss.service_spaces("Il piano interrato ospita la cantina") == {"interrato", "cantina"})
chk("S2 box doccia is not a service space", ss.service_spaces("Bagno con box doccia") == set())
chk("S3 deposito cauzionale is not one", ss.service_spaces("Deposito cauzionale richiesto") == set())
chk("S4 box auto found", ss.service_spaces("Comodo box auto di proprieta") == {"box auto"})
chk("S5 ROOM_KEYWORDS untouched", set(ss.ROOM_KEYWORDS) == {"living", "kitchen", "bedrooms", "bathrooms", "outdoor"})
chk("S6 listing tie: lavanderia next to bagno", ss._service_tied("bagno con lavanderia", "bathrooms", "lavanderia"))
chk("S7 no tie when far apart", not ss._service_tied("bagno luminoso. " + "x " * 60 + "cantina", "bathrooms", "cantina"))
src = open("scene_script.py").read()
chk("S8 validator wired, exterior exempt", 'service_spaces(sent) if cat != "exterior"' in src)
chk("S9 prompt has the rule and the no-tu rule", "WHAT A SENTENCE IS ABOUT" in src and "'trovi'" in src)
print("FAILS", F)
