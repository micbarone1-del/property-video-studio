"""2026-11-20: possible duplicate of a partner request (same listing sent again with a DIFFERENT external_ref). Pure functions, no network.
Decided with Michele: the video is created as usual and the operator is told (never blocks the partner, the per-agency 24 h limit stays).
The SAME external_ref is already handled elsewhere (the idempotency check at the top of POST /v1/videos, since 2026-10-02).
Same listing = same agency and either (a) at least 80% of the photos are the same files (URL without its signature/query string, so a re-signed
URL still matches) with at least 3 photos on each side, or (b) the same normalised title and the same normalised description.
Failed jobs are ignored (a retry after a failure is legitimate); jobs older than 30 days are ignored."""
import hashlib
import re
from datetime import datetime, timedelta

MIN_PHOTOS = 3
MIN_OVERLAP = 0.8
WINDOW_DAYS = 30


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _payload(job: dict) -> dict:
    p = job.get("partner_payload")
    return p if isinstance(p, dict) else {}


def _photo_keys(job: dict) -> set:
    photos = _payload(job).get("photos")
    out = set()
    if isinstance(photos, list):
        for ph in photos:
            url = ph.get("url") if isinstance(ph, dict) else None
            if url:
                out.add(str(url).split("?")[0].split("#")[0].strip().lower())
    return out


def _text_key(job: dict):
    desc = _norm(_payload(job).get("description"))
    name = _norm(job.get("property_name") or _payload(job).get("property_name"))
    if not desc or not name:
        return None
    return name, hashlib.sha1(desc.encode("utf-8")).hexdigest()[:16]


def same_listing(a: dict, b: dict):
    """Why job a and job b look like the same listing (Italian text), or None."""
    if not a.get("agency_id") or a.get("agency_id") != b.get("agency_id"):
        return None
    if a.get("external_ref") == b.get("external_ref"):
        return None
    pa, pb = _photo_keys(a), _photo_keys(b)
    if len(pa) >= MIN_PHOTOS and len(pb) >= MIN_PHOTOS:
        overlap = len(pa & pb) / min(len(pa), len(pb))
        if overlap >= MIN_OVERLAP:
            return f"stesse foto ({round(overlap * 100)}%)"
    ta, tb = _text_key(a), _text_key(b)
    if ta and ta == tb:
        return "stesso titolo e stessa descrizione"
    return None


def find_possible_duplicates(new_id: str, jobs: dict, now=None) -> list:
    """[{job_id, external_ref, status, reason}] of the earlier partner jobs that look like the same listing as job `new_id`."""
    new = jobs.get(new_id)
    if not new:
        return []
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=WINDOW_DAYS)
    out = []
    for jid, j in jobs.items():
        if jid == new_id or j.get("source") != "relinx" or j.get("status") == "failed":
            continue
        try:
            if datetime.fromisoformat(str(j.get("created_at"))) < cutoff:
                continue
        except Exception:
            pass
        reason = same_listing(new, j)
        if reason:
            out.append({"job_id": jid, "external_ref": j.get("external_ref"), "status": j.get("status"), "reason": reason})
    return out


def alert_html(job_id: str, job: dict, dups: list) -> str:
    rows = "".join(f"<li>job {d['job_id']} (external_ref {d['external_ref']}, stato {d['status']}): {d['reason']}</li>" for d in dups)
    return (f"<p>Relinx ha inviato un annuncio che somiglia a uno gia' ricevuto, con un external_ref diverso.</p>"
            f"<p>Nuovo: job {job_id}, external_ref {job.get('external_ref')}, {job.get('property_name') or ''}.</p><ul>{rows}</ul>"
            "<p>Il video e' stato creato come sempre: se e' un doppione involontario, fermalo dalla dashboard prima che spenda. "
            "Il limite per agenzia nelle 24 ore resta attivo.</p>")
