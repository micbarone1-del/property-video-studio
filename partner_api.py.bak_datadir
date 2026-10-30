"""
Backlog item 48 (CRM partner API), 2026-09-29: partner authentication and
key management. A partner (e.g. Relinx) is distinct from an agency -- a
partner integrates on behalf of one or more agencies. Follows
cost_model.py's existing plain-JSON storage pattern rather than
introducing a new mechanism.
"""
import json
import secrets
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PARTNERS_FILE = BASE_DIR / "partners.json"


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


def deactivate_partner(partner_id: str) -> bool:
    partners = list_partners()
    for p in partners:
        if p["partner_id"] == partner_id:
            p["active"] = False
            _save(PARTNERS_FILE, partners)
            return True
    return False
