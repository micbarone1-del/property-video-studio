import scene_script as s, listing_scraper as l
fails = 0
def check(n, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + n); fails += 0 if ok else 1
p = s.build_blocks_prompt("x", "Roma", "Agenzia", ["a"] * 6, ["cucina"] * 6)
check("V1 the prompt asks for the listing's own selling expressions first", "SOURCES, IN THIS ORDER OF PREFERENCE" in p and "SELLING EXPRESSIONS" in p)
check("V2 photo notes are last resort and capped at two sentences", "last resort" in p and "at most THREE photo-note sentences" in p)
check("V3 the tone is no longer 'objective, calm, factual'", "calm, factual" not in p and "estate-agent tone" in p)
check("V4 the photo block says last resort", "LAST-RESORT" in l.scene_facts_block(["x"], ["cucina"]))
print("FAILS:", fails)
