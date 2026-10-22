"""Patch B (2026-10-22): per-scene narration for the STANDARD URL/Relinx video. No network, no API key, no TTS.
Run: python3 test_scene_script.py"""
import os, sys, types, json
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import scene_script as ss
import narration as N
import listing_scraper as ls

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

DESC = ("Villa in vendita a Roma, Olgiata. Abbiamo il piacere di proporre villa unifamiliare di 650 metri quadri "
        "completamente ristrutturata, con giardino di 3000 metri quadri, 5 camere da letto e 4 bagni. Soggiorno ampio, "
        "cucina abitabile, terrazza. Prezzo 1.680.000 euro.")
AG = "Coldwell Banker"
PRICE = "€ 1.680.000"
GOOD = [
    "Coldwell Banker presenta una villa in vendita a Olgiata, vicino a Roma.",
    "La villa unifamiliare di 650 metri quadri è completamente ristrutturata.",
    "Il soggiorno è un ampio ambiente, ideale per vivere la casa.",
    "La cucina è abitabile.",
    "La zona notte dispone di 5 camere da letto.",
    "Terrazza e giardino completano la proprietà: contattate Coldwell Banker per maggiori informazioni.",
]
def val(s, **kw):
    return ss.validate(s, kw.get("desc", DESC), kw.get("agency", AG), kw.get("price", PRICE), split_fn=N.split_into_sentences)
def with_(i, text):
    s = list(GOOD); s[i] = text; return s

# ---------------- pure fact check
check("V1 a good script is accepted", val(GOOD) == [], val(GOOD))
check("V2 five sentences rejected", any("exactly 6" in p for p in val(GOOD[:5])))
check("V3 seven sentences rejected", any("exactly 6" in p for p in val(GOOD + ["Altro."])))
check("V4 non-list rejected", ss.validate(None, DESC)[0].startswith("expected exactly 6"))
long14 = "Una due tre quattro cinque sei sette otto nove dieci undici dodici tredici quattordici."
check("V5 scene 1-5: 14 words ok, 16 accepted (soft margin 2), 17 too long", not any("words" in p for p in val(with_(1, "La villa unifamiliare è ristrutturata, con 650 metri quadri e giardino di 3000 metri."))) and
      not any("words" in p for p in val(with_(1, long14 + " Altra parola."))) and
      any("maximum 14" in p for p in val(with_(1, long14 + " Altra parola qui."))))
S17 = "Il giardino e la terrazza completano la proprietà: contattate Coldwell Banker per ricevere tutte le maggiori informazioni."
check("V6 scene 6 may be up to 17 words, the same sentence is too long in scenes 1-5", not any("maximum" in p for p in val(with_(5, S17))) and any("maximum 14" in p for p in val(with_(2, S17))))
S18 = "Il giardino e la terrazza completano la proprietà e la rendono molto comoda: contattate Coldwell Banker per ricevere maggiori informazioni."
check("V7 scene 6: 19 words accepted (soft margin 2), 20 words rejected", not any("words" in p for p in val(with_(5, S17 + " Grazie mille.")))  and
      any("maximum 17" in p for p in val(with_(5, S18))))
check("V8 number not in the listing rejected", any("number 700" in p for p in val(with_(1, "La villa unifamiliare di 700 metri quadri è ristrutturata."))))
check("V9 number in the listing accepted (650, 3000, 5, 4)", val(with_(1, "La villa ha 650 metri quadri e un giardino di 3000 metri quadri.")) == [])
check("V10 number word not in the listing rejected (sei bagni)", any("number word" in p for p in val(with_(4, "La zona notte dispone di sette camere da letto."))))
check("V11 number word backed by a digit in the listing accepted (cinque = 5)", val(with_(4, "La zona notte dispone di cinque camere da letto.")) == [])
check("V12 feature not in the listing rejected (piscina)", any("piscin" in p for p in val(with_(5, "Piscina e giardino completano la proprietà: contattate Coldwell Banker per maggiori informazioni."))))
check("V13 feature in the listing accepted (terrazza, giardino)", val(GOOD) == [])
check("V14 promotional adjective rejected", any("promotional" in p for p in val(with_(2, "Il soggiorno è un meraviglioso ambiente luminoso."))))
check("V15 promotional adjective allowed when the listing says it", val(with_(2, "Il soggiorno è un meraviglioso ambiente luminoso."), desc=DESC + " Meraviglioso soggiorno.") == [])
check("V16 floors never named", any("floor" in p for p in val(with_(3, "Al primo piano troviamo la camera da letto."))) and any("floor" in p for p in val(with_(3, "La cucina si trova al piano terra."))))
check("V17 'su due piani' is a general fact, not a floor reference", not any("floor" in p for p in val(with_(1, "La villa si sviluppa su due piani."), desc=DESC + " Su due piani.")))
check("V18 price (digits) rejected", any("price" in p for p in val(with_(1, "La villa costa 1.680.000 euro."))))
DESC_RENT = DESC.replace("Prezzo 1.680.000 euro.", "Affitto 1.200 euro al mese.")
check("V18b price known only from the listing text (Relinx passes no price): digits rejected", any("price" in p for p in val(with_(1, "La villa ha 650 metri quadri a 1.680.000."), price=None)) and
      any("price" in p for p in val(with_(1, "La villa ha 650 metri quadri a 1.200."), price=None, desc=DESC_RENT)))
check("V18c a size next to no money word is still a normal number", val(with_(1, "La villa ha 650 metri quadri e giardino di 3000 metri."), price=None) == [])
check("V19 price (euro word / symbol) rejected", any("price" in p for p in val(with_(1, "La villa è proposta a un ottimo euro prezzo."))) and any("price" in p for p in val(with_(1, "La villa è in vendita a € molti."))))
check("V20 phone number rejected", any("phone" in p for p in val(with_(5, "Chiamate il 0612345678 oggi stesso per maggiori informazioni sulla villa."))))
check("V21 scene 1 must say sale or rent", any("must say" in p for p in val(with_(0, "Coldwell Banker presenta una villa a Olgiata, vicino a Roma."))))
check("V22 'in affitto' rejected when the listing says only sale", any("affitto" in p for p in val(with_(0, "Coldwell Banker presenta una villa in affitto a Olgiata, vicino a Roma."))))
check("V23 'in affitto' accepted when the listing says rent", val(with_(0, "Coldwell Banker presenta una villa in affitto a Olgiata, vicino a Roma."), desc="Villa in affitto a Roma. 650 metri quadri ristrutturata giardino 3000 5 4 terrazza.") == [])
check("V24 agency named in scene 1 and in scene 6", any("scene 1: must name" in p for p in val(with_(0, "Presentiamo una villa in vendita a Olgiata, vicino a Roma."))) and
      any("scene 6: must name" in p for p in val(with_(5, "Terrazza e giardino completano la proprietà: contattate l'agenzia per maggiori informazioni."))))
check("V25 no agency name known: the agency check is skipped", val(with_(0, "Presentiamo una villa in vendita a Olgiata, vicino a Roma."), agency=None) == [] or
      not any("must name" in p for p in val(with_(0, "Presentiamo una villa in vendita a Olgiata, vicino a Roma."), agency=None)))
check("V26 two sentences inside one scene rejected", any("more than one sentence" in p for p in val(with_(3, "La cucina è abitabile. Ha molti armadi."))))
check("V27 sentence must end with a full stop", any("full stop" in p for p in val(with_(3, "La cucina è abitabile!"))))
check("V28 too short rejected", any("too short" in p for p in val(with_(3, "Cucina."))))
check("V30 a sentence starting with a digit is named (splitter cannot see the boundary)", any("scene 2: must start with a capital letter" in p for p in ss.validate(with_(1, "650 metri quadri con giardino di 3000 metri."), DESC, AG, PRICE, split_fn=lambda t: ["a"] * 5)))
check("V31 parse adds the missing final stop", ss.parse('["Una frase senza punto", "Altra frase."]') == ["Una frase senza punto.", "Altra frase."])
check("V32 a final semicolon becomes a stop", ss.parse('["Una frase;", "Altra."]')[0] == "Una frase.")
check("V29 the spoken split must give 6 sentences", any("splits into 7" in p for p in ss.validate(GOOD, DESC, AG, PRICE, split_fn=lambda t: ["a"] * 7)))
check("V30 an unrelated real split of the good script gives 6", len(N.split_into_sentences(" ".join(GOOD))) == 6)

# ---------------- parse
check("P1 plain JSON array", ss.parse('["a b c d.", "e"]') == ["a b c d.", "e."])
check("P2 fenced JSON array", ss.parse('```json\n["x y z w."]\n```') == ["x y z w."])
check("P3 text around the array", ss.parse('Ecco: ["uno due tre quattro."] fine') == ["uno due tre quattro."])
check("P4 garbage / object / mixed types -> None", ss.parse("niente") is None and ss.parse('{"a": 1}') is None and ss.parse('[1, 2]') is None and ss.parse("") is None)
check("P5 whitespace in a sentence is collapsed", ss.parse('["a   b\\nc d."]') == ["a b c d."])

# ---------------- spill + prompts
sync = {"rows": [{"index": 0, "spill_secs": 0.0}, {"index": 1, "spill_secs": 1.5}, {"index": 2, "spill_secs": 0.5},
                 {"index": 5, "spill_secs": 3.0}]}
check("S1 spill: only scenes 1-5 beyond 0.8 s are reported; the last sentence is judged by the overflow rule", ss.spill_problems(sync) == [(1, 1.5)])
check("S2 spill without a plan is empty", ss.spill_problems(None) == [] and ss.spill_problems({}) == [])
pr = ss.build_prompt(DESC, "via X", AG, ["facciata/esterno dell'edificio", "soggiorno", "cucina", "camere da letto", "bagni", "spazi esterni (giardino/terrazza)"])
check("S3 prompt: 6 scenes with roles, labels, and the hard rules", all(f"Scene {i}:" in pr for i in range(1, 7)) and "OPENING" in pr and "GENERAL FACTS" in pr and "CLOSING" in pr and
      "soggiorno" in pr and "Do NOT say the price" in pr and "floors" in pr and "JSON array" in pr)
tp = ss.build_tighten_prompt(GOOD, [(1, 1.5)], DESC, AG)
check("S4 tighten prompt names the sentence and keeps the others", "sentence 2" in tp and "1.5 s" in tp and "EXACTLY unchanged".lower() in tp.lower().replace("exactly unchanged", "exactly unchanged"))

check("V33 tighten prompt keeps sale/rent and the agency name", "in vendita" in tp and "Coldwell Banker" in tp and "MUST-KEEP" in tp)

# ---------------- scene slots / sequence (single shared definition)
P = lambda c, i=0: {"url": f"{c}{i}", "category": c, "local_path": f"/img/{c}{i}.jpg"}
sel6 = {"selected": {c: [P(c)] for c in ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]}}
check("L1 sequence follows PRIORITY_ORDER", ls.standard_scene_sequence(sel6) == ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"])
sel_dup = {"selected": {"exterior": [P("exterior")], "living": [P("living", 0), P("living", 1)], "kitchen": [P("kitchen")],
                        "bedrooms": [P("bedrooms", 0), P("bedrooms", 1)], "bathrooms": [P("bathrooms")]}}
check("L2 repeated categories repeat in the sequence (no outdoor)", ls.standard_scene_sequence(sel_dup) == ["exterior", "living", "living", "kitchen", "bedrooms", "bedrooms", "bathrooms"])
cfg = ls.build_standard_video_scenes_config(sel_dup, {}, 5)
check("L3 scenes config is built from the SAME slots (same order, same photos)",
      [s["category"] for s in cfg] == ls.standard_scene_sequence(sel_dup) and
      [s["local_image_path"] for s in cfg] == [p["local_path"] for _, p in ls.standard_scene_slots(sel_dup)])
check("L4 empty selection -> empty sequence", ls.standard_scene_sequence({"selected": {}}) == [])

# ---------------- orchestration with fakes
replies = []; prompts = []
class Msgs:
    def create(self, **kw):
        txt = kw["messages"][0]["content"]
        prompts.append(txt)
        r = replies.pop(0)
        if isinstance(r, Exception): raise r
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=r)])
class FakeClient:
    def __init__(self, api_key=None): self.messages = Msgs()
ls.anthropic.Anthropic = FakeClient
ls._track_claude = lambda r: r
queue = []; measure_calls = []; trims = []
def fake_measure(text, voice_id=None, attempts=1, scene_secs=None):
    measure_calls.append((text, scene_secs))
    dur, spill = queue.pop(0)
    rows = [{"index": i, "scene": i, "start_secs": i * 5.0, "end_secs": i * 5.0 + 4.0, "offset_in_scene_secs": 0.0,
             "extra_pause_secs": 0.0, "spill_secs": spill.get(i, 0.0)} for i in range(6)]
    return {"ok": True, "duration_secs": dur, "audio_path": "/tmp/fake.mp3", "sync": {"rows": rows, "marker": len(measure_calls)}}
ls._measure_tts_duration = fake_measure
ls._fade_out_and_trim = lambda path, target, search_window_secs=4.0: (trims.append(target), path)[1]
SEQ = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
def run(rep, tts, premium=False, seq=SEQ, agency=AG, price=PRICE):
    replies[:] = list(rep); queue[:] = list(tts); prompts.clear(); measure_calls.clear(); trims.clear()
    return ls.generate_narration_and_derive_scenes(DESC, "largo Olgiata 15", price, None, premium, agency, ["exterior"], seq)
J = lambda s: json.dumps(s, ensure_ascii=False)

o = run([J(GOOD)], [(28.5, {})])
check("O1 happy path: per_scene, one Claude call, one TTS call, 6 scenes", o["ok"] and o["narration_mode"] == "per_scene" and len(prompts) == 1 and len(measure_calls) == 1 and
      o["tts_calls_used"] == 1 and o["scene_count"] == 6 and o["script_attempts"] == 1 and not o["script_tightened"], o)
check("O2 the text is the 6 sentences joined, TTS gets the fixed 6x5 s scenes", o["narration_text"] == " ".join(GOOD) and measure_calls[0][1] == [5] * 6)
check("O3 the prompt carries the room of each scene", "soggiorno" in prompts[0] and "cucina" in prompts[0] and "camere da letto" in prompts[0] and "Coldwell Banker" in prompts[0])
check("O4 the result says nothing about a fallback", o["script_fallback_reason"] is None)

bad_price = with_(1, "La villa costa 1.680.000 euro in vendita.")
o = run([J(bad_price), J(GOOD)], [(28.5, {})])
check("O5 first script rejected (price) -> second attempt accepted, told why", o["narration_mode"] == "per_scene" and o["script_attempts"] == 2 and len(prompts) == 2 and "REJECTED" in prompts[1] and "price" in prompts[1], (o.get("narration_mode"), o.get("script_attempts")))

o = run([J(bad_price), J(bad_price), J(bad_price), "Testo narrazione di prova " * 12], [(28.5, {})])
check("O6 three rejections -> single-text fallback, job still ok, reason recorded", o["ok"] and o["narration_mode"] == "single_text" and o["script_fallback_reason"] and "fact check" in o["script_fallback_reason"] and o["tts_calls_used"] == 1, o)
check("O7 the fallback used the previous single-text prompt (4th Claude call)", len(prompts) == 4 and "voiceover script" in prompts[3])

check("O5b first two rejected, third accepted", run([J(bad_price), J(bad_price), J(GOOD)], [(28.5, {})])["script_attempts"] == 3)
o = run([J(["non json"]) if False else "not json at all", "still not json", "again not json", "Testo narrazione " * 12], [(28.5, {})])
check("O8 unparseable replies -> fallback, not a crash", o["ok"] and o["narration_mode"] == "single_text")
o = run([RuntimeError("boom"), "Testo narrazione " * 12], [(28.5, {})])
check("O9 Claude error on the script -> fallback to single text, not a failed job", o["ok"] and o["narration_mode"] == "single_text" and "boom" in (o["script_fallback_reason"] or ""), o.get("script_fallback_reason"))

o = run(["Testo narrazione " * 12], [(28.5, {})], seq=None)
check("O10 no sequence -> single text exactly as before", o["ok"] and o["narration_mode"] == "single_text" and o["script_fallback_reason"] is None and len(prompts) == 1 and "voiceover script" in prompts[0])
o = run(["Testo narrazione " * 12], [(36.0, {}), (30.0, {})], premium=True)
check("O11 premium with a sequence -> single text (premium is a later step)", o["narration_mode"] == "single_text" and o["script_fallback_reason"] is None)
o = run(["Testo narrazione " * 12], [(28.5, {})], seq=SEQ[:5])
check("O12 a 5-scene sequence is not the standard video -> single text", o["narration_mode"] == "single_text")

# spill / tighten
TIGHT = list(GOOD); TIGHT[1] = "La villa di 650 metri quadri è ristrutturata."
o = run([J(GOOD), J(TIGHT)], [(30.0, {1: 1.5}), (28.0, {})])
check("O13 a sentence too long for its scene -> ONE rewrite + second TTS, adopted", o["narration_mode"] == "per_scene" and o["script_tightened"] and o["tts_calls_used"] == 2 and
      o["narration_text"] == " ".join(TIGHT) and len(measure_calls) == 2, o)
check("O14 only the tighten prompt was sent for the second call, naming the sentence", "sentence 2" in prompts[1] and "too long" in prompts[1])
CH = list(TIGHT); CH[2] = "Il soggiorno è un ampio ambiente."
o = run([J(GOOD), J(CH)], [(30.0, {1: 1.5})])
check("O15 the rewrite touched a sentence it should not -> rejected, first script kept, no second TTS", o["script_tightened"] is False and o["tts_calls_used"] == 1 and o["narration_text"] == " ".join(GOOD) and len(measure_calls) == 1)
BADT = list(TIGHT); BADT[1] = "La villa di 999 metri quadri è ristrutturata."
o = run([J(GOOD), J(BADT)], [(30.0, {1: 1.5})])
check("O16 the rewrite fails the fact check -> first script kept", o["script_tightened"] is False and o["narration_text"] == " ".join(GOOD) and o["tts_calls_used"] == 1)
o = run([J(GOOD), RuntimeError("x")], [(30.0, {1: 1.5})])
check("O17 the rewrite call fails -> first script kept, job continues", o["ok"] and o["script_tightened"] is False and o["narration_mode"] == "per_scene")
o = run([J(GOOD), J(TIGHT)], [(30.0, {1: 1.5}), (30.0, {1: 1.5, 2: 1.0})])
check("O18 the rewrite is worse than the first -> first kept", o["script_tightened"] is False and o["narration_text"] == " ".join(GOOD) and o["tts_calls_used"] == 2)
o = run([J(GOOD)], [(30.0, {0: 0.5})])
check("O19 a spill under the tolerance (0.5 s) is left alone: no rewrite", o["tts_calls_used"] == 1 and len(prompts) == 1 and not o["script_tightened"])

# per-scene never rewrites the whole text
o = run([J(GOOD)], [(36.0, {})])
check("O20 speech above the band: no whole-text shorten call, hard cap at 32 s as before", o["narration_mode"] == "per_scene" and len(prompts) == 1 and trims == [32.0] and o["was_trimmed"] and o["scene_count"] == 6 and o["sync"] is None, (trims, o))
o = run([J(GOOD)], [(21.0, {})])
check("O21 speech below the band: no whole-text extend call, still 6 scenes", o["narration_mode"] == "per_scene" and len(prompts) == 1 and o["scene_count"] == 6 and o["tts_calls_used"] == 1)
o = run([J(GOOD)], [(32.0, {})])
check("O22 32 s speech accepted without a trim (30 s of scenes + 2 s absorbed)", not o["was_trimmed"] and trims == [])

# no agency known
GOOD_NOAG = list(GOOD); GOOD_NOAG[0] = "Presentiamo una villa in vendita a Olgiata, vicino a Roma."; GOOD_NOAG[5] = "Terrazza e giardino completano la proprietà: contattate l'agenzia per maggiori informazioni."
o = run([J(GOOD_NOAG)], [(28.5, {})], agency=None)
check("O23 no agency name: per-scene script still works", o["narration_mode"] == "per_scene" and "l'agenzia" in prompts[0])

# ---------------- call sites: one selection, done first, reused (URL and Relinx), single shared definition
api = open("api_server.py").read()
i_url_sel = api.index("scraper.select_photos_for_scene_count, extraction[\"photos\"], scraper.STANDARD_SCENES")
i_url_narr = api.index("scraper.generate_narration_and_derive_scenes,", i_url_sel)
check("C1 URL path: the standard photo selection runs BEFORE the narration", i_url_sel < i_url_narr)
check("C2 URL path: the narration receives the scene sequence", "premium, agency_name, scene_category_order, scene_sequence," in api)
check("C3 URL path: the selection is reused (no second selection for 6 scenes)", "elif pre_selection is not None and narration[\"scene_count\"] == scraper.STANDARD_SCENES:" in api and "selection = pre_selection" in api)
i_rel_sel = api.index("scraper.select_photos_for_scene_count, photos_for_selection, scraper.STANDARD_SCENES")
i_rel_narr = api.index("scraper.generate_narration_and_derive_scenes,", i_rel_sel)
check("C4 Relinx path: selection before narration, sequence passed, selection reused",
      i_rel_sel < i_rel_narr and "agency.get(\"name\"), scene_category_order, scene_sequence," in api and "if narration[\"scene_count\"] == scraper.STANDARD_SCENES:\n            selection = pre_selection" in api)
check("C5 both job records store narration_mode", api.count('"narration_mode": narration.get("narration_mode")') == 2)
check("C6 the scenes config builder uses the shared slots (no second copy of the loop)", "for category, photo in standard_scene_slots(selection):" in open("listing_scraper.py").read())

print(f"RESULT: {'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
