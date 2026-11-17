"""test_agency_text.py - the agency's own presentation is dropped from partner descriptions (2026-11-16, real jobs 748be538 / 12940f6f)."""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as ls
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " -- " + str(info)))
    fails += 0 if c else 1

AG = ("GIAL è un' agenzia con una esperienza consolidata, si occupa dal 1974 di compravendite e locazioni immobiliari. L'intero gruppo opera ogni giorno con lo sguardo rivolto al futuro e alle crescenti esigenze del mercato. "
      "L'evoluzione del mercato immobiliare e una esigente aspettativa della clientela spingono inoltre Gial Immobili a porre quotidianamente un attenzione particolare al tema della formazione al fine di garantire un adeguata competenza ai professionisti del gruppo.")
MARINO = ("MARINO, località Cava dei Selci, proponiamo in vendita un appartamento posto al primo piano composto da ingresso, soggiorno con angolo cottura, due camere matrimoniali, cameretta, bagno e balcone. "
          "L'immobile si presenta in buone condizioni manutentive, ha doppia esposizione e si trova nelle immediate vicinanze dei principali servizi e e delle fermate dei mezzi pubblici, tutte raggiungibili a piedi. ") + AG
c, rem = ls.strip_agency_text(MARINO)
check("A1 the agency paragraph is gone", "1974" not in c and "gruppo" not in c and "formazione" not in c and "clientela" not in c, c)
check("A2 every property sentence is kept (rooms, condition, services nearby)", "due camere matrimoniali" in c and "doppia esposizione" in c and "fermate dei mezzi pubblici" in c, c)
check("A3 the 3 agency sentences are reported as removed", len(rem) == 3, rem)
ARICCIA = ("Località Cecchina, in via delle More, proponiamo in vendita una villa unifamiliare, ideale per chi è alla ricerca di una proprietà indipendente. La villa si sviluppa su più livelli: Piano terra: ingresso, salone, cucina abitabile, bagno e balcone abitabile. "
           "Completa la proprietà un ampio giardino con piazzale. Grazie alla disposizione su più livelli, la villa può essere interessante anche per famiglie numerose.\n\n") + AG + "\n\nCaratteristiche: balcone, terrazzo, giardino"
c2, rem2 = ls.strip_agency_text(ARICCIA)
check("A4 villa: property text and the features line kept, agency gone", "ampio giardino" in c2 and "Caratteristiche: balcone, terrazzo, giardino" in c2, c2)
check("A5 villa: agency gone", "1974" not in c2 and "professionisti" not in c2, c2)
t = "Appartamento luminoso al terzo piano, edificio costruito dal 1974, con doppio affaccio e cantina. Il quartiere è tranquillo e ben servito."
c3, rem3 = ls.strip_agency_text(t)
check("A6 'dal 1974' about the building is NOT touched", c3 == t and rem3 == [], c3)
c4, rem4 = ls.strip_agency_text("Per informazioni contattaci in agenzia. Il nostro team vi aspetta.")
check("A7 only agency talk -> fail-safe: original returned, nothing removed", c4.startswith("Per informazioni") and rem4 == [], (c4, rem4))
check("A8 empty / None never raises", ls.strip_agency_text("") == ("", []) and ls.strip_agency_text(None)[1] == [])
os.environ["PVS_STRIP_AGENCY_TEXT"] = "0"
c5, rem5 = ls.strip_agency_text(MARINO)
check("A9 PVS_STRIP_AGENCY_TEXT=0 switches it off", c5 == MARINO and rem5 == [])
os.environ.pop("PVS_STRIP_AGENCY_TEXT")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_server.py")).read()
check("A10 the partner intake uses it ONCE and keeps the removed sentences on the job", src.count("scraper.strip_agency_text(payload.description)") == 1 and '"agency_text_removed": agency_text_removed' in src)
print("FAILS: %d" % fails)
sys.exit(1 if fails else 0)
