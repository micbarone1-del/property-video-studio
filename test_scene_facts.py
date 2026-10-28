import os, sys, types
import listing_scraper as ls
res = []


def check(name, ok):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


seq = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
photos = [{"url": "u/" + c, "original_url": "o/" + c} for c in seq]
six = ["Facciata chiara con finestre", "", "Luce naturale e pareti chiare", "Finestra con luce laterale", "Piastrelle chiare e finestra", "Balcone con vista aperta"]
j = lambda l: __import__("json").dumps(l, ensure_ascii=False)

check("F1 a valid list of facts is kept", ls.parse_scene_facts(j(six), 6) == six)
check("F2 a reply wrapped in a code fence is read", ls.parse_scene_facts("```json\n" + j(six) + "\n```", 6) == six)
check("F3 wrong length or not json -> None", ls.parse_scene_facts(j(six[:5]), 6) is None and ls.parse_scene_facts("no list here", 6) is None)
bad = list(six); bad[0] = "Facciata appena ristrutturata"; bad[2] = "Cucina con 2 finestre"
r = ls.parse_scene_facts(j(bad), 6)
check("F4 a banned word or a digit empties only that phrase", r is not None and r[0] == "" and r[2] == "" and r[3] == six[3])
bad2 = list(six); bad2[0] = "Facciata con parquet"; bad2[3] = "Camera splendida"; bad2[5] = "Balcone con vista aperta"
r2 = ls.parse_scene_facts(j(bad2), 6)
check("F4b a word a photo cannot prove (parquet, promotional) is dropped, balcony and view are kept", r2 is not None and r2[0] == "" and r2[3] == "" and r2[5] == six[5])
bad3 = list(six); bad3[1] = "Stanza vuota con pareti chiare"; bad3[2] = "Bagno stretto con piastrelle"; bad3[3] = "Pavimento in terracotta"
r3 = ls.parse_scene_facts(j(bad3), 6)
check("F4c a fact that names the room, says empty or names a material is dropped", r3 is not None and r3[1] == "" and r3[2] == "" and r3[3] == "" and r3[0] == six[0])
check("F4d the prompt asks for colours not materials and forbids naming the room", "COLOURS, never materials" in ls.SCENE_FACTS_PROMPT and "Never name the room" in ls.SCENE_FACTS_PROMPT)
bad4 = list(six); bad4[0] = "Vista su piazza con alberi"; bad4[5] = "Balcone in cemento grigio"; bad4[2] = "Vista su alberi e edifici"
r4 = ls.parse_scene_facts(j(bad4), 6)
check("F4e a place name or a material is dropped, a view of trees and buildings is kept", r4 is not None and r4[0] == "" and r4[5] == "" and r4[2] == "Vista su alberi e edifici")
check("F5 all phrases empty -> None", ls.parse_scene_facts(j([""] * 6), 6) is None)
blk = ls.scene_facts_block(six, seq)
check("F6 the block lists only non-empty facts, scene numbers as words, no room label, no digit", "Scene three: Luce naturale e pareti chiare" in blk and "Scene two" not in blk and "terrazza" not in blk and not any(c.isdigit() for c in blk))

orig_core, orig_desc, orig_flag = ls._generate_narration_core, ls.describe_scenes_for_narration, os.environ.get("PVS_SCENE_FACTS")
seen, calls = {}, []
ls._generate_narration_core = lambda description, *a, **k: (seen.update(d=description) or {"ok": True})
def fake_desc(sp):
    calls.append(len(sp))
    return {"ok": True, "facts": six}
ls.describe_scenes_for_narration = fake_desc
os.environ.pop("PVS_SCENE_FACTS", None)
r = ls.generate_narration_and_derive_scenes("TESTO", None, None, None, False, "Ag", None, seq, photos)
check("W1 switch off: text unchanged, no vision call, scene_facts None", seen["d"] == "TESTO" and not calls and r["scene_facts"] is None)
os.environ["PVS_SCENE_FACTS"] = "1"
r = ls.generate_narration_and_derive_scenes("TESTO", None, None, None, False, "Ag", None, seq, photos)
check("W2 switch on: the facts follow the listing text and are returned", seen["d"].startswith("TESTO") and "Scene three: Luce naturale e pareti chiare" in seen["d"] and r["scene_facts"] == six)
calls.clear()
ls.generate_narration_and_derive_scenes("TESTO", None, None, None, True, "Ag", None, seq, photos)
ls.generate_narration_and_derive_scenes("TESTO", None, None, None, False, "Ag", None, seq, photos[:5])
ls.generate_narration_and_derive_scenes("TESTO", None, None, None, False, "Ag", None, seq, None)
check("W3 premium, 5 photos or no photos: no vision call, text unchanged", not calls and seen["d"] == "TESTO")
ls.describe_scenes_for_narration = lambda sp: {"ok": False, "error": "boom"}
r = ls.generate_narration_and_derive_scenes("TESTO", None, None, None, False, "Ag", None, seq, photos)
check("W4 a failed vision call leaves the text as it was and the job goes on", seen["d"] == "TESTO" and r["ok"] and r["scene_facts"] is None and r["scene_facts_error"] == "boom")
ls.describe_scenes_for_narration = orig_desc

sent = {}
class _Msgs:
    def create(self, **kw):
        sent.update(kw)
        blk = types.SimpleNamespace(type="text", text=j(six))
        return types.SimpleNamespace(content=[blk], usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))
ls.anthropic.Anthropic = lambda **kw: types.SimpleNamespace(messages=_Msgs())
ls.fetch_photo_bytes = lambda u, fb=None, timeout=20, attempts=1: {"ok": True, "content": b"x"}
d = ls.describe_scenes_for_narration(photos)
imgs = [c for c in sent["messages"][0]["content"] if c["type"] == "image"]
check("D1 one call carries the 6 photos and returns the facts", d == {"ok": True, "facts": six} and len(imgs) == 6)
ls.fetch_photo_bytes = lambda u, fb=None, timeout=20, attempts=1: {"ok": False, "error": "404"}
check("D2 a photo that cannot be downloaded -> ok False", ls.describe_scenes_for_narration(photos)["ok"] is False)

import scene_script as ss
_t = "La proprieta e completamente rifinita e perfetta. Ottima esposizione."
_p1 = ss._fact_problems(_t, "t", _t.lower(), "appartamento da ristrutturare", set(), set())
_p2 = ss._fact_problems(_t, "t", _t.lower(), "appartamento rifinito e perfetto, ottima esposizione", set(), set())
check("V1 words of state or quality (rifinit, perfett, ottim) are rejected when the listing text does not use them", all(any(k in x for x in _p1) for k in ("rifinit", "perfett", "ottim")))
check("V2 the same words are accepted when the listing text uses them", not any("promotional" in x for x in _p2))
api = open("api_server.py").read()
q = chr(34)
check("S1 both workflows pass the scene photos and store the facts", api.count("scraper.standard_scene_photos(") == 2 and api.count(q + "scene_facts" + q + ": narration.get(") == 2)
if orig_flag is None:
    os.environ.pop("PVS_SCENE_FACTS", None)
print(str(sum(res)) + "/" + str(len(res)))
sys.exit(0 if all(res) else 1)
