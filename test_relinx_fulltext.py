import relinx_pilot_check as rp
D = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
LD = '<script type="application/ld+json">{"@graph":[{"identifier":"7","name":"X","description":"%s"}]}</script>' % D
U = "https://relinx.it/it/immobili/a/b-7/"
T = []
r = rp.parse_listing(LD + "<p>" + D + " mu nu xi. Altro &#x27;testo&#x27;</p>", U)["description"]
T.append(("L1 testo visibile piu' lungo: usato, entita' decodificate", r == D + " mu nu xi. Altro 'testo'"))
T.append(("L2 nessun testo piu' lungo: resta il JSON-LD", rp.parse_listing(LD + "<p>" + D + "</p>", U)["description"] == D))
T.append(("L3 testo visibile diverso: resta il JSON-LD", rp.parse_listing(LD + "<p>Altro testo molto piu' lungo e diverso dal JSON-LD</p>", U)["description"] == D))
bad = 0
for n, ok in T:
    print("PASS" if ok else "FAIL", n)
    bad += (not ok)
raise SystemExit(bad)
