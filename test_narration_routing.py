"""test_narration_routing.py - prompt and validator read the SAME routing tables; the view check ignores place names (2026-11-12)."""
import scene_script as ss, narration as nr
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
desc_photos = "Villino a Marino. " + ss.PHOTO_FACTS_MARK + ": soggiorno, cucina."
chk("V1 a place name (Marino) is not a sea view", ss.view_problems("GIAL presenta un appartamento ad Marino.", desc_photos) == [])
chk("V2 the common word 'mare' is still refused when the photos do not show it", len(ss.view_problems("Si affaccia sul mare.", desc_photos)) == 1)
chk("V3 'mare' is accepted when the photo facts confirm it", ss.view_problems("Si affaccia sul mare.", "x " + ss.PHOTO_FACTS_MARK + ": vista mare dal balcone") == [])
seq = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
labels = ["Esterno", "Soggiorno", "Cucina", "Camere", "Bagni", "Giardino"]
p = ss.build_blocks_prompt("Appartamento con posto auto.", "Marino", "GIAL IMMOBILIARE", labels, seq)
chk("R1 the prompt lists every service space of the table", all(k in p for k in ss.SERVICE_SPACE_KEYWORDS))
chk("R2 the prompt names the scenes where they are allowed", "exterior or outdoor scene" in p)
chk("R3 over the kitchen slot the prompt forbids the words of the other rooms", "never use soggiorno" in p or "never use soggiorno, salone" in p)
ok = ["Appartamento luminoso in ottima posizione.", "La zona e ben servita dai mezzi pubblici.", "Gli spazi sono distribuiti con equilibrio.",
      "L'immobile ha tre camere da letto ampie.", "Il bagno e comodo e ben distribuito.", "Contatta GIAL IMMOBILIARE per vederlo."]
def probe(s):
    blocks = [" ".join(s[0:2]), " ".join(s[2:4]), " ".join(s[4:6])]
    return ss.validate_blocks(blocks, "Appartamento luminoso con tre camere e due bagni.", "GIAL IMMOBILIARE", None, split_fn=nr.split_into_sentences, scene_sequence=seq)
g = list(ok); g[5] = "Il giardino ha un comodo posto auto privato."
chk("R4 a parking space over the garden scene is allowed now", not any("another space" in x for x in probe(g)))
b = list(ok); b[4] = "Il bagno ha un posto auto accanto."
chk("R5 over a bathroom scene it is not refused (soft preference)", not any("another space" in x for x in probe(b)))
src = open("scene_script.py", encoding="utf-8").read()
chk("R6 only ONE place lists the scenes where service spaces are allowed", src.count("SERVICE_SPACE_OK_SCENES = (") == 1)
print("FAILS", F); raise SystemExit(1 if F else 0)
