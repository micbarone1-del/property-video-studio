"""
Backlog item 48 (CRM partner API), 2026-09-29: partner authentication and
key management. A partner (e.g. Relinx) is distinct from an agency -- a
partner integrates on behalf of one or more agencies. Follows
cost_model.py's existing plain-JSON storage pattern rather than
introducing a new mechanism.
"""
import json
import secrets
import time
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

import cost_model   # the ONE place that decides the data folder (PVS_DATA_DIR)

BASE_DIR = Path(__file__).resolve().parent

PAYLOAD_MAX_CHARS = 200_000   # a request bigger than this is stored cut, with the flag below (never blocks the job)


def received_payload_for_job(raw, max_chars=PAYLOAD_MAX_CHARS):
    """2026-11-12: the request exactly as the partner sent it (all fields, also the ones the model does not know), to be kept in the job as
    `partner_payload` so we can see what Relinx really sends. ONE function, ONE caller (POST /v1/videos). Never raises: None when unreadable."""
    try:
        text = json.dumps(raw, ensure_ascii=False)
    except Exception:
        return None
    if len(text) > max_chars:
        return {"_truncated": True, "_chars": len(text), "text": text[:max_chars]}
    return json.loads(text)
PARTNERS_FILE = cost_model.DATA_DIR / "partners.json"


def _load(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def list_partners():
    return _load(PARTNERS_FILE, [])


def create_partner(name: str) -> dict:
    """Creates a new partner and returns the plaintext API key ONCE -- it
    is never stored or retrievable again after this call. Only its
    SHA-256 hash is persisted to disk."""
    partners = list_partners()
    raw_key = f"pvs_{secrets.token_urlsafe(32)}"
    partner = {
        "partner_id": f"pt_{uuid.uuid4().hex[:8]}",
        "name": name.strip(),
        "api_key_hash": _hash_key(raw_key),
        "created_at": datetime.utcnow().isoformat(),
        "active": True,
    }
    partners.append(partner)
    _save(PARTNERS_FILE, partners)
    result = dict(partner)
    result["api_key"] = raw_key  # only ever present in THIS return value
    return result


def verify_partner_key(raw_key: str):
    """Returns the partner record (without the key) if valid and active,
    else None."""
    if not raw_key:
        return None
    key_hash = _hash_key(raw_key)
    for p in list_partners():
        if p.get("api_key_hash") == key_hash and p.get("active", True):
            return p
    return None


def identify_partner_key(raw_key: str):
    """2026-11-20: for the 401 log only. 'partner_id (active|inactive)' when the key is one we issued (so a refused key tells which old key the caller
    still uses), else 'unknown'. Never returns or logs the key itself."""
    key_hash = _hash_key(raw_key or "")
    for p in list_partners():
        if p.get("api_key_hash") == key_hash:
            return f"{p.get('partner_id')} ({'active' if p.get('active', True) else 'inactive'})"
    return "unknown"


class AuthRefusalAlerts:
    """2026-11-20: decides WHEN a refused partner request (401) is worth ONE notification to the operator. Pure and in memory (state resets at restart,
    which only means one extra alert). It never blocks or changes the 401 answer.
      strong refusal (the key looks like one of ours, or it is a key we issued and switched off): notify at the first occurrence
      weak refusal (anything else: no header, short or foreign key): notify only when it repeats weak_threshold times inside window_secs
      the same signature notifies at most once per cooldown_secs, and the whole process at most global_max times per global_window_secs
    Why: a Relinx request refused with 401 on 19/11 at 23:14 left no trace and nobody was told."""
    def __init__(self, window_secs=900, weak_threshold=3, cooldown_secs=21600, global_max=4, global_window_secs=3600):
        self.window_secs, self.weak_threshold, self.cooldown_secs = window_secs, weak_threshold, cooldown_secs
        self.global_max, self.global_window_secs = global_max, global_window_secs
        self._hits, self._last_alert, self._global = {}, {}, []

    def note(self, signature: str, strong: bool, now: float = None) -> bool:
        now = time.time() if now is None else now
        hits = [t for t in self._hits.get(signature, []) if now - t <= self.window_secs] + [now]
        self._hits[signature] = hits
        if not (strong or len(hits) >= self.weak_threshold):
            return False
        last = self._last_alert.get(signature)
        if last is not None and now - last < self.cooldown_secs:
            return False
        self._global = [t for t in self._global if now - t <= self.global_window_secs]
        if len(self._global) >= self.global_max:
            return False
        self._last_alert[signature] = now
        self._global.append(now)
        return True


def auth_refusal_is_strong(raw_key: str, known: str) -> bool:
    """True when a refused key is probably a real partner mistake: it is an issued key that was switched off, or it has the exact shape of our keys
    (pvs_ + 43 characters) but matches nothing we stored."""
    raw_key = raw_key or ""
    return str(known).endswith("(inactive)") or (raw_key.startswith("pvs_") and len(raw_key) == 47)


def deactivate_partner(partner_id: str) -> bool:
    partners = list_partners()
    for p in partners:
        if p["partner_id"] == partner_id:
            p["active"] = False
            _save(PARTNERS_FILE, partners)
            return True
    return False
