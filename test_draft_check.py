"""Unit tests for draft_check.evaluate (synthetic metas, no network, no cost)."""
import copy, sys
import draft_check as dc
import listing_scraper as ls

def good():
    cats = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
    return {"status": "draft", "narration_mode": "per_scene", "narration_duration_secs": 29.0,
            "narration_text": "Splendida villa. Contatta l'agenzia per visitarla.",
            "scenes_config": [{"category": c, "duration": 5, "space_type": "large", "pov_movement": "outward_view" if c == "outdoor" else "walk_in_explore"} for c in cats],
            "selection_report": {"candidates_by_category": {"exterior": 2, "outdoor": 1}},
            "claude_usage": {"cost_eur": 0.12}}

def ids(m, **kw): return [(l, i) for l, i, _ in dc.evaluate(m, **kw) if l in ("FAIL", "WARN")]
res = []
def t(name, ok): res.append(ok); print(("PASS " if ok else "FAIL ") + name)

t("T1 good draft has no FAIL/WARN", ids(good()) == [])
m = good(); m["status"] = "preparing"; t("T2 preparing is not checkable", ids(m) == [("FAIL", "C1")])
m = good(); m["status"] = "done"; t("T2b finished job is checked", ids(m) == [])
m = good(); m["narration_mode"] = "single_text"; t("T3 single_text fails", ("FAIL", "C2") in ids(m))
m = good(); m["narration_duration_secs"] = 40; t("T4 voice too long", ("FAIL", "C3") in ids(m))
m = good(); m["scenes_config"].pop(); t("T5 five scenes", ("FAIL", "C4") in ids(m))
t("T6 duplicate photo", ("FAIL", "C5") in ids(good(), image_hashes=["a", "b", "a", "c", "d", "e"]))
m = good(); m["scenes_config"][5]["category"] = "exterior"; t("T7 repeated category warns", ("WARN", "C6") in ids(m))
m = good(); m["scenes_config"][1]["space_type"] = "corridor"; t("T8 living read as corridor only warns (the page label wins)", ("WARN", "C7") in ids(m))
m = good(); m["scenes_config"][5]["category"] = "kitchen"; t("T9 missing outdoor warns", ("WARN", "C8") in ids(m))
t("T10 pause 3 s warns", ("WARN", "C9") in ids(good(), silences=[3.0]))
t("T11 pause 5 s fails", ("FAIL", "C9") in ids(good(), silences=[5.0]))
m = good(); m["narration_text"] = "Bella casa."; t("T12 no contact sentence", ("FAIL", "C10") in ids(m))
m = good(); m["narration_text"] += " Costa 300.000 euro."; t("T13 price spoken", ("FAIL", "C11") in ids(m))
m = good(); m["scenes_config"][5]["pov_movement"] = "walk_in_gentle"; t("T14 outdoor wrong move", ("WARN", "C12") in ids(m))
m = good(); m["claude_usage"]["cost_eur"] = 2; t("T15 claude cost high", ("WARN", "C13") in ids(m))
t("T16 speech band equals listing_scraper", (dc.SPEECH_MIN, dc.SPEECH_MAX) == (ls.STANDARD_MIN_SPEECH_SECS, ls.STANDARD_MAX_SPEECH_SECS))
print(f"{sum(res)}/{len(res)}"); sys.exit(0 if all(res) else 1)
