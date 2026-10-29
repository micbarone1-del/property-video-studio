"""2026-10-29: the Claude cost of a job when a call is made with ANOTHER model than the default (the photo-quality judge uses a second,
cheaper model). Real functions, fake client, no network. Prices come from listing_scraper.CLAUDE_PRICES (haiku 4.5 default 1/5 USD per
M tokens, haiku 5.5 0.10/0.50), USD_TO_EUR 0.93."""
import io, os, sys, types, threading
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls
from PIL import Image

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def resp(i, o):
    return types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=i, output_tokens=o), content=[types.SimpleNamespace(type="text", text="ANSWER: ok none")])

DEF_1M = round((1.00 + 5.00) * ls.USD_TO_EUR, 4)       # 1M in + 1M out at the default model
H55_1M = (0.10 + 0.50) * ls.USD_TO_EUR                  # same tokens at claude-haiku-5-5

ls.reset_claude_usage()
ls._track_claude(resp(1_000_000, 1_000_000))
c = ls.get_claude_cost()
check("K1 a call without model: tokens in the default counters, nothing extra, priced at the default model", c["input_tokens"] == 1_000_000 and c["output_tokens"] == 1_000_000 and c["extra_cost_eur"] == 0 and c["cost_eur"] == DEF_1M, c)
ls._track_claude(resp(1_000_000, 1_000_000), ls.MODEL)
check("K1b a call with model == MODEL is the same as no model", ls.get_claude_cost()["input_tokens"] == 2_000_000)

ls.reset_claude_usage()
ls._track_claude(resp(1_000_000, 1_000_000), "claude-haiku-5-5")
c = ls.get_claude_cost()
check("K2 a call with ANOTHER model: its own price in extra_cost_eur, default token counters untouched, call counted", c["input_tokens"] == 0 and c["output_tokens"] == 0 and c["calls"] == 1 and abs(c["extra_cost_eur"] - H55_1M) < 1e-6 and abs(c["cost_eur"] - round(H55_1M, 4)) < 1e-9, c)
ls._track_claude(resp(1_000_000, 1_000_000))
c = ls.get_claude_cost()
check("K3 both kinds add up in cost_eur (default 5.58 + haiku 5.5 0.558 EUR)", abs(c["cost_eur"] - round(DEF_1M + H55_1M, 4)) < 1e-9 and c["calls"] == 2, c)
ls.reset_claude_usage()
ls._track_claude(resp(1_000_000, 0), "some-unknown-model")
check("K4 an unknown model is priced like the default one, never zero", ls.get_claude_cost()["cost_eur"] == round(1.00 * ls.USD_TO_EUR, 4), ls.get_claude_cost())
ls.reset_claude_usage()
check("K5 reset clears the extra cost too", ls.get_claude_cost() == {"input_tokens": 0, "output_tokens": 0, "calls": 0, "extra_cost_eur": 0.0, "cost_eur": 0.0}, ls.get_claude_cost())
ls._track_claude(resp(10, 10), "claude-haiku-5-5")
m = ls.merge_claude_usage(None, ls.get_claude_cost())
check("K6 merge_claude_usage still works with the new dict (cost_eur summed)", m["cost_eur"] == ls.get_claude_cost()["cost_eur"] and m["calls"] == 1, m)

# K7: the real judge, two models, usage 1M/1M each -> cost of both
class Msgs:
    def create(self, **kw):
        return resp(1_000_000, 1_000_000)
class FakeClient:
    def __init__(self, api_key=None): self.messages = Msgs()
ls.anthropic.Anthropic = FakeClient
buf = io.BytesIO(); Image.new("RGB", (1200, 800), "gray").save(buf, "JPEG"); photo = buf.getvalue()
os.environ.pop("PVS_QUALITY_MODELS", None)
ls.reset_claude_usage()
r = ls.assess_photo_quality(photo, "t")
c = ls.get_claude_cost()
check("K7 the real judge with the default two models: verdict ok and the job cost counts BOTH calls at their own prices", r["verdict"] == "ok" and c["calls"] == 2 and abs(c["cost_eur"] - round(DEF_1M + H55_1M, 4)) < 1e-9, (r, c))

# K8: one-argument stub of _track_claude (ten older tests use it) still works for a call without model
seen = []
real_track = ls._track_claude
ls._track_claude = lambda r: seen.append("one-arg") or r
word, ok = ls._vision_word_from_b64(["x"], "q", "t")
ls._track_claude = real_track
check("K8 a call without model uses the one-argument _track_claude (old stubs and callers keep working)", seen == ["one-arg"] and ok, seen)

# K9: threads
ls.reset_claude_usage()
def work():
    for _ in range(50):
        ls._track_claude(resp(1000, 1000), "claude-haiku-5-5")
ths = [threading.Thread(target=work) for _ in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
unit = ls.claude_cost_eur(1000, 1000, "claude-haiku-5-5")
check("K9 8 threads x 50 calls: nothing lost (400 calls, extra cost = 400 x unit)", ls.get_claude_cost()["calls"] == 400 and abs(ls.get_claude_cost()["extra_cost_eur"] - 400 * unit) < 1e-4, ls.get_claude_cost())

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
