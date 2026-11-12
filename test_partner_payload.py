"""test_partner_payload.py - the partner request is kept in the job as received (2026-11-12). No network, no app import."""
import json, partner_api as pa
fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)
raw = {"external_ref": "x1", "description": "d", "features": ["a"], "photos": [{"url": "https://u/1", "category": "kitchen", "order": 1}], "campo_nuovo": {"mq": 110}}
out = pa.received_payload_for_job(raw)
check("P1 every field is kept, also the unknown one", out == raw and out["campo_nuovo"]["mq"] == 110)
check("P2 it is a copy, not the same object", out is not raw)
check("P3 an unreadable value gives None, no exception", pa.received_payload_for_job({"a": object()}) is None)
big = {"d": "x" * 500}
cut = pa.received_payload_for_job(big, max_chars=100)
check("P4 a huge request is cut and flagged", cut["_truncated"] is True and len(cut["text"]) == 100 and cut["_chars"] > 100)
check("P5 the result can be saved as JSON", json.dumps(out) and json.dumps(cut))
check("P6 accents survive", pa.received_payload_for_job({"d": "caffè"})["d"] == "caffè")
src = open("api_server.py", encoding="utf-8").read()
i = src.index("async def create_video_from_partner"); j = src.index("async def _build_relinx_job_in_background")
body = src[i:j]
check("P7 the endpoint reads the raw body and stores it in the job", "request: Request" in body and "await request.json()" in body and '"partner_payload": _raw_payload' in body)
check("P8 a failure while reading never stops the job", "except Exception as _e:" in body and "_raw_payload = None" in body)
check("P9 only ONE place builds the stored payload", src.count("received_payload_for_job(") == 1)
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
raise SystemExit(1 if fails else 0)
