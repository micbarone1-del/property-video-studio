"""2026-11-20: partner webhook with retries, stored result and ONE operator alert (partner_webhook.py + the glue in api_server). No network:
the pure state logic is tested directly, the glue is run from its own source with a fake requests."""
import asyncio, logging, os, sys, types
sys.path.insert(0, os.getcwd())
import partner_webhook as pw
ok_all = True
def chk(name, cond, info=""):
    global ok_all
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if (info and not cond) else ""))
    if not cond: ok_all = False

# --- pure state logic
s = pw.new_state("completed")
chk("PW1 new state is pending with no attempts", s["status"] == "pending" and s["attempts"] == 0 and s["event"] == "completed")
chk("PW2 success at the first attempt: delivered, no next attempt", pw.record_attempt(s, True, 200) == "delivered" and s["status"] == "delivered" and s["attempts"] == 1 and s["next_at"] is None and pw.retry_delay(s) is None)
s = pw.new_state("failed")
r1 = pw.record_attempt(s, False, 503); d1 = pw.retry_delay(s)
r2 = pw.record_attempt(s, True, 200)
chk("PW3 one failure then success: retry (60 s) then delivered, 2 attempts", (r1, d1, r2, s["attempts"], s["status"]) == ("retry", 60, "delivered", 2, "delivered"), (r1, d1, r2, s))
s = pw.new_state("completed")
seq = []; delays = []
for _ in range(4):
    seq.append(pw.record_attempt(s, False, None, "Timeout")); delays.append(pw.retry_delay(s))
chk("PW4 four failures: retry, retry, retry, failed; waits 60, 300, 900 then nothing", seq == ["retry", "retry", "retry", "failed"] and delays == [60, 300, 900, None] and s["status"] == "failed" and s["attempts"] == 4, (seq, delays))
chk("PW5 the stored error is the name or 'HTTP n', never a URL", s["last_error"] == "Timeout" and pw.new_state("x") is not None)
s = pw.new_state("completed"); pw.record_attempt(s, False, 503)
chk("PW6 an HTTP failure is stored as 'HTTP 503'", s["last_error"] == "HTTP 503" and s["last_http"] == 503)
chk("PW7 only 2xx counts as delivered", [pw.is_ok_http(c) for c in (200, 204, 301, 400, 500, None)] == [True, True, False, False, False, False])
jobs = {"a": {"callback_url": "u", "webhook_delivery": {"status": "pending"}}, "b": {"callback_url": "u", "webhook_delivery": {"status": "delivered"}},
        "c": {"webhook_delivery": {"status": "pending"}}, "d": {"callback_url": "u"}}
chk("PW8 startup resume picks only pending deliveries of jobs with a callback", [j for j, _ in pw.pending_event_jobs(jobs)] == ["a"])
html = pw.failure_html("jid1", {"external_ref": "E-9", "callback_url": "https://x/hook?t=SECRETTOKEN"}, {"event": "completed", "attempts": 4, "last_http": 503, "last_error": "HTTP 503"})
chk("PW9 the alert text names job, external_ref, event in Italian, attempts and never the callback URL or token", "jid1" in html and "E-9" in html and "completato" in html and "4 tentativi" in html and "SECRETTOKEN" not in html and "https://x" not in html)

# --- the glue, run from api_server's own source with a fake requests
src = open("api_server.py", encoding="utf-8").read()
i = src.index("_WEBHOOK_TASKS = set()"); j = src.index('@app.on_event("startup")\nasync def _resume_pending_webhooks')
seg = src[i:j]
calls = {"post": [], "notify": [], "saves": 0}
answers = []
def fake_post(url, data=None, headers=None, timeout=0):
    calls["post"].append(url)
    a = answers.pop(0)
    if isinstance(a, Exception): raise a
    return types.SimpleNamespace(status_code=a)
fake_requests = types.ModuleType("requests"); fake_requests.post = fake_post
sys.modules["requests"] = fake_requests
JOBS = {}
async def _notify_operator(job_id, event, subject, body_html, push_message, priority="default", tags=None):
    calls["notify"].append((job_id, event, body_html))
def _save_job(job_id): calls["saves"] += 1
ns = {"asyncio": asyncio, "os": os, "log": logging.getLogger("t"), "JOBS": JOBS, "partner_webhook": pw, "_save_job": _save_job,
      "_notify_operator": _notify_operator, "_partner_failure_fields": lambda j: {"failure_code": "generation_failed"}}
exec(compile(seg, "api_server_segment", "exec"), ns)
pw.RETRY_DELAYS = (0.01, 0.01, 0.01)   # the glue reads partner_webhook.RETRY_DELAYS through retry_delay / record_attempt

async def scenario():
    # A: delivered at once
    JOBS["A"] = {"callback_url": "https://cb/A?t=TOK", "external_ref": "EA", "status": "done"}
    answers[:] = [200]; calls["post"].clear()
    await ns["_send_partner_webhook"]("A", "completed")
    chk("PW10 delivered at the first attempt: one post, stored delivered, no retry task, job status untouched",
        len(calls["post"]) == 1 and JOBS["A"]["webhook_delivery"]["status"] == "delivered" and JOBS["A"]["status"] == "done" and not ns["_WEBHOOK_TASKS"])
    # B: 503 then 200
    JOBS["B"] = {"callback_url": "https://cb/B?t=TOK", "external_ref": "EB", "status": "failed"}
    answers[:] = [503, 200]; calls["post"].clear()
    await ns["_send_partner_webhook"]("B", "failed")
    chk("PW11 the first answer is returned without waiting for the retries (a retry task is pending)", JOBS["B"]["webhook_delivery"]["status"] == "pending" and len(ns["_WEBHOOK_TASKS"]) == 1)
    await asyncio.sleep(0.2)
    chk("PW12 the background retry delivers: 2 posts, delivered, 2 attempts, no alert", len(calls["post"]) == 2 and JOBS["B"]["webhook_delivery"]["status"] == "delivered" and JOBS["B"]["webhook_delivery"]["attempts"] == 2 and not calls["notify"])
    # C: all fail -> ONE alert
    JOBS["C"] = {"callback_url": "https://cb/C?t=TOK", "external_ref": "EC", "status": "done", "property_name": "Casa C"}
    answers[:] = [ConnectionError("https://cb/C?t=TOK refused")] * 4; calls["post"].clear(); calls["notify"].clear()
    await ns["_send_partner_webhook"]("C", "completed")
    await asyncio.sleep(0.3)
    st = JOBS["C"]["webhook_delivery"]
    chk("PW13 four failures: failed, 4 attempts, ONE operator alert, error stored by NAME only, job status untouched",
        st["status"] == "failed" and st["attempts"] == 4 and len(calls["post"]) == 4 and len(calls["notify"]) == 1 and st["last_error"] == "ConnectionError" and "TOK" not in str(st) and "TOK" not in calls["notify"][0][2] and JOBS["C"]["status"] == "done", (st, calls["notify"]))
    # D: replaced by a newer delivery -> the old retries stop
    JOBS["D"] = {"callback_url": "https://cb/D", "external_ref": "ED", "status": "done"}
    answers[:] = [500, 200]; calls["post"].clear()
    await ns["_send_partner_webhook"]("D", "completed")
    old_state = JOBS["D"]["webhook_delivery"]
    JOBS["D"]["webhook_delivery"] = pw.new_state("failed")   # a newer event took over
    await asyncio.sleep(0.2)
    chk("PW14 when a newer delivery replaces the old one, the old retries stop (no extra post)", len(calls["post"]) == 1 and old_state["status"] == "pending")
    # E: no callback -> nothing
    JOBS["E"] = {"external_ref": "EE"}; calls["post"].clear()
    await ns["_send_partner_webhook"]("E", "failed")
    chk("PW15 a job without callback_url does nothing", not calls["post"] and "webhook_delivery" not in JOBS["E"])
asyncio.run(scenario())

# --- source-level guards on the glue
send_body = src[src.index("async def _send_partner_webhook"):src.index('@app.on_event("startup")\nasync def _resume_pending_webhooks')]
chk("PW16 the first call never sleeps: retries go to a background task", "asyncio.sleep" not in send_body.split("async def _webhook_retry_loop")[0].split("async def _send_partner_webhook")[-1] and "asyncio.create_task(_webhook_retry_loop" in src)
chk("PW17 the webhook code never changes the job's own status", '["status"] =' not in seg and '["released"]' not in seg and 'job["status"]' not in seg)
chk("PW18 payload builder keeps the failure fields, signing stays optional with its warning", 'if event == "failed":' in seg and "_partner_failure_fields(" in seg and "X-Signature" in seg and "sending unsigned webhook" in seg)
chk("PW19 the error returned to the state is the exception NAME, not its text", "type(e).__name__" in seg and "str(e)" not in seg.split("async def _webhook_attempt")[0])
chk("PW20 a restart resumes pending deliveries", '@app.on_event("startup")\nasync def _resume_pending_webhooks' in src and "partner_webhook.pending_event_jobs(JOBS)" in src and "first_delay=30" in src)
print("ALL PASS" if ok_all else "SOME FAIL"); sys.exit(0 if ok_all else 1)
