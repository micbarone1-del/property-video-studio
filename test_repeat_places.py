import scene_script as ss, narration as nr
f = lambda t: ss.repeat_problems([t], nr.split_into_sentences, "GIAL IMMOBILIARE")
A = "GIAL IMMOBILIARE presenta in vendita una villa a Roma. Ha tre livelli. Il salone è ampio. La cucina è abitabile. Le camere sono quattro."
T = [("P1 stesso luogo in due frasi: segnalato", bool(f(A + " Una casa indipendente a Roma, contatta GIAL IMMOBILIARE."))),
     ("P2 luogo detto una volta: nessun problema", not f(A + " Contatta GIAL IMMOBILIARE.")),
     ("P3 nome agenzia ripetuto: nessun problema", not f("GIAL IMMOBILIARE presenta in vendita un bilocale. Contatta GIAL IMMOBILIARE.")),
     ("P4 stessa parola comune in due frasi: nessun problema", not f("GIAL IMMOBILIARE presenta un bilocale. Il balcone è grande. Anche l'altro balcone è grande.")),
     ("P5 via ripetuta: segnalata", bool(f("In vendita in Via Mazzini un bilocale. Si trova in Via Mazzini al primo piano.")))]
bad = 0
for n, ok in T:
    print("PASS" if ok else "FAIL", n); bad += (not ok)
raise SystemExit(bad)
