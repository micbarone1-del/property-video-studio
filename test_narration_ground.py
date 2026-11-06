import scene_script as ss
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)
LISTING = "Luminoso attico con affaccio panoramico verso il mare, terzo piano senza ascensore, palazzo d'epoca."
FACTS = "\n\nWHAT THE PHOTOS PLAINLY SHOW (x):\nScene one: tetto a vista con travi di legno"
chk("G1 sea claim only in the listing text -> problem", len(ss.view_problems("L'attico affaccia verso il mare.", LISTING + FACTS)) == 1)
chk("G2 sea confirmed by the photo facts -> ok", ss.view_problems("L'attico affaccia verso il mare.", LISTING + FACTS.replace("tetto a vista", "vista sul mare")) == [])
chk("G3 no photo facts block at all -> sea still a problem", len(ss.view_problems("Vista sul mare.", LISTING)) == 1)
chk("G4 horizon invented -> problem", len(ss.view_problems("Domina la città verso l'orizzonte.", LISTING + FACTS)) == 1)
chk("G5 no view word -> no problem", ss.view_problems("Attico al terzo piano senza ascensore.", LISTING + FACTS) == [])
chk("G6 'colline' and 'lago' both reported", "colline" in ss.view_problems("Vista su colline e lago.", LISTING + FACTS)[0] and "lago" in ss.view_problems("Vista su colline e lago.", LISTING + FACTS)[0])
chk("G7 word boundary: 'immaginare' / 'amare' do not trigger", ss.view_problems("Da immaginare e da amare.", LISTING + FACTS) == [])
b = ["GIAL presenta un appartamento. Gli spazi sono ben organizzati su questo livello della casa.", "x y", "z"]
gp = ss.generic_problems(b)
chk("G8 'ben organizzat' / 'su questo livello' now generic filler", len(gp) == 1 and "ben organizzat" in gp[0] and "su questo livello" in gp[0])
chk("G9 'su due livelli' (real fact) is NOT filler", ss.generic_problems(["Appartamento su due livelli con terrazzo."]) == [])
chk("G10 'domina la città verso l'orizzonte' is filler", len(ss.generic_problems(["Domina la città verso l'orizzonte."])) == 1)
import inspect, re
chk("G11 view check wired in validate_free_text (all paths that use it)", "view_problems(text, description)" in inspect.getsource(ss.validate_free_text))
src = open("listing_scraper.py").read() if __import__("os").path.exists("listing_scraper.py") else open("../fresh3/listing_scraper.py").read()
chk("G12 marker equals the text the scraper puts before the photo facts", ss.PHOTO_FACTS_MARK in src)
chk("G13 survivors of the battery are filler now", len(ss.generic_problems(["Un angolo cottura funzionale e accogliente."])) == 1 and len(ss.generic_problems(["Il cucinotto e pratico e funzionale."])) == 1)
chk("G14 real facts stay allowed", ss.generic_problems(["Cucina a vista sul soggiorno, bagno con finestra, terrazzo di cento metri."]) == [])
print("FAILS", F)
