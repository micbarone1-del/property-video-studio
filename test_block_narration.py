"""Patch Q (2026-10-24): narration in 3 blocks fitted to the fixed 5 s clips (video leads, voice adapts). Pure planner, block
script rules, orchestration with fakes, wiring (text checks). No network, no audio. Run: python3 test_block_narration.py"""
import os, sys, types, json
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import scene_timing as T
import scene_script as ss
import listing_scraper as ls

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

# ---------------- A. plan_blocks
nom, vend = T.block_nominal_starts(6, 2)
check("A1 nominal starts [0, 9.6, 18.6], video 27.5", [round(x, 2) for x in nom] == [0.0, 9.6, 18.6] and abs(vend - 27.5) < 1e-6, (nom, vend))
p = T.plan_blocks([8.9, 8.0, 8.6])
check("A2 good durations -> ok, rates inside 0.92-1.10, gaps 0.3-1.6", p["ok"] and all(0.92 - 1e-6 <= r <= 1.10 + 1e-6 for r in p["rates"]), p)
gaps = [p["starts"][i + 1] - p["ends"][i] for i in range(2)]
check("A3 pause between blocks inside 0.3-1.6 s", all(0.3 - 1e-6 <= g <= 1.6 + 1e-6 for g in gaps), gaps)
check("A4 starts begin at 0 and increase", p["starts"][0] == 0.0 and p["starts"][0] < p["starts"][1] < p["starts"][2], p["starts"])
q = T.plan_blocks([11.5, 8.2, 8.2])
check("A5 block 1 far too long -> not ok, too_long block 0 with seconds_over > 0", (not q["ok"]) and q["problems"][0]["block"] == 0 and q["problems"][0]["kind"] == "too_long" and q["problems"][0]["seconds_over"] > 0, q["problems"])
w = T.plan_blocks([5.0, 8.2, 8.2])
check("A6 block 1 far too short -> too_short", (not w["ok"]) and w["problems"][0]["kind"] == "too_short", w["problems"])
for ds in ([8.9, 8.0, 8.6], [8.0, 7.5, 7.8], [9.4, 8.7, 9.0]):
    pp = T.plan_blocks(ds)
    if not pp["ok"]:
        check("A7 sample durations feasible " + str(ds), False, pp["problems"]); continue
    cp = T.plan_from_anchors([None, None, pp["starts"][1], None, pp["starts"][2], None], pp["speech_end"], [5.0] * 6)
    sp = [c["speed"] for c in cp["clips"]]
    check("A7 clip speeds inside 0.8-1.25 for " + str(ds), cp["ok"] and all(0.8 - 1e-3 <= s <= 1.25 + 1e-3 for s in sp), sp)

# ---------------- A8. sentence level (Patch R)
check("A8 second sentence offset = one clip minus one cross-fade (4.5 s)", abs(T.SECOND_OFFSET_SECS - 4.5) < 1e-9)
check("A9 pause puts sentence 2 at the offset (4.2 s sentence -> 0.3 s)", abs(T.sentence_pause(4.2, 1.0) - 0.3) < 1e-9)
check("A10 pause is clamped (long first sentence -> 0.25, short -> 1.6)", T.sentence_pause(6.0, 1.0) == T.SENT_PAUSE_MIN_SECS and T.sentence_pause(2.0, 1.0) == T.SENT_PAUSE_MAX_SECS)
check("A11 pause written before the tempo change = final pause x rate", abs(T.sentence_pause_pre(4.2, 1.1) - T.sentence_pause(4.2, 1.1) * 1.1) < 1e-9)
so = T.second_sentence_offsets(6)
check("A12 second-sentence offsets: 5.1 s in the first block (longer first clip), 4.5 s in the others", so == [5.1, 4.5, 4.5], so)
at = T.sentence_anchor_times([0, 9.6, 18.6], so)
check("A13 anchors: scene 1 free, scenes 2-6 each tied to its own sentence", at == [None, 5.1, 9.6, 14.1, 18.6, 23.1], at)
cp = T.plan_from_anchors(at, 27.3, [5.0] * 6)
check("A14 sentences on the cuts -> every clip at normal speed", cp["ok"] and all(abs(c["speed"] - 1.0) < 0.02 for c in cp["clips"]), [c["speed"] for c in cp["clips"]])

# ---------------- B. block script
DESC = ("Villa in vendita a Roma, Olgiata. Abbiamo il piacere di proporre villa unifamiliare di 650 metri quadri "
        "completamente ristrutturata, con giardino di 3000 metri quadri, 5 camere da letto e 4 bagni. Soggiorno ampio, "
        "cucina abitabile, terrazza. Prezzo 1.680.000 euro.")
AG = "Coldwell Banker"; PRICE = "€ 1.680.000"
SEQ = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
LABELS = ["Facciata", "Soggiorno", "Cucina", "Camera da letto", "Bagno", "Giardino"]
GOOD = ["Coldwell Banker presenta una villa in vendita a Olgiata. Di 650 metri quadri, è completamente ristrutturata.",
        "La cucina è abitabile e molto funzionale. Ci sono 5 camere da letto, tutte molto luminose.",
        "Gli spazi sono curati nei dettagli. Il giardino è di 3000 metri quadri, contatta Coldwell Banker."]
from narration import split_into_sentences as SPLIT
pr = ss.validate_blocks(GOOD, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B1 good blocks accepted", pr == [], pr)
check("B2 parse_blocks reads a JSON object (also in a code fence)", ss.parse_blocks(json.dumps({"blocks": GOOD})) == GOOD and ss.parse_blocks("```json\n" + json.dumps({"blocks": GOOD}) + "\n```") == GOOD)
check("B3 parse_blocks rejects the wrong count / garbage", ss.parse_blocks(json.dumps({"blocks": GOOD[:2]})) is None and ss.parse_blocks("no") is None and ss.parse_blocks("") is None)
# the real defects of draft 41ae5a44 (Michele, 2026-10-24): topics out of order inside the block
bad = list(GOOD); bad[1] = "Ci sono 5 camere da letto, tutte molto luminose. La cucina è abitabile e molto funzionale."
pr = ss.validate_blocks(bad, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B4 bedrooms named over the kitchen scene (order swapped) is rejected, both sentences", sum("block 2" in x for x in pr) >= 2, pr)
bad = list(GOOD); bad[2] = "Il giardino è di 3000 metri quadri. I 4 bagni sono curati nei dettagli, contatta Coldwell Banker."
pr = ss.validate_blocks(bad, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B5 garden before bathrooms (as in the real draft) is rejected", len([x for x in pr if "block 3" in x]) >= 2, pr)
gen = list(GOOD); gen[1] = "Gli ambienti sono ben distribuiti e luminosi. Ci sono 5 camere da letto, tutte molto luminose."
pr = ss.validate_blocks(gen, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B6 a GENERAL sentence over the kitchen scene is accepted (Michele 2026-10-25: only a wrong room name is not)", pr == [], pr)
four = list(GOOD); four[2] = "I 4 bagni sono curati nei dettagli. Il giardino è di 3000 metri quadri, contatta Coldwell Banker."
pr = ss.validate_blocks(four, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B6b more than 3 rooms named is rejected", any("at most 3" in x for x in pr), pr)
bad = list(GOOD); bad[0] = "Coldwell Banker presenta una villa in vendita a Olgiata. Di 650 metri quadri, è completamente ristrutturata e a un solo livello."
three = list(GOOD); three[0] = "Coldwell Banker presenta una villa in vendita. A Olgiata. Di 650 metri quadri, è ristrutturata."
pr = ss.validate_blocks(three, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B7 a block with 3 sentences is rejected", any("EXACTLY 2" in x for x in pr), pr)
short = list(GOOD); short[1] = "La cucina è abitabile. Ci sono 5 camere."
pr = ss.validate_blocks(short, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B8 too few words is rejected", len(pr) >= 1, pr)
fact = list(GOOD); fact[2] = "Gli spazi sono curati nei dettagli. Il giardino è di 9000 metri quadri, contatta Coldwell Banker."
pr = ss.validate_blocks(fact, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B9 invented number is rejected by the fact check", len(pr) >= 1, pr)
fb = ss.build_block_feedback([{"block": 0, "kind": "too_long", "seconds_over": 1.0}], [10.0, 8.0, 8.0], GOOD)
check("B10 block feedback names block 1, seconds, words to remove and keeps the rest", "Block 1" in fb and "10.0 s" in fb and "remove about" in fb and "EXACTLY" in fb, fb)
fs = ss.build_sync_feedback([{"clip": 3, "kind": "too_slow", "seconds_over": 1.2}, {"clip": 4, "kind": "too_fast", "seconds_over": 0.8}], GOOD)
fs2 = ss.build_sync_feedback([{"clip": 2, "kind": "too_fast", "seconds_over": 1.6}, {"clip": 3, "kind": "too_slow", "seconds_over": 0.3}], GOOD)
check("B11b a knock-on problem of the next scene is not reported (only the first sentence to fix)", "Block 2, sentence 1" in fs2 and "Block 2, sentence 2" not in fs2, fs2)
check("B11 sync feedback maps clip 3 -> block 2 sentence 2, clip 4 -> block 3 sentence 1", "Block 2, sentence 2 (scene 4)" in fs and "shorten" in fs and "Block 3, sentence 1 (scene 5)" in fs and "lengthen" in fs, fs)
pm = ss.build_blocks_prompt(DESC, "Via X", AG, LABELS, SEQ)
check("B12 prompt maps every sentence to its scene and demands the room name where required",
      "Block 2, sentence 1 (heard over scene 3: Cucina): may name this room" in pm and "ONLY if it is a real highlight" in pm and "Block 3, sentence 2 (heard over scene 6" in pm and AG in pm and "EXACTLY 2" in pm)

# ---------------- B13. word-timing check with the real audio (pure)
import word_align as WA
BL = GOOD
full_tk = WA.tokens(" ".join(BL))
def times_for(overrides=None):
    # token i said at 0.4 * i + shift per sentence start: sentence starts from the nominal plan
    so = T.second_sentence_offsets(6); starts = [0.0, 9.6, 18.6]
    out, idx = [], 0
    for b, text in enumerate(BL):
        for k_, sent in enumerate(SPLIT(text)):
            t0 = starts[b] + (0 if k_ == 0 else so[b])
            for w_i, _ in enumerate(WA.tokens(sent)):
                out.append((t0 + 0.4 * w_i, t0 + 0.4 * w_i + 0.3)); idx += 1
    for i_, t_ in (overrides or {}).items():
        out[i_] = (t_, t_ + 0.3)
    return out
cuts_nom = [0.0, 4.75, 9.25, 13.75, 18.25, 22.75, 27.5]
rooms = ss.check_room_words(BL, SEQ, times_for(), cuts_nom, SPLIT)
check("B13 rooms named in their own sentences, said inside their pictures -> all ok (kitchen, bedrooms, outdoor)", [r["room"] for r in rooms] == ["kitchen", "bedrooms", "outdoor"] and all(r["ok"] for r in rooms), rooms)
kit_idx = [i_ for i_, t_ in enumerate(full_tk) if t_ == "cucina"][0]
late_rooms = ss.check_room_words(BL, SEQ, times_for({kit_idx: 14.2}), cuts_nom, SPLIT)
check("B14 'cucina' said at 14.2 s (scene 3 ends at 13.75) is reported as late", [r["kind"] for r in late_rooms if r["room"] == "kitchen"] == ["late"], late_rooms)
early_rooms = ss.check_room_words(BL, SEQ, times_for({kit_idx: 8.0}), cuts_nom, SPLIT)
check("B15 'cucina' said at 8.0 s (before the kitchen picture) is reported as early", [r["kind"] for r in early_rooms if r["room"] == "kitchen"] == ["early"], early_rooms)
fbw = ss.build_word_check_feedback([r for r in late_rooms if not r["ok"]], BL)
check("B16 word-check feedback names block, sentence, word and time", "Block 2, sentence 1" in fbw and "'cucina'" in fbw and "14.2" in fbw, fbw)

# ---------------- C. orchestration with fakes
class Seg:                       # stands for a pydub segment: only its length (ms) matters here
    def __init__(self, ms): self.ms = int(round(ms))
    def __len__(self): return self.ms
replies, prompts = [], []
class FakeClient:
    def __init__(self, api_key=None): pass
ls.anthropic.Anthropic = FakeClient
def fake_reply(client, prompt, max_tokens=1024):
    prompts.append(prompt)
    r = replies.pop(0)
    if isinstance(r, Exception): raise r
    return r
ls._claude_text_reply = fake_reply
SENT = {}                        # sentence text -> seconds (default: words / 2.1)
synth_calls = []
def fake_synth(text, voice_id=None):
    synth_calls.append(text)
    sents = SPLIT(text)
    secs = [SENT.get(x, len(x.split()) / 2.1) for x in sents]
    return {"ok": True, "clips": [Seg(x * 1000) for x in secs], "sentence_secs": secs}
_REAL_SYNTH = ls._synthesize_block        # kept for the Patch R4 test of the real merge
ls._synthesize_block = fake_synth
def fake_segment(clips, rate, offset=None):
    d1 = len(clips[0]) / 1000.0
    kw = {} if offset is None else {"offset": offset}
    return Seg(len(clips[0]) + T.sentence_pause_pre(d1, rate, **kw) * 1000 + len(clips[1]))
ls._block_segment = fake_segment
asm_calls = []
def fake_asm(segments, rates, starts):
    asm_calls.append((rates, starts))
    total = starts[2] + len(segments[2]) / 1000.0 / rates[2]
    return {"ok": True, "audio_path": "/tmp/fake_blocks.mp3", "duration_secs": total, "starts_secs": list(starts)}
ls._assemble_block_audio = fake_asm
import word_timing as WTM
WORD_OVERRIDES = {}
ONCE = [False]
def fake_transcribe(path, language="it"):
    # words of the narration placed where the fake plan says: sentence starts from the last assembly call
    rates, starts = asm_calls[-1]
    so = T.second_sentence_offsets(6)
    blocks_text = LAST_BLOCKS[0]
    out = []
    for b, text in enumerate(blocks_text):
        for k_, sent in enumerate(SPLIT(text)):
            t0 = starts[b] + (0 if k_ == 0 else so[b])
            for w_i, w in enumerate(sent.replace(".", "").replace(",", "").split()):
                out.append((w, t0 + 0.4 * w_i, t0 + 0.4 * w_i + 0.3))
    flat = [w for w, _, _ in out]
    for word, t in list(WORD_OVERRIDES.items()):
        out = [(w, (t if w.lower() == word else a), (t + 0.3 if w.lower() == word else b_)) for w, a, b_ in out]
    if ONCE[0]:
        WORD_OVERRIDES.clear()
    return out
WTM.transcribe_words = fake_transcribe
LAST_BLOCKS = [GOOD]
_orig_reply = ls._claude_text_reply
def _tracking_reply(client, prompt, max_tokens=1024):
    r = fake_reply(client, prompt, max_tokens)
    try:
        LAST_BLOCKS[0] = json.loads(r)["blocks"]
    except Exception:
        pass
    return r
ls._claude_text_reply = _tracking_reply
def run():
    return ls._block_narration(DESC, "Via X", PRICE, "v", AG, SEQ)
replies[:] = [json.dumps({"blocks": GOOD})]
r = run()
check("C1 first reply accepted -> ok, 3 synth calls, mode anchored/blocks/sentence_sync", r["ok"] and r["tts_calls"] == 3 and r["result"]["narration_mode"] == "anchored" and r["result"]["timeline"]["method"] == "blocks" and r["result"]["timeline"]["sentence_sync"] is True, r)
res = r["result"]; tl = res["timeline"]
check("C2 result has the keys the pipeline reads", all(k in res for k in ("narration_text", "audio_path", "speech_duration_secs", "scene_count", "video_duration_secs", "tts_calls_used", "was_trimmed", "sync", "error", "script_attempts", "timeline")))
check("C3 timeline: 6 targets, speeds inside limits, 5 anchors (scenes 2-6, one per sentence)", len(tl["targets"]) == 6 and all(0.8 - 1e-3 <= s <= 1.25 + 1e-3 for s in tl["speeds"]) and [a["scene"] for a in tl["anchors"]] == [2, 3, 4, 5, 6], tl)
check("C4 narration text = the 3 blocks joined; price not spoken", res["narration_text"] == " ".join(GOOD) and "1.680" not in res["narration_text"])
offs = [a["offset_secs"] for a in tl["anchor_offsets"]]
check("C5 every scene is on screen at (or just before) the sentence that talks about it (-1.1..+0.3 s)", all(-1.1 - 1e-6 <= o <= 0.3 + 1e-6 for o in offs), offs)
check("C6 second sentences start where the log can verify them (second_start recorded per block)", all("second_start" in b and "sentence_secs" in b for b in tl["blocks"]))
# a sentence that is far too long for its scene -> sync feedback to THAT sentence, then fixed
LONG = "La cucina è abitabile, molto funzionale e con il piano di lavoro."
SENT[LONG] = 7.9
b_long = list(GOOD); b_long[1] = LONG + " Ci sono 5 camere da letto, tutte molto luminose."
replies[:] = [json.dumps({"blocks": b_long}), json.dumps({"blocks": GOOD})]
synth_calls.clear(); prompts.clear()
r = run()
check("C7 a sentence too long for its scene is sent back with the scene number, then accepted", r["ok"] and r["result"]["script_attempts"] == 2 and len(prompts) == 2 and ("sentence" in prompts[1] and "too long" in prompts[1]), prompts[-1][-500:] if len(prompts) > 1 else r)
SENT.pop(LONG, None)
check("C8 unchanged blocks are not synthesised again", r["tts_calls"] == 4 and len(synth_calls) == 4, synth_calls)
replies[:] = [json.dumps({"blocks": fact}), json.dumps({"blocks": GOOD})]
synth_calls.clear()
r = run()
check("C9 text rejected by the rules costs no TTS; ok on attempt 2", r["ok"] and r["result"]["script_attempts"] == 2 and r["tts_calls"] == 3, r.get("reason"))
replies[:] = [json.dumps({"blocks": fact})] * ls.BLOCK_MAX_ATTEMPTS
r = run()
check("C10 always rejected -> ok False with a reason, no exception", (not r["ok"]) and r["reason"], r)
replies[:] = ["not json"] * ls.BLOCK_MAX_ATTEMPTS
check("C11 garbage replies -> ok False", not run()["ok"])
replies[:] = [RuntimeError("boom")]
r = run()
check("C12 API error -> ok False, never raises", (not r["ok"]) and "boom" in r["reason"], r)
ls._synthesize_block = lambda t, v=None: {"ok": False}
replies[:] = [json.dumps({"blocks": GOOD})]
r = run()
check("C13 TTS failure -> ok False", (not r["ok"]) and "TTS" in r["reason"], r)
ls._synthesize_block = fake_synth
# last attempt: sentences cannot follow their scenes -> block starts only (sentence_sync False), not a fallback to per_scene
LONG2 = "La cucina è abitabile, molto funzionale e con il piano di lavoro."
SENT[LONG2] = 12.0     # R5: 7.0 s now FITS (the joint search finds tempo+silences); 12 s cannot
b_long2 = list(GOOD); b_long2[1] = LONG2 + " Ci sono 5 camere da letto, tutte molto luminose."
replies[:] = [json.dumps({"blocks": b_long2})] * ls.BLOCK_MAX_ATTEMPTS
r = run()
check("C14 sentences never fit -> last attempt keeps the block starts only (sentence_sync False) or reports why", (r["ok"] and r["result"]["timeline"]["sentence_sync"] is False) or (not r["ok"] and r["reason"]), r.get("reason"))
SENT.pop(LONG2, None)

# a sentence far too SHORT for its picture: the block still fits its slot, but scene 3 would have to be sped up too much
SHORT = "La cucina è molto abitabile."
SENT[SHORT] = 0.3
b_short = list(GOOD); b_short[1] = SHORT + " Ci sono 5 camere da letto, tutte molto luminose."
replies[:] = [json.dumps({"blocks": b_short}), json.dumps({"blocks": GOOD})]
prompts.clear()
r = run()
check("C15 a sentence too short for its scene -> sync feedback names block 2 sentence 1 (scene 3) 'too short', then accepted",
      r["ok"] and len(prompts) == 2 and "Block 2, sentence 1 (scene 3)" in prompts[1] and "too short" in prompts[1], (r.get("reason"), prompts[-1][-400:]))
SENT.pop(SHORT, None)

# word check with the real audio
replies[:] = [json.dumps({"blocks": GOOD})]
WORD_OVERRIDES.clear()
r = run()
wc = r["result"]["timeline"]["word_check"]
check("C16 room words verified with the audio: checked, 3 rooms, 0 violations", r["ok"] and wc["checked"] and len(wc["rooms"]) == 3 and wc["violations"] == 0, wc)
WORD_OVERRIDES["cucina"] = 14.5          # the kitchen word is said while the bedroom picture is on screen
ONCE[0] = True                           # ... only the first time (the retry is "fixed")
replies[:] = [json.dumps({"blocks": GOOD}), json.dumps({"blocks": GOOD})]
prompts.clear()
r = run()
check("C17 a room word said outside its picture is sent back with word and time; the retry is accepted", r["ok"] and r["result"]["script_attempts"] == 2 and len(prompts) == 2 and "the word 'cucina' is said at 14.5" in prompts[1], (r.get("reason"), prompts[-1][-300:]))
ONCE[0] = False
WORD_OVERRIDES.clear()
replies[:] = [json.dumps({"blocks": GOOD})]
WTM.transcribe_words = lambda path, language="it": None
r = run()
check("C18 recogniser not available -> accepted, word_check says NOT verified", r["ok"] and r["result"]["timeline"]["word_check"]["checked"] is False and "NOT verified" in r["result"]["timeline"]["word_check"].get("note", ""), r)
WTM.transcribe_words = fake_transcribe

# Patch R3 (draft dd4d2b79): a reply that is not JSON must NOT erase the measured-duration feedback of the attempt before
SENT[LONG] = 7.9
replies[:] = [json.dumps({"blocks": b_long}), "Certo! Ecco il testo richiesto.", json.dumps({"blocks": GOOD})]
prompts.clear()
r = run()
check("C19 non-JSON reply keeps the previous feedback (sentence too long) and adds the JSON reminder; next reply accepted",
      r["ok"] and len(prompts) == 3 and "too long" in prompts[2] and "not a JSON object" in prompts[2] and "Your previous blocks were" in prompts[2],
      (r.get("reason"), prompts[-1][-500:]))
SENT.pop(LONG, None)
# Patch R3: generic "servizi" is not a room name; "doppi servizi" / "servizi igienici" are
import scene_script as _ssr3
check("B17 'servizi completi' names no room; 'doppi servizi' and 'servizi igienici' name the bathrooms",
      _ssr3.named_rooms("Una proprietà con doppio ingresso e servizi completi.") == set()
      and _ssr3.named_rooms("La proprietà dispone di doppi servizi.") == {"bathrooms"}
      and _ssr3.named_rooms("Ci sono due servizi igienici.") == {"bathrooms"})

# Patch R4: the closing invitation is spoken as its own sentence (after a real pause), only at synthesis time
import scene_script as _ssr4
check("B18 closing clause -> own sentence; other texts unchanged",
      _ssr4.closing_as_sentence("Il giardino è di 3000 metri quadri, contatta Coldwell Banker.", "Coldwell Banker") == "Il giardino è di 3000 metri quadri. Contatta Coldwell Banker."
      and _ssr4.closing_as_sentence("Il giardino è ampio, luminoso e curato.", "Coldwell Banker") == "Il giardino è ampio, luminoso e curato."
      and _ssr4.closing_as_sentence("Il giardino è di 3000 metri quadri, contatta Coldwell Banker.", None) == "Il giardino è di 3000 metri quadri, contatta Coldwell Banker."
      and _ssr4.closing_as_sentence("Giardino di 60 mq, ampio, contatta COLDWELL BANKER!", "Coldwell Banker") == "Giardino di 60 mq, ampio. Contatta COLDWELL BANKER.")
synth_calls.clear()
replies[:] = [json.dumps({"blocks": GOOD})]
r = run()
check("C20 only the last block is sent to the voice with the closing as its own sentence; narration_text keeps the 3 blocks as written",
      r["ok"] and synth_calls[2].endswith(". Contatta Coldwell Banker.") and synth_calls[0] == GOOD[0] and synth_calls[1] == GOOD[1] and r["result"]["narration_text"] == " ".join(GOOD), synth_calls)
# the real _synthesize_block: 3 spoken sentences -> 2 timing units; the 2nd = sentence 2 + CLOSING_PAUSE + closing
import narration as _nar
_o_syn, _o_join = _nar.synthesize_sentences, _nar.join_clips
_nar.synthesize_sentences = lambda text, voice_id=None, tmp_parent=None: {"ok": True, "sentences": ["a", "b", "c"], "error": None, "clips": [Seg(1000), Seg(2000), Seg(1500)]}
_nar.join_clips = lambda clips, pause_ms=380: Seg(sum(len(c) for c in clips) + pause_ms * (len(clips) - 1))
_syn3 = _REAL_SYNTH("A. B. Contatta X.", "v")
_nar.synthesize_sentences = lambda text, voice_id=None, tmp_parent=None: {"ok": True, "sentences": ["a", "b"], "error": None, "clips": [Seg(1000), Seg(2000)]}
_syn2 = _REAL_SYNTH("A. B.", "v")
_nar.synthesize_sentences, _nar.join_clips = _o_syn, _o_join
check("C21 real _synthesize_block: 3 sentences -> sentence_secs [1.0, 2.0 + 0.6 + 1.5 = 4.1]; 2 sentences unchanged",
      _syn3["ok"] and _syn3["sentence_secs"] == [1.0, 4.1] and len(_syn3["clips"]) == 2 and _syn2["ok"] and _syn2["sentence_secs"] == [1.0, 2.0], (_syn3, _syn2))

# retry helper shared
n = {"c": 0}
def flaky():
    n["c"] += 1
    return {"ok": n["c"] >= 2}
ls.time.sleep = lambda s: None
check("C12 _retry_tts retries then succeeds", ls._retry_tts(flaky, 3)["ok"] and n["c"] == 2)

# ---------------- D. wiring
src = open("listing_scraper.py").read()
gen = src[src.index("def generate_narration_and_derive_scenes("):]
check("D1 generate_narration_and_derive_scenes calls _block_narration under the same flag", "_block_narration(" in gen and "anchored_timeline_enabled()" in gen)
check("D2 _measure_tts_duration uses the shared _retry_tts", "_retry_tts(lambda: _measure_tts_duration_once" in src)
nsrc = open("narration.py").read()
check("D3 narration has join_clips / stretch_audio / assemble_blocks", all(f"def {f}(" in nsrc for f in ("join_clips", "stretch_audio", "assemble_blocks")))
api = open("api_server.py").read()
check("D4 api_server still reads the anchored timeline targets", '_tl.get("mode") == "anchored"' in api)

# ---------------- E. Patch R5 (2026-10-25): one authority (clip speeds) + word budget of the last sentence
import scene_timing as _T5
_ok5 = _T5.plan_blocks_joint([[4.3, 4.8], [3.2, 3.8], [3.5, 5.9]])
_ok6 = _T5.plan_blocks_joint([[4.3, 4.8], [3.2, 3.8], [3.0, 6.1]])
_bad = _T5.plan_blocks_joint([[4.3, 4.8], [3.2, 3.8], [3.1, 6.7]])
check("E1 real attempts of draft d6ca1445 (last sentence 5.9 s and 6.1 s) fit now (the old pre-filter rejected both)",
      _ok5["ok"] and _ok6["ok"] and all(0.8 - 1e-3 <= c["speed"] <= 1.25 + 1e-3 for c in _ok5["clip_plan"]["clips"]), (_ok5["problems"], _ok6["problems"]))
check("E2 a really too long last sentence (6.7 s) is reported as clip 5 too_slow with the seconds, ok False",
      (not _bad["ok"]) and _bad["problems"] and _bad["problems"][0]["clip"] == 5 and _bad["problems"][0]["kind"] == "too_slow" and _bad["violation"] > 0.3, _bad)
check("E3 the plan keeps tempo inside 0.92-1.10, silences inside 0.3-1.6 and gives the starts the audio assembly needs",
      all(0.92 - 1e-9 <= r <= 1.10 + 1e-9 for r in _ok5["rates"]) and all(0.3 - 1e-9 <= g <= 1.6 + 1e-9 for g in _ok5["gaps"]) and len(_ok5["starts"]) == 3 and _ok5["starts"][0] == 0.0, _ok5)
cb = ss.closing_budget("Gallo Immobiliare"); cb_long = ss.closing_budget("Immobiliare Sant Agnese e Figli"); cb_none = ss.closing_budget(None)
check("E4 closing budget: 'contatta Gallo Immobiliare' = 3 words -> fact <= 8 of 11; a long agency name leaves at least 3 words of fact; no name works",
      cb == {"invitation": 3, "total": 11, "fact": 8} and cb_long["fact"] >= ss.LAST_SENTENCE_MIN_FACT_WORDS and cb_none["fact"] > 0, (cb, cb_long, cb_none))
long_last = list(GOOD); long_last[2] = "Gli spazi sono curati nei dettagli. Il giardino è di 3000 metri quadri e molto ben curato, contatta Coldwell Banker."
pr = ss.validate_blocks(long_last, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("E5 a last sentence over the budget is rejected with the numbers; the good one (10 words) is accepted", any("AT MOST 11 words" in x for x in pr), pr)
check("E6 the prompt gives the budget of the last sentence", "AT MOST 11 words in total" in pm and "contatta Coldwell Banker" in pm, pm[pm.find("EXCEPTION"):pm.find("EXCEPTION") + 200])
fs3 = ss.build_sync_feedback([{"clip": 5, "kind": "too_slow", "seconds_over": 0.2}], GOOD)
check("E7 feedback aims inside the limit, not at its edge: even 0.2 s over asks for at least 2 words", "at least" not in fs3 and "about 2 words" in fs3 and "not at its edge" in fs3, fs3)
src_rep = open("listing_scraper.py").read()
check("E8 the block loop uses plan_blocks_joint (no second pre-filter) and the old plan_blocks is not called any more",
      "st.plan_blocks_joint(" in src_rep and "st.plan_blocks(" not in src_rep)

print(f"\n{total - len(fails)}/{total} PASS")
sys.exit(1 if fails else 0)
