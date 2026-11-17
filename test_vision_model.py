import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules: sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as ls
F = 0
def check(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)
sent = {}
ls.fetch_photo_bytes = lambda *a, **k: {"ok": True, "content": b"x"}
ls._image_b64_for_vision = lambda c, side=0: "B64"
def fake(imgs, prompt, label="", words=1, max_tokens=20, marker="", model=""):
    sent.update(prompt=prompt, words=words, max_tokens=max_tokens, marker=marker, model=model); return ("kitchen photo", True)
ls._vision_word_from_b64 = fake
os.environ.pop("PVS_VISION_MODEL", None)
check("default model is sonnet 5.5", ls.vision_model() == "claude-sonnet-5-5")
ls._vision_one_word("u", None, "Q", words=2)
check("default: model, marker and room to reason", sent["model"] == "claude-sonnet-5-5" and sent["marker"] == "answer:" and sent["max_tokens"] == 300)
check("default: the question is kept and the answer line asked", sent["prompt"].startswith("Q") and "ANSWER: <kind> <source>" in sent["prompt"])
ls._vision_one_word("u", None, "Q", words=1)
check("one word question gets the one-word answer line", "ANSWER: <word>" in sent["prompt"])
for v in ("", "default", "legacy", "OFF"):
    os.environ["PVS_VISION_MODEL"] = v; sent.clear()
    ls._vision_one_word("u", None, "Q", words=2)
    check("PVS_VISION_MODEL=%r: legacy path unchanged" % v, sent["prompt"] == "Q" and sent["model"] == "" and sent["marker"] == "" and sent["max_tokens"] == 20)
os.environ["PVS_VISION_MODEL"] = "claude-haiku-5-5"; check("any model id is accepted", ls.vision_model() == "claude-haiku-5-5")
os.environ.pop("PVS_VISION_MODEL")
sent.clear(); ls._vision_word_from_b64 = lambda imgs, prompt, label="", words=1, max_tokens=20, marker="", model="": (sent.update(model=model) or ("photo", True))
r = ls._confirm_render("u")
check("second look uses the vision model and keeps a photo verdict", sent["model"] == "claude-sonnet-5-5" and r == (False, True))
ls._vision_word_from_b64 = lambda *a, **k: ("render", True)
check("second look render verdict", ls._confirm_render("u") == (True, True))
print("RESULT", "ALL PASS" if not F else f"{F} FAIL"); sys.exit(1 if F else 0)
