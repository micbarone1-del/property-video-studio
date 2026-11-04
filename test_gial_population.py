"""test_gial_population.py - pure parts of gial_population.py (no network)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gial_population as gp
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n)
    fails += 0 if c else 1
html = '<a href="/it/agenzia/Gial/immobili/1285/">x</a><a href="/it/agenzia/Gial/immobili/1337/">y</a><a href="/it/agenzia/Gial/immobili/1285/">dup</a><a href="/it/agenzia/Gial/">no</a>'
check("G1 ids from the agency page, no duplicates, in order", gp.ids_from_agency_page(html) == ["1285", "1337"])
check("G2 canonical from og:url", gp.canonical_of('<meta property="og:url" content="https://relinx.it/it/immobili/a/appartamento-vendita-65-mq-3-locali-1286/">').endswith("1286/"))
check("G3 kind of listing from the slug", gp.kind_of("https://relinx.it/it/immobili/a/appartamento-vendita-65-mq-3-locali-1286/") == "appartamento" and gp.kind_of("https://relinx.it/it/immobili/a/villa-vendita-1-mq-1337/") == "villa" and gp.kind_of("https://relinx.it/it/immobili/a/attico-vendita-130-mq-3-locali-1030/") == "attico" and gp.kind_of("https://x/negozio-affitto-1/") == "negozio")
log = """[FAIL] 1286 trilocale (b6419df5) mode=None claude=EUR None
    FAIL C1  status is 'failed' or no scenes: Annuncio non idoneo al video standard: 3 foto utilizzabili e 3 tipi di ambiente
[FAIL] 1260 trilocale (e86161f5) mode=None claude=EUR None
    FAIL C1  status is 'failed' or no scenes: Annuncio non idoneo: le stanze risultano vuote e le foto non hanno etichette
[PASS] 1299 bilocale (aaaaaaaa) mode=blocks claude=EUR 0.2
[FAIL] 1248 (-) mode=None claude=EUR None
    FAIL P0  ReadTimeout(ReadTimeoutError("x"))
"""
r = gp.parse_log(log)
check("G4 passed drafts are taken with their job", r["passed"] == [("1299 bilocale", "aaaaaaaa")])
check("G5 failures are grouped by reason", [c for _, c, _ in r["failed"]] == ["poche foto/ambienti utilizzabili", "stanze vuote senza etichette", "timeout del sito"])
sys.exit(1 if fails else 0)
