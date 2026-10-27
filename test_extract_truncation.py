"""extract_listing: a cut-off answer (stop_reason max_tokens) gives a clear error, the cap is large enough, a complete answer still parses."""
import json
import sys
import listing_scraper as ls

res = []


def t(n, ok):
    res.append(ok)
    print(("PASS " if ok else "FAIL ") + n)


class Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class Resp:
    def __init__(self, text, stop):
        self.content = [Block(text)]
        self.stop_reason = stop


seen = {}


def fake_client(text, stop):
    class C:
        def __init__(self, **k):
            pass

        class messages:
            @staticmethod
            def create(**kw):
                seen.update(kw)
                return Resp(text, stop)
    return C


ls._track_claude = lambda r: r
ls.try_upgrade_resolution = lambda u: {"url": u, "upgraded": False}
URL = "https://www.immobiliare.it/annunci/1/"
cut = json.dumps({"photos": [{"url": "https://x/a.jpg", "label_it": "Salone"}]})[:-12]
ls.anthropic.Anthropic = fake_client(cut, "max_tokens")
r = ls.extract_listing(URL)
t("X1 truncated answer gives a clear error, not a JSON error", (not r["ok"]) and "Listing too large" in r["error"] and "JSON parse failed" not in r["error"])
t("X2 the cap sent to the API is at least 12000", seen.get("max_tokens", 0) >= 12000)
full = json.dumps({"photos": [{"url": "https://x/a.jpg", "label_it": "Salone", "category": "living"}], "description": "d", "price": None, "address": None})
ls.anthropic.Anthropic = fake_client(full, "end_turn")
r = ls.extract_listing(URL)
t("X3 complete answer still parses", r["ok"] and len(r["photos"]) == 1 and r["photos"][0]["category"] == "living")
ls.anthropic.Anthropic = fake_client("{" + chr(34) + "photos" + chr(34) + ": [ {oops", "end_turn")
r = ls.extract_listing(URL)
t("X4 genuinely malformed JSON keeps the JSON parse error", (not r["ok"]) and "JSON parse failed" in r["error"])
print(str(sum(res)) + "/" + str(len(res)))
sys.exit(0 if all(res) else 1)
