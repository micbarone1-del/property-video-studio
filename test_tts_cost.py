"""Voiceover cost: one rate per TTS provider, narration text counted in the backend estimate, no second copy of the rate in the UI."""
import os
import sys

import cost_tracker as ct

res = []


def t(n, ok):
    res.append(ok)
    print(("PASS " if ok else "FAIL ") + n)


g = ct.GOOGLE_TTS_CHIRP3_HD_USD_PER_CHAR * ct.USD_TO_EUR
t("S1 google rate is USD 30 per 1M characters in EUR", abs(ct.tts_cost_per_char("google") - 0.00003 * 0.92) < 1e-12)
t("S2 388 characters on google cost about EUR 0.0107, not 0.1164", abs(388 * ct.tts_cost_per_char("google") - 0.0107) < 0.0001)
t("S3 elevenlabs keeps its configured rate", ct.tts_cost_per_char("elevenlabs") == ct.ELEVENLABS_COST_PER_CHAR)
old = os.environ.get("TTS_PROVIDER")
os.environ["TTS_PROVIDER"] = "google"
t("S4 the active provider comes from TTS_PROVIDER (google)", ct.tts_cost_per_char() == g)
os.environ["TTS_PROVIDER"] = "elevenlabs"
t("S5 the active provider comes from TTS_PROVIDER (elevenlabs)", ct.tts_cost_per_char() == ct.ELEVENLABS_COST_PER_CHAR)
os.environ["TTS_PROVIDER"] = "google"
scene = [{"duration": 5, "voiceover": ""}]
e = ct.estimate_job_cost(scene, model_tier="luma", narration_chars=388)
t("S6 narration text is counted in the backend estimate", e["tts_chars"] == 388 and abs(e["tts_eur"] - round(388 * g, 4)) < 1e-9)
e2 = ct.estimate_job_cost([{"duration": 5, "voiceover": "x" * 100}], model_tier="luma")
t("S7 per-scene voiceover still counted, default narration_chars is 0", e2["tts_chars"] == 100)
if old is None:
    os.environ.pop("TTS_PROVIDER", None)
else:
    os.environ["TTS_PROVIDER"] = old
ui = open("ui.html").read()
t("S8 the UI has no hard-coded voiceover rate and reads the server value", "EL_PER_CHAR" not in ui and "ttsCostPerChar" in ui and "cost_per_char_eur" in ui)
api = open("api_server.py").read()
t("S9 the API exposes the rate and passes the narration length twice", api.count("narration_chars=len(narration") == 2 and "cost_per_char_eur" in api)
print(str(sum(res)) + "/" + str(len(res)))
sys.exit(0 if all(res) else 1)
