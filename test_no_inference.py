import scene_script as s, re
fails = 0
def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1
D = "Attico su due livelli di 130 mq con terrazzo."
def n(t, d=D): return len(s.validate_free_text(t, [], d, None, None, check_timing=False))
base = n("Attico su due livelli di 130 mq con terrazzo.")
check("I1 'permette di pranzare in casa' is rejected", n("La cucina permette di pranzare in casa.") > base)
check("I2 'ventilazione naturale' is rejected", n("Il bagno ha ventilazione naturale.") > base)
check("I3 'consente' and 'ideale' are rejected", n("Il soggiorno consente di ospitare, ideale per famiglie.") > base)
check("I4 the same word is allowed when the listing text uses it", n("Soggiorno ideale.", D + " Soggiorno ideale.") <= n("Soggiorno.", D + " Soggiorno ideale."))
p = s.build_blocks_prompt("x", "Roma", "Agenzia", ["a"] * 6, ["cucina"] * 6)
check("I5 the prompt forbids inferences and no longer invites 'benefit'", "NO INFERENCES" in p and "fact or benefit" not in p)
check("I6 scene facts are asked at temperature 0", "temperature=0" in open("listing_scraper.py").read())
print("FAILS:", fails)
