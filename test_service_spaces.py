import scene_script as ss
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
chk("S1 interrato found", ss.service_spaces("Il piano interrato ospita la cantina") == {"interrato", "cantina"})
chk("S2 box doccia is not a service space", ss.service_spaces("Bagno con box doccia") == set())
chk("S3 deposito cauzionale is not one", ss.service_spaces("Deposito cauzionale richiesto") == set())
chk("S4 box auto found", ss.service_spaces("Comodo box auto di proprieta") == {"box auto"})
chk("S5 ROOM_KEYWORDS untouched", set(ss.ROOM_KEYWORDS) == {"living", "kitchen", "bedrooms", "bathrooms", "outdoor"})
chk("S6 listing tie: lavanderia next to bagno", ss._service_tied("bagno con lavanderia", "bathrooms", "lavanderia"))
chk("S7 no tie when far apart", not ss._service_tied("bagno luminoso. " + "x " * 60 + "cantina", "bathrooms", "cantina"))
src = open("scene_script.py").read()
chk("S8 validator wired, exterior and outdoor exempt (one constant)", 'service_spaces(sent) if cat not in SERVICE_SPACE_OK_SCENES' in src and ss.SERVICE_SPACE_OK_SCENES == ("exterior", "outdoor"))
chk("S9 prompt has the rule and the no-tu rule", "WHAT A SENTENCE IS ABOUT" in src and "'trovi'" in src)
print("FAILS", F)
import narration as ls
def _probe(sentences, seq):
    blocks = [" ".join(sentences[0:2]), " ".join(sentences[2:4]), " ".join(sentences[4:6])]
    return ss.validate_blocks(blocks, "Appartamento luminoso con tre camere e due bagni.", "GIAL IMMOBILIARE", None,
                              split_fn=ls.split_into_sentences, scene_sequence=seq)
_seq = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
_ok = ["Appartamento luminoso in ottima posizione.", "La zona e ben servita dai mezzi pubblici.", "Gli spazi sono distribuiti con equilibrio.",
       "L'immobile ha tre camere da letto ampie.", "Il bagno e comodo e ben distribuito.", "Contatta GIAL IMMOBILIARE per vederlo."]
_bad = list(_ok); _bad[4] = "Il piano interrato ospita cantina e garage."
_ext = list(_ok); _ext[0] = "Edificio con garage e posto auto comodi."
chk("S10 service space over a bathroom scene is blocked", any("another space" in p for p in _probe(_bad, _seq)))
chk("S11 same text without it: no service-space problem", not any("another space" in p for p in _probe(_ok, _seq)))
chk("S12 garage over the exterior scene is allowed", not any("another space" in p for p in _probe(_ext, _seq)))
print("FAILS", F)
