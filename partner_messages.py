"""partner_messages.py - the ONE place for what a partner (Relinx) is told when a job fails (2026-11-16, Michele).

Three public failure codes, no more:
  input_not_suitable   the listing cannot make a standard video (photos / environments / quality). The message says what is missing.
  generation_failed    any processing error (voice, generation, rework, assembly, internal). Generic on purpose: the technical reason stays in
                       the job (message, failure_code, rework_events) and in the server log, never in the partner response.
  rejected_by_operator the operator refused the finished video instead of releasing it.
The job keeps its own detailed internal code (insufficient_photos, narration_failed, ...); this module translates it for the outside.
Language: job["language"] (optional field of the partner request, default "it"). To add a language: add a column to MESSAGES. Nothing else.
"""
CODES = ("input_not_suitable", "generation_failed", "rejected_by_operator")
DEFAULT_LANGUAGE = "it"

MESSAGES = {
    "it": {
        "input_not_suitable": "Annuncio non idoneo al video standard: le foto disponibili non sono sufficienti o non hanno una qualita' adeguata.",
        "generation_failed": "Non e' stato possibile produrre il video. Il nostro team e' stato avvisato.",
        "rejected_by_operator": "Il video non ha superato il controllo di qualita' e non verra' consegnato. Il nostro team e' a disposizione per chiarimenti.",
    },
}

# internal codes (what the job stores) that mean "the input is not suitable"
INPUT_INTERNAL = {"insufficient_photos", "insufficient_photo_quality", "unfurnished", "input_not_suitable"}
# a message written by the acceptance gate in Italian says exactly what is missing: it is kept
_ITALIAN_MARKERS = ("Annuncio non idoneo", "Annuncio non supportato")


def normalize_language(value) -> str:
    lang = str(value or "").strip().lower()[:2]
    return lang if lang in MESSAGES else DEFAULT_LANGUAGE


def public_failure(job: dict) -> dict:
    """{"failure_code", "failure_message"} for a failed job, one of the three codes."""
    lang = normalize_language((job or {}).get("language"))
    table = MESSAGES[lang]
    internal = (job or {}).get("failure_code")
    if internal == "rejected_by_operator":
        return {"failure_code": "rejected_by_operator", "failure_message": table["rejected_by_operator"]}
    if internal in INPUT_INTERNAL:
        detail = str((job or {}).get("failure_public_message") or "")
        keep = lang == "it" and detail.startswith(_ITALIAN_MARKERS)
        return {"failure_code": "input_not_suitable", "failure_message": detail if keep else table["input_not_suitable"]}
    return {"failure_code": "generation_failed", "failure_message": table["generation_failed"]}
