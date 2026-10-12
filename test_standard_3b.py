"""3B (2026-10-12): fixed 6-scene standard video, speech band 24-28 s, acceptance rule. No network, no API key, no TTS."""
import os, sys, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def ph(cat, n, prefix="u"):
    return [{"url": f"{prefix}_{cat}_{i}", "category": cat} for i in range(n)]

# ---- acceptance rule
full = ph("exterior",1)+ph("living",2)+ph("kitchen",1)+ph("bedrooms",2)+ph("bathrooms",1)+ph("outdoor",1)
r = ls.check_listing_acceptance(full)
check("A1 full listing accepted", r["ok"] and r["code"] is None and r["usable_photos"] == 8 and len(r["environment_types"]) == 6, r)
r = ls.check_listing_acceptance(ph("living",2)+ph("kitchen",1)+ph("bedrooms",1)+ph("bathrooms",1))
check("A2 exactly 5 photos / 4 types accepted (boundary)", r["ok"], r)
r = ls.check_listing_acceptance(ph("living",1)+ph("kitchen",1)+ph("bedrooms",1)+ph("bathrooms",1))
check("A3 4 photos rejected even with 4 types", (not r["ok"]) and r["code"] == "insufficient_photos" and r["usable_photos"] == 4, r)
r = ls.check_listing_acceptance(ph("living",4)+ph("kitchen",2)+ph("bedrooms",2))
check("A4 8 photos but only 3 types rejected", (not r["ok"]) and len(r["environment_types"]) == 3 and "Mancano" in r["message"] and "bagni" in r["message"].split("Mancano")[1], r)
r = ls.check_listing_acceptance(ph("exterior",6)+ph("outdoor",5))
check("A5 exterior-only listing rejected with the explained reason", (not r["ok"]) and "solo esterni" in r["message"], r)
dup = [{"url": "same", "category": "living"}]*6 + ph("kitchen",1)+ph("bedrooms",1)+ph("bathrooms",1)
r = ls.check_listing_acceptance(dup)
check("A6 duplicate URLs counted once (4 usable -> rejected)", (not r["ok"]) and r["usable_photos"] == 4, r)
unc = ph("living",2)+ph("kitchen",1)+ph("bedrooms",1)+ph("bathrooms",1)+[{"url":"x","category":"uncategorized"},{"url":"y","category":"laundry"},{"url":"z","category":None},{"url":None,"category":"living"}]
r = ls.check_listing_acceptance(unc)
check("A7 uncategorized / non-standard categories / missing url are not usable", r["ok"] and r["usable_photos"] == 5, r)
r = ls.check_listing_acceptance([])
check("A8 empty list rejected without crash", (not r["ok"]) and r["usable_photos"] == 0 and "nessuno" in r["message"], r)
check("A9 message states what is required and what was found", "almeno 5 foto" in ls.check_listing_acceptance(ph("living",2))["message"] and "soggiorno" in ls.check_listing_acceptance(ph("living",2))["message"])

# ---- fixed 6 scenes, band 24-28
check("B1 constants", ls.STANDARD_SCENES == 6 and ls.STANDARD_MIN_SPEECH_SECS == 24.0 and ls.STANDARD_MAX_SPEECH_SECS == 28.0, (ls.STANDARD_SCENES, ls.STANDARD_MAX_SPEECH_SECS))

prompts = []
class Msgs:
    def create(self, **kw):
        txt = kw["messages"][0]["content"]
        prompts.append(txt if isinstance(txt, str) else "")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="testo narrazione di prova " * 10)])
class FakeClient:
    def __init__(self, api_key=None): self.messages = Msgs()
ls.anthropic.Anthropic = FakeClient
ls._track_claude = lambda r: r
queue = []; trims = []
def fake_measure(text, voice_id=None, attempts=1):
    return {"ok": True, "duration_secs": queue.pop(0), "audio_path": "/tmp/fake.mp3"}
ls._measure_tts_duration = fake_measure
def fake_trim(path, target, search_window_secs=4.0):
    trims.append(target); return path
ls._fade_out_and_trim = fake_trim

def run(durations, premium=False):
    queue[:] = list(durations); trims.clear(); prompts.clear()
    return ls.generate_narration_and_derive_scenes("desc", "via X", "100", None, premium, "Agenzia Test", ["living"])

o = run([26.0])
check("N1 26 s speech -> exactly 6 scenes / 30 s, one TTS call", o["ok"] and o["scene_count"] == 6 and o["video_duration_secs"] == 30 and o["tts_calls_used"] == 1 and not o["was_trimmed"], o)
o = run([21.0, 25.0])
check("N2 21 s speech (below 24) -> extend pass, 6 scenes", o["ok"] and o["scene_count"] == 6 and o["tts_calls_used"] == 2 and abs(o["speech_duration_secs"]-25.0) < 1e-6, o)
o = run([33.0, 27.0])
check("N3 33 s speech (above 28) -> shorten pass, 6 scenes", o["ok"] and o["scene_count"] == 6 and o["tts_calls_used"] == 2 and not o["was_trimmed"], o)
o = run([33.0, 31.0])
check("N4 still too long after the pass -> hard cap at 28 s, still 6 scenes", o["scene_count"] == 6 and o["was_trimmed"] and trims == [28.0] and o["speech_duration_secs"] == 28.0, (o, trims))
o = run([24.0]); o2 = run([28.0])
check("N5 band edges 24 and 28 accepted without correction", o["tts_calls_used"] == 1 and o["scene_count"] == 6 and o2["tts_calls_used"] == 1 and o2["scene_count"] == 6)
o = run([28.0]); check("N6 28 s needs no trim (1+28+1 = 30)", not o["was_trimmed"] and trims == [])
run([26.0])
check("N7 standard prompt asks for about 26 seconds / 65-75 words", any("about 26 seconds" in p for p in prompts))
o = run([53.0], premium=True)
check("N8 premium unchanged: 53 s speech (its own band floor) -> 11 scenes, no correction, no trim", o["scene_count"] == 11 and o["tts_calls_used"] == 1 and not o["was_trimmed"], o)
o = run([20.0, 21.0], premium=True)
check("N9 premium below its own band still gets its extend pass (11 scenes minimum)", o["tts_calls_used"] == 2 and o["scene_count"] == 11, o)

# ---- selection always yields 6 photos for 6 scenes (ranking stubbed: single candidates -> no vision call)
ls.rank_photos_by_quality = lambda cat, c, max_to_compare=6: ls._tag_rank(c, "single_candidate")
sel = ls.select_photos_for_scene_count(ph("living",3)+ph("kitchen",1)+ph("bedrooms",1)+ph("bathrooms",1), 6)
check("S1 4 types + surplus -> still 6 selected via backfill, no gap", sel["total_selected"] == 6 and not sel["gaps"], sel["total_selected"])
sel = ls.select_photos_for_scene_count(full, 6)
check("S2 full listing -> one photo per category (6 categories)", sorted(sel["selected"]) == sorted(ls.PRIORITY_ORDER) and all(len(v) >= 1 for v in sel["selected"].values()) and sel["total_selected"] == 6)

# ---- api_server wiring (static): both paths run the check before narration; premium bypass; code returned
api = open("api_server.py", encoding="utf-8").read()
i_url_check = api.index("check_listing_acceptance(extraction[\"photos\"])")
i_url_narr = api.index("scraper.generate_narration_and_derive_scenes", i_url_check - 3000)
check("W1 URL path: check runs before narration", i_url_check < api.index("scraper.generate_narration_and_derive_scenes,", i_url_check))
check("W2 URL path: premium skips the check; 422 carries code", "if not premium:\n        acceptance = scraper.check_listing_acceptance" in api and '"code": acceptance["code"]' in api)
i_rel_check = api.index("check_listing_acceptance(photos_for_selection)")
check("W3 Relinx path: check runs before narration and sets failure_code", i_rel_check < api.index("scraper.generate_narration_and_derive_scenes,", i_rel_check) and '"failure_code": acceptance["code"]' in api)
check("W4 Relinx path: photos built once (no second copy after narration)", api.count("photos_for_selection = []") == 1)
check("W5 acceptance saved in selection_report on both paths", api.count('selection_report["acceptance"] = acceptance') == 2)

print(f"RESULT: {'ALL PASS' if not fails else 'FAIL'} ({total - len(fails)}/{total})")
sys.exit(1 if fails else 0)
