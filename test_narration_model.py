"""PVS_NARRATION_MODEL switch (2026-11-10): fake client, no API, no cost."""
import os
import listing_scraper as ls
FAILS = 0
def check(name, cond):
    global FAILS
    print(("PASS " if cond else "FAIL ") + name)
    FAILS += 0 if cond else 1
os.environ.pop("PVS_NARRATION_MODEL", None)
check("N1 default: narration model = MODEL", ls.narration_model() == ls.MODEL)
check("N2 default: tokens unchanged", ls.narration_tokens(1200) == 1200)
os.environ["PVS_NARRATION_MODEL"] = "claude-sonnet-5-5"
check("N3 switch on: sonnet", ls.narration_model() == "claude-sonnet-5-5")
check("N4 switch on: at least 3000 tokens, never lowered", ls.narration_tokens(1200) == 3000 and ls.narration_tokens(4000) == 4000)
class U: input_tokens = 1000; output_tokens = 2000
class B: type = "text"; text = " ok "
class R: usage = U(); content = [B()]
class M:
    kw = None
    def create(self, **kw):
        self.kw = kw
        return R()
class C:
    def __init__(self): self.messages = M()
c = C(); e0 = ls._claude_usage["extra_cost_eur"]
t = ls._claude_text_reply(c, "p", max_tokens=3000, model="claude-sonnet-5-5")
check("N5 sonnet call: model sent, text returned", c.messages.kw["model"] == "claude-sonnet-5-5" and t == "ok")
check("N6 sonnet cost goes to extra_cost_eur", ls._claude_usage["extra_cost_eur"] > e0)
c2 = C(); e1 = ls._claude_usage["extra_cost_eur"]
ls._claude_text_reply(c2, "p")
check("N7 default call: MODEL, no extra cost", c2.messages.kw["model"] == ls.MODEL and ls._claude_usage["extra_cost_eur"] == e1)
src = open("listing_scraper.py").read()
check("N8 no writing call left on fixed MODEL/2048", "client.messages.create(model=MODEL, max_tokens=2048," not in src)
check("N9 proofread untouched (Haiku, 600)", "_claude_text_reply(client, prompt, max_tokens=600)" in src)
print("FAILS:", FAILS)
