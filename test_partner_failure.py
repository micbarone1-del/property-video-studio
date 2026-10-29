"""2026-10-29: the partner API now says WHY a job failed (failure_code + failure_message). No network, no keys.
The real helper functions are cut out of api_server.py and executed, so this tests the shipped code, not a copy."""
import ast, os, sys, types
sys.path.insert(0, os.getcwd())
for name in ("anthropic",):
    try:
        __import__(name)
    except Exception:
        m = types.ModuleType(name); m.Anthropic = object; sys.modules[name] = m
import listing_scraper as ls

fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

src = open("api_server.py").read()
tree = ast.parse(src)
want_funcs = {"_map_internal_status_to_partner_status", "_partner_failure_fields", "_partner_status_payload"}
parts = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in want_funcs:
        parts.append(ast.get_source_segment(src, node))
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "PARTNER_FAILURE_GENERIC" for t in node.targets):
        parts.append(ast.get_source_segment(src, node))
ns = {}
exec("\n\n".join(parts), ns)
fields, payload = ns["_partner_failure_fields"], ns["_partner_status_payload"]

# P1-P4 failure fields
check("P1 completed/running job: no failure fields", fields({"status": "done"}) == {} and fields({"status": "running"}) == {})
f = fields({"status": "failed", "failure_code": "insufficient_photos", "failure_public_message": "Not enough usable photos for this listing: x"})
check("P2 code and message from the job", f == {"failure_code": "insufficient_photos", "failure_message": "Not enough usable photos for this listing: x"}, f)
g = fields({"status": "failed", "message": "Errore assemblaggio: Traceback secret path /var/www"})
check("P3 failed elsewhere (assembly, orphan): generic pair, internal text NOT leaked", g["failure_code"] == "generation_failed" and "Traceback" not in g["failure_message"] and "/var/www" not in g["failure_message"], g)
h = fields({"status": "failed", "failure_code": "internal_error"})
check("P4 code without a message still gets a sentence", bool(h["failure_message"]), h)

# P5-P8 shared payload
fj = {"status": "failed", "external_ref": "R1", "failure_code": "unfurnished", "failure_public_message": "msg"}
p = payload("abc", fj, "abc")
check("P5 payload failed: status failed + both fields", p["status"] == "failed" and p["failure_code"] == "unfurnished" and p["failure_message"] == "msg" and "video_url" not in p, p)
d = payload("abc", {"status": "done", "released": True, "external_ref": "R"}, "real9")
check("P6 payload completed released: video_url uses the download id, no failure fields", d["video_url"].endswith("/real9/download") and "failure_code" not in d and d["id"] == "abc", d)
d2 = payload("abc", {"status": "done", "released": False}, "abc")
check("P7 done but not released: in_review, no url", d2["status"] == "in_review" and "video_url" not in d2, d2)
check("P8 draft: in_review without failure", payload("a", {"status": "draft"}, "a")["status"] == "in_review")

# P9-P14 wiring (source level: one builder, used everywhere)
check("P9 GET by id uses the shared builder", "return _partner_status_payload(job_id, job, real_id)" in src)
check("P10 GET by external_ref uses the shared builder", "return _partner_status_payload(jid, job, jid)" in src)
check("P11 no leftover hand-built status dict in the two GETs", src.count('"status": _map_internal_status_to_partner_status(job.get("status"), released)') == 1)
check("P11b duplicate POST of a failed job also returns the reason", "**_partner_failure_fields(existing)" in src)
check("P12 failed webhook carries the fields", 'if event == "failed":' in src and "_partner_failure_fields(" in src.split('if event == "failed":')[1][:200])
for name, needle in (("P13a photo gaps", '"insufficient_photo_quality" if scraper.QUALITY_GAP_MARKER in gap_desc'), ("P13b narration", '"failure_code": "narration_failed"'),
                     ("P13c internal error", '"failure_code": "internal_error"'), ("P13d scope rejection", '"failure_public_message": acceptance["message"]')):
    check("P13 failure site sets code+message: " + name, needle in src)
check("P14 internal text never copied into the public message",
      'failure_public_message": f"Internal' not in src and "failure_public_message\": str(e" not in src and 'narration[\'error\']}",\n' not in src.split('"failure_code": "narration_failed"')[1][:160])

# P15-P16 quality marker is the single source of the phrase
photos = [{"quality_rejected": True}, {"quality_rejected": True}, {}]
note = ls._quality_gap_note(photos)
check("P15 quality gap note contains the marker", ls.QUALITY_GAP_MARKER in note and note.startswith(" 2 photo(s)"), note)
check("P16 no quality-rejected photo: empty note, no marker", ls._quality_gap_note([{}]) == "")

print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
