import listing_scraper as ls
f = ls.drop_unlisted_facts
T = []
T.append(("O1 balcone non nel testo: scartato", f(["camera con balcone"], "Bilocale ristrutturato") == [""]))
T.append(("O2 balcone nel testo: tenuto", f(["camera con balcone"], "Bilocale con balcone") == ["camera con balcone"]))
T.append(("O3 terrazzo/terrazza/terrazzino", f(["terrazza visibile"], "due terrazzini abitabili") == ["terrazza visibile"]))
T.append(("O4 giardino non nel testo: scartato", f(["giardino con alberi"], "Villino a schiera") == [""]))
T.append(("O5 fatto senza spazi esterni e testo vuoto", f(["cucina con zona pranzo"], None) == ["cucina con zona pranzo"]))
T.append(("O6 isola non nel testo: scartata", f(["cucina con isola"], "Bilocale ristrutturato") == [""]))
T.append(("O7 isola nel testo: tenuta", f(["cucina con isola"], "cucina con isola") == ["cucina con isola"]))
bad = 0
for n, ok in T:
    print("PASS" if ok else "FAIL", n)
    bad += (not ok)
raise SystemExit(bad)
