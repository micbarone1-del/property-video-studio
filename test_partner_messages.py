"""test_partner_messages.py - three public failure codes, Italian messages, language switch, reject endpoint wiring (2026-11-16). No network."""
import ast, sys
from pathlib import Path
import partner_messages as pm

fails = []
def check(n, ok):
    print(("PASS " if ok else "FAIL ") + n)
    if not ok: fails.append(n)

F = lambda **k: pm.public_failure(dict(status="failed", **k))
for internal in ("insufficient_photos", "insufficient_photo_quality", "unfurnished"):
    check("PM1 %s -> input_not_suitable" % internal, F(failure_code=internal)["failure_code"] == "input_not_suitable")
for internal in ("narration_failed", "internal_error", "generation_failed", None, "whatever_new"):
    check("PM2 %s -> generation_failed" % internal, F(failure_code=internal)["failure_code"] == "generation_failed")
check("PM3 operator rejection -> rejected_by_operator", F(failure_code="rejected_by_operator")["failure_code"] == "rejected_by_operator")
only = {F(failure_code=c)["failure_code"] for c in (None, "insufficient_photos", "narration_failed", "rejected_by_operator", "unfurnished", "x")}
check("PM4 only the three codes ever come out", only <= set(pm.CODES) and len(only) == 3)
gate = "Annuncio non idoneo al video standard: 3 foto utilizzabili (servono almeno 5). Mancano: bagni."
check("PM5 the Italian gate message that says what is missing is kept", F(failure_code="insufficient_photos", failure_public_message=gate)["failure_message"] == gate)
eng = F(failure_code="insufficient_photo_quality", failure_public_message="Not enough usable photos for this listing: x")["failure_message"]
check("PM6 an English internal message is replaced by the Italian one", eng == pm.MESSAGES["it"]["input_not_suitable"])
secret = F(failure_code="internal_error", failure_public_message="Traceback /var/www/secret", message="Error: boom /var/www")
check("PM7 technical text never reaches the partner", "Traceback" not in secret["failure_message"] and "/var/www" not in secret["failure_message"])
check("PM8 language: missing, unknown and 'IT' all fall back to it", all(pm.normalize_language(x) == "it" for x in (None, "", "pl", "xx", "IT", "it-IT")))
check("PM9 every message is Italian text", all(m for m in pm.MESSAGES["it"].values()) and set(pm.MESSAGES["it"]) == set(pm.CODES))
check("PM10 a job with another known language would use its own column (table-driven)", pm.public_failure({"status": "failed", "language": "it"})["failure_code"] == "generation_failed")

src = Path("api_server.py").read_text()
check("PM11 the public builder is the catalog", "partner_messages.public_failure(job)" in src)
check("PM12 request has an optional language, stored on the job", "language: str | None = None" in src and '"language": partner_messages.normalize_language(payload.language)' in src)
tree = ast.parse(src)
rj = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "reject_job")
rs = ast.get_source_segment(src, rj)
check("PM13 reject: only a not-released done/awaiting job, keep=True, partner told, nothing deleted",
      '"released"' in rs and '("done", "awaiting_approval")' in rs and '"keep": True' in rs and '_send_partner_webhook(job_id, "failed")' in rs
      and "unlink" not in rs and "rmtree" not in rs and "os.remove" not in rs)
check("PM14 the operator note stays internal", "operator_note" in rs and "operator_note" not in Path("partner_messages.py").read_text())
pipe = src.split("Pipeline failed:")[1][:900]
check("PM15 a failure in the first generation tells the partner and the operator", "_send_partner_webhook(job_id" in pipe and "_notify_operator" in pipe)
page = Path("operator_page.html").read_text()
check("PM16 the dashboard has the Rifiuta button", "rejectJob(" in page and "/reject" in page)
sys.exit(1 if fails else 0)
