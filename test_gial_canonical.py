import os, sys
sys.path.insert(0, os.getcwd())
import gial_population as gp
h = '<link rel="canonical" href="https://relinx.it/it/immobili/a/appartamento-affitto-60-mq-1212/"><meta property="og:url" content="https://relinx.it/it/agenzia/Gial/immobili/1212/">'
ok = gp.canonical_of(h).endswith("-1212/") and gp.kind_of(gp.canonical_of(h)) == "appartamento"
print("PASS" if ok else "FAIL", "C1 il link canonical vince su og:url della pagina agenzia")
raise SystemExit(0 if ok else 1)
