"""test_luma_credits.py - the Luma balance in the credit check (2026-11-23). No network, no key: requests.get is replaced. Prints PASS/FAIL per case, exit 1 on any FAIL.
  python3 test_luma_credits.py"""
import io
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ["LUMA_API_KEY"] = "luma-secret-key-for-tests-0123456789"
import credit_monitor as cm
import requests

HERE = Path(__file__).resolve().parent
FAILS = []
CALLS = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ((" - " + str(info)) if info and not ok else ""))
    if not ok:
        FAILS.append(name)


class R:
    def __init__(self, code=200, body=None, text=None):
        self.status_code, self._b, self.text = code, body, text if text is not None else json.dumps(body)

    def json(self):
        if self._b is None:
            raise ValueError("no json")
        return self._b

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def answer(resp=None, exc=None):
    def fake_get(url, **kw):
        CALLS.append((url, kw))
        if exc:
            raise exc
        return resp
    cm.requests.get = fake_get


# L1 normal: the real answer shape
answer(R(200, {"balance_credits": 17779}))
r = cm.get_luma_credits()
check("L1 normal balance: ok, credits, dollars", r["ok"] and r["credits"] == 17779 and abs(r["usd"] - 53.34) < 0.01 and r["error"] is None, r)
check("L1b request: right URL, bearer header, timeout", CALLS[-1][0] == "https://agents.lumalabs.ai/v1/credits" and CALLS[-1][1]["headers"]["Authorization"].startswith("Bearer ") and CALLS[-1][1]["timeout"] <= 15)
# L2/L3 threshold: >= is ok
answer(R(200, {"balance_credits": cm.LUMA_THRESHOLD - 1}))
check("L2 just below the threshold: not ok", cm.get_luma_credits()["ok"] is False)
answer(R(200, {"balance_credits": cm.LUMA_THRESHOLD}))
check("L3 exactly the threshold: ok", cm.get_luma_credits()["ok"] is True)
answer(R(200, {"balance_credits": 0}))
r = cm.get_luma_credits()
check("L3b zero balance: not ok, 0 credits", r["ok"] is False and r["credits"] == 0, r)
# L4 key refused
for code in (401, 403):
    answer(R(code, {"detail": "bad key"}))
    r = cm.get_luma_credits()
    check(f"L4 HTTP {code}: not ok, says the key is refused", r["ok"] is False and r["credits"] is None and "chiave" in r["error"], r)
# L5-L8 hiccups never raise a false alarm
for label, resp, exc in (("L5 HTTP 500", R(500, {}), None), ("L6 timeout", None, requests.exceptions.Timeout("slow")),
                         ("L7 odd answer (no balance field)", R(200, {"hello": 1}), None), ("L8 answer is not JSON", R(200, None, "<html>"), None),
                         ("L8b balance is text", R(200, {"balance_credits": "many"}), None)):
    answer(resp, exc)
    r = cm.get_luma_credits()
    check(label + ": ok=True with the error noted", r["ok"] is True and r["credits"] is None and r["error"], r)
# L9 no key -> no request
n = len(CALLS)
os.environ["LUMA_API_KEY"] = ""
answer(R(200, {"balance_credits": 1}))
r = cm.get_luma_credits()
check("L9 no key: ok, no request made", r["ok"] and r["error"] == "LUMA_API_KEY not set" and len(CALLS) == n, r)
os.environ["LUMA_API_KEY"] = "luma-secret-key-for-tests-0123456789"
# L10 the key never shows up (result, log)
buf = io.StringIO()
h = logging.StreamHandler(buf)
cm.log.addHandler(h)
cm.log.setLevel(logging.DEBUG)
answer(None, requests.exceptions.ConnectionError("failed for Bearer luma-secret-key-for-tests-0123456789"))
r = cm.get_luma_credits()
cm.log.removeHandler(h)
check("L10 the key is not in the result nor in the log", "luma-secret-key" not in json.dumps(r) and "luma-secret-key" not in buf.getvalue(), (r, buf.getvalue()))
# L11 combined status
cm.get_fal_credits = lambda: {"balance": 16.8, "ok": True, "error": None}
cm.get_elevenlabs_credits = lambda: {"characters_remaining": None, "ok": True, "error": None}
cm.get_anthropic_status = lambda: {"ok": True, "reachable": True, "error": None}
answer(R(200, {"balance_credits": 17779}))
s = cm.get_all_credits()
check("L11 all fine: luma in the answer, any_low False", s["luma"]["credits"] == 17779 and s["any_low"] is False, s)
answer(R(200, {"balance_credits": 100}))
s = cm.get_all_credits()
check("L12 low Luma alone makes any_low True", s["any_low"] is True and s["fal"]["ok"] and s["luma"]["ok"] is False, s)
answer(R(401, {}))
check("L13 refused Luma key makes any_low True", cm.get_all_credits()["any_low"] is True)
# L14 the alert mail has a Luma row, once, with the numbers
sent = []
cm.send_alert_email = lambda subject, body: sent.append((subject, body)) or True
answer(R(200, {"balance_credits": 1234}))
cm.check_and_alert("job1", "Casa")
check("L14 alert mail sent with a Luma row", len(sent) == 1 and "<strong>Luma</strong>" in sent[0][1] and "1,234" in sent[0][1] and sent[0][1].count("<strong>Luma</strong>") == 1, sent[:1])
sent.clear()
answer(R(200, {"balance_credits": 17779}))
cm.check_and_alert("job1", "Casa")
check("L15 healthy balance: no mail", not sent)
# L16 the maintenance line
import maintenance_scheduler as ms
ms.credit_monitor.get_luma_credits = cm.get_luma_credits
answer(R(200, {"balance_credits": 17779}))
c = ms.check_credits()
check("L16 maintenance: ok, detail shows Luma credits and dollars", c["status"] == "ok" and "Luma: 17,779 crediti (circa $53)" in c["detail"], c)
answer(R(200, {"balance_credits": 500}))
c = ms.check_credits()
check("L17 maintenance: low Luma -> red", c["status"] == "red" and "Luma: 500 crediti" in c["detail"], c)
answer(R(401, {}))
c = ms.check_credits()
check("L18 maintenance: refused key -> red, says why", c["status"] == "red" and "rifiutato la chiave" in c["detail"], c)
# L19 ONE reader: the URL lives only in credit_monitor.py
hits = [p.name for p in HERE.glob("*.py") if p.name not in ("test_luma_credits.py", "patch_luma.py") and "v1/credits" in p.read_text(errors="ignore")]
check("L19 the balance URL is read in one module only", sorted(hits) in (["credit_monitor.py"], ["credit_monitor.py", "fake_providers.py"]), hits)
# L20 the fake instance answers the same shape
fp = (HERE / "fake_providers.py").read_text()
check("L20 fake provider has /v1/credits with balance_credits", '/v1/credits' in fp and '"balance_credits"' in fp)
# L21 banner: the script in ui.html still parses and has the Luma row
ui = (HERE / "ui.html").read_text(encoding="utf-8")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", ui, re.S)
big = max(scripts, key=len)
Path("/tmp/_ui_check.js").write_text(big, encoding="utf-8")
try:
    ok = subprocess.run(["node", "--check", "/tmp/_ui_check.js"], capture_output=True, text=True, timeout=60)
    check("L21 ui.html script parses (node --check)", ok.returncode == 0, ok.stderr[:300])
except FileNotFoundError:
    print("SKIP L21 (node not installed)")
check("L22 banner has the Luma row once", ui.count("data.luma && !data.luma.ok") == 1)
print(f"test_luma_credits FAILS {len(FAILS)}")
sys.exit(1 if FAILS else 0)
