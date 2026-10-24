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

# ---------------- B. block script
DESC = ("Villa in vendita a Roma, Olgiata. Abbiamo il piacere di proporre villa unifamiliare di 650 metri quadri "
        "completamente ristrutturata, con giardino di 3000 metri quadri, 5 camere da letto e 4 bagni. Soggiorno ampio, "
        "cucina abitabile, terrazza. Prezzo 1.680.000 euro.")
AG = "Coldwell Banker"; PRICE = "€ 1.680.000"
SEQ = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
LABELS = [ls.CATEGORY_ITALIAN_LABELS.get(c, c) for c in SEQ]
GOOD = ["Coldwell Banker presenta una villa in vendita a Olgiata. Di 650 metri quadri, è completamente ristrutturata e piena di luce.",
        "La cucina è abitabile e gli spazi sono ampi. Ci sono 5 camere da letto dove riposare in assoluta tranquillità.",
        "I 4 bagni sono curati nei dettagli e il giardino di 3000 metri quadri è perfetto. Contatta Coldwell Banker per visitarla."]
from narration import split_into_sentences as SPLIT
pr = ss.validate_blocks(GOOD, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B1 good blocks accepted", pr == [], pr)
check("B2 parse_blocks reads a JSON object (also in a code fence)", ss.parse_blocks(json.dumps({"blocks": GOOD})) == GOOD and ss.parse_blocks("```json\n" + json.dumps({"blocks": GOOD}) + "\n```") == GOOD)
check("B3 parse_blocks rejects the wrong count / garbage", ss.parse_blocks(json.dumps({"blocks": GOOD[:2]})) is None and ss.parse_blocks("no") is None and ss.parse_blocks("") is None)
bad = list(GOOD); bad[0] = "Coldwell Banker presenta una villa in vendita a Olgiata, con un soggiorno ampio, una cucina abitabile e molta luce naturale."
pr = ss.validate_blocks(bad, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B4 room not shown in the block is rejected (cucina in block 1)", any("cucina" in x and "block 1" in x for x in pr), pr)
short = list(GOOD); short[1] = "La cucina è abitabile."
pr = ss.validate_blocks(short, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B5 block with too few words is rejected", any("block 2" in x and "words" in x for x in pr), pr)
fact = list(GOOD); fact[2] = "I 4 bagni sono curati nei dettagli e il giardino di 9000 metri quadri è perfetto. Contatta Coldwell Banker per visitarla."
pr = ss.validate_blocks(fact, DESC, AG, PRICE, split_fn=SPLIT, scene_sequence=SEQ)
check("B6 invented number is rejected by the fact check", len(pr) >= 1, pr)
fb = ss.build_block_feedback([{"block": 0, "kind": "too_long", "seconds_over": 1.0}], [10.0, 8.0, 8.0], GOOD)
check("B7 feedback names block 1, seconds, words to remove and keeps the rest", "Block 1" in fb and "10.0 s" in fb and "remove about" in fb and "EXACTLY" in fb, fb)
pm = ss.build_blocks_prompt(DESC, "Via X", AG, LABELS, SEQ)
check("B8 prompt lists the 6 scenes and the 3 blocks", "Scene 6" in pm and "Block 3" in pm and AG in pm)

# ---------------- C. orchestration with fakes
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
DUR = {}
synth_calls = []
def fake_synth(text, voice_id=None):
    synth_calls.append(text)
    return {"ok": True, "segment": ("seg", text), "duration_secs": DUR.get(text, len(text.split()) / 2.1)}
ls._synthesize_block = fake_synth
asm_calls = []
def fake_asm(segments, rates, starts):
    asm_calls.append((rates, starts))
    return {"ok": True, "audio_path": "/tmp/fake_blocks.mp3", "duration_secs": starts[2] + 8.5 / rates[2], "starts_secs": starts}
ls._assemble_block_audio = fake_asm
def run():
    return ls._block_narration(DESC, "Via X", PRICE, "v", AG, SEQ)
for k, t in zip(range(3), GOOD): DUR[t] = [8.9, 8.0, 8.6][k]
replies[:] = [json.dumps({"blocks": GOOD})]
r = run()
check("C1 first reply accepted -> ok, 3 synth calls, mode anchored/blocks", r["ok"] and r["tts_calls"] == 3 and r["result"]["narration_mode"] == "anchored" and r["result"]["timeline"]["method"] == "blocks", r)
res = r["result"]
check("C2 result has the keys the pipeline reads", all(k in res for k in ("narration_text", "audio_path", "speech_duration_secs", "scene_count", "video_duration_secs", "tts_calls_used", "was_trimmed", "sync", "error", "script_attempts", "timeline")))
tl = res["timeline"]
check("C3 timeline: 6 targets, speeds inside limits, 2 anchors at scenes 3 and 5", len(tl["targets"]) == 6 and all(0.8 - 1e-3 <= s <= 1.25 + 1e-3 for s in tl["speeds"]) and [a["scene"] for a in tl["anchors"]] == [3, 5], tl)
check("C4 narration text = the 3 blocks joined; price not spoken", res["narration_text"] == " ".join(GOOD) and "1.680" not in res["narration_text"])
# too long block 1 -> rewrite only that block
LONG = "Coldwell Banker presenta una villa in vendita a Olgiata. Di 650 metri quadri, è completamente ristrutturata, luminosa e circondata dal verde più bello."
DUR[LONG] = 11.8
replies[:] = [json.dumps({"blocks": [LONG, GOOD[1], GOOD[2]]}), json.dumps({"blocks": GOOD})]
synth_calls.clear(); prompts.clear()
r = run()
check("C5 too-long block -> feedback with seconds, rewritten, ok on attempt 2", r["ok"] and r["result"]["script_attempts"] == 2 and "Block 1" in prompts[1] and "11.8 s" in prompts[1], prompts[-1][-400:] if prompts else "")
check("C6 unchanged blocks are not synthesised again (4 calls, not 6)", r["tts_calls"] == 4 and len(synth_calls) == 4, synth_calls)
# fact error then good
replies[:] = [json.dumps({"blocks": fact}), json.dumps({"blocks": GOOD})]
synth_calls.clear()
r = run()
check("C7 rejected text costs no TTS; ok on attempt 2", r["ok"] and r["result"]["script_attempts"] == 2 and r["tts_calls"] == 3, r.get("reason"))
# never acceptable
replies[:] = [json.dumps({"blocks": fact})] * ls.BLOCK_MAX_ATTEMPTS
r = run()
check("C8 always rejected -> ok False with a reason, no exception", (not r["ok"]) and r["reason"], r)
replies[:] = ["not json"] * ls.BLOCK_MAX_ATTEMPTS
check("C9 garbage replies -> ok False", not run()["ok"])
replies[:] = [RuntimeError("boom")]
r = run()
check("C10 API error -> ok False, never raises", (not r["ok"]) and "boom" in r["reason"], r)
ls._synthesize_block = lambda t, v=None: {"ok": False}
replies[:] = [json.dumps({"blocks": GOOD})]
r = run()
check("C11 TTS failure -> ok False", (not r["ok"]) and "TTS" in r["reason"], r)
ls._synthesize_block = fake_synth

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

print(f"\n{total - len(fails)}/{total} PASS")
sys.exit(1 if fails else 0)
