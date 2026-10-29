"""
listing_scraper.py

Extracts photos (with labels + categories), description, price, and address
from a real-estate listing page — using the Claude API's web_fetch server
tool, then selects the right photos per your priority order and flags gaps
requiring manual upload.

Generalized across immobiliare.it, idealista.it, and casa.it (the three
sites agreed as initial scope) rather than one hardcoded adapter per site —
since extraction works by having Claude read the page SEMANTICALLY (not via
brittle CSS/DOM selectors), the same extraction logic works across
differently-structured sites. Each site's own domain is checked against
SUPPORTED_DOMAINS; anything else logs a "site requested" entry instead of
guessing at an unsupported site's structure.

WHY CLAUDE-FETCH INSTEAD OF A DIRECT REQUEST: immobiliare.it returns a 403
Forbidden to direct requests.get() calls from this VPS — confirmed via live
testing (July 9 2026) to be IP-based blocking (a full realistic browser
header set made no difference; the same URL loaded fine from a real
residential browser). The Claude API's web_fetch tool runs server-side on
Anthropic's infrastructure, not this VPS, and is confirmed working. The same
approach is used preemptively for idealista.it/casa.it since they're
comparable commercial portals likely to have similar protections — this is
UNCONFIRMED for those two specifically until tested.

REQUIREMENTS:
  - `anthropic` Python package (in requirements.txt)
  - `ANTHROPIC_API_KEY` in .env

STATUS: immobiliare.it extraction fully tested and confirmed working
end-to-end (July 9 2026) — real listing, 45 photos, correct categorization,
correct description/price/address. idealista.it and casa.it use the same
code path but are UNTESTED — need a real listing URL from each to confirm
before trusting them.

KNOWN OPEN ITEMS (not blockers, flagged for follow-up):
  - Image resolution: attempts common CDN size-suffix upgrades via a cheap
    HEAD request before falling back to whatever Claude returned. This is a
    best-effort heuristic, not a confirmed-correct mechanism for every site.
  - Vision-QC fallback for "uncategorized" photos calls vision_analysis.py's
    analyse_input() — ASSUMING its return schema includes a "space_type" or
    similar field usable to derive one of our 6 categories. This assumption
    is NOT independently re-verified in this session; check real output
    against this assumption on first real use.
"""

import os
import camera_plan
import re
import math
import json
import time
import logging
import threading
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
import anthropic
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# Claude API pricing - Haiku 4.5 (verified against Anthropic pricing, July 2026)
CLAUDE_INPUT_PER_MTOK  = 1.00   # USD per million input tokens
CLAUDE_OUTPUT_PER_MTOK = 5.00   # USD per million output tokens
USD_TO_EUR = 0.93

# Accumulates real token usage across every Anthropic call made while building
# one job (extraction, photo quality ranking, narration, captions). Reset per
# job by the caller via reset_claude_usage().
_claude_usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

def reset_claude_usage():
    _claude_usage.update({"input_tokens": 0, "output_tokens": 0, "calls": 0})

_claude_lock = threading.Lock()


def _track_claude(response):
    try:
        u = response.usage
        with _claude_lock:
            _claude_usage["input_tokens"]  += getattr(u, "input_tokens", 0) or 0
            _claude_usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
            _claude_usage["calls"] += 1
    except Exception:
        pass
    return response

# USD per million tokens (input, output) by model. 5.5 models: platform.claude.com model pages, 2026-10-25 (prompts up to 100K tokens).
CLAUDE_PRICES = {
    "claude-haiku-4-5-20251001": (CLAUDE_INPUT_PER_MTOK, CLAUDE_OUTPUT_PER_MTOK),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}


def claude_cost_eur(input_tokens, output_tokens, model=None):
    """THE cost formula (EUR) of a number of tokens of one model; an unknown model is priced like the default one (never zero)."""
    pin, pout = CLAUDE_PRICES.get(model or MODEL, (CLAUDE_INPUT_PER_MTOK, CLAUDE_OUTPUT_PER_MTOK))
    usd = (input_tokens / 1_000_000) * pin + (output_tokens / 1_000_000) * pout
    return round(usd * USD_TO_EUR, 4)


def merge_claude_usage(base, extra):
    """Sums two usage dicts ({input_tokens, output_tokens, calls, cost_eur}); either may be None. Used to add the usage of calls that were
    NOT counted in the per-job counter (the clip QC runs after the draft was made) to the job's claude_usage."""
    out = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cost_eur": 0.0}
    for d in (base, extra):
        for k in ("input_tokens", "output_tokens", "calls"):
            out[k] += int((d or {}).get(k, 0) or 0)
        out["cost_eur"] += float((d or {}).get("cost_eur", 0) or 0)
    out["cost_eur"] = round(out["cost_eur"], 4)
    return out


def get_claude_cost():
    """Real Claude API cost for the current job, in EUR."""
    i = _claude_usage["input_tokens"]; o = _claude_usage["output_tokens"]
    return {
        "input_tokens": i, "output_tokens": o, "calls": _claude_usage["calls"],
        "cost_eur": claude_cost_eur(i, o),
    }

MODEL = "claude-haiku-4-5-20251001"  # cheapest current model; upgrade to
                                       # claude-sonnet-5 if extraction quality
                                       # proves unreliable on tricky listings

CATEGORIES = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]
PRIORITY_ORDER = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]

CATEGORY_ITALIAN_LABELS = {
    "exterior": "facciata/esterno dell'edificio",
    "living": "soggiorno",
    "kitchen": "cucina",
    "bedrooms": "camere da letto",
    "bathrooms": "bagni",
    "outdoor": "spazi esterni (giardino/terrazza)",
    "laundry": "lavanderia",
    "office": "studio",
    "garage": "garage",
}


def derive_available_category_order(photos: list, priority_order: list = None) -> list:
    """Returns the subset of priority_order categories that have at least
    one real photo, in priority_order's sequence -- this IS the actual
    scene sequence the video will show. Lightweight on purpose: only
    checks presence, no quality ranking, no API calls."""
    order = priority_order if priority_order is not None else PRIORITY_ORDER
    present = {p.get("category") for p in photos}
    return [cat for cat in order if cat in present]

MIN_USABLE_PHOTOS = 5
MIN_ENVIRONMENT_TYPES = 4
_STANDARD_TYPES_IT = "facciata, soggiorno, cucina, camera da letto, bagno, balcone/giardino"


def check_listing_acceptance(photos: list) -> dict:
    """2026-10-12 (3B): standard-video acceptance rule, run BEFORE any narration/TTS is paid for.
    A listing is accepted only with at least MIN_USABLE_PHOTOS usable photos (a real category, de-duplicated
    by URL) AND at least MIN_ENVIRONMENT_TYPES distinct environment types. Otherwise it is rejected with the
    code "insufficient_photos" and an Italian reason an operator or a partner API can show as it is."""
    seen, by_cat = set(), {}
    for p in photos or []:
        cat, url = p.get("category"), p.get("url")
        if cat in CATEGORIES and url and url not in seen:
            seen.add(url)
            by_cat[cat] = by_cat.get(cat, 0) + 1
    usable = sum(by_cat.values())
    types_found = [c for c in PRIORITY_ORDER if c in by_cat]
    missing = [c for c in PRIORITY_ORDER if c not in by_cat]
    result = {"ok": True, "code": None, "message": None, "usable_photos": usable,
              "environment_types": types_found, "missing_types": missing,
              "min_photos": MIN_USABLE_PHOTOS, "min_types": MIN_ENVIRONMENT_TYPES}
    if usable >= MIN_USABLE_PHOTOS and len(types_found) >= MIN_ENVIRONMENT_TYPES:
        return result
    found_it = ", ".join(CATEGORY_ITALIAN_LABELS[c] for c in types_found) or "nessuno"
    only_outside = bool(types_found) and set(types_found) <= {"exterior", "outdoor"}
    msg = (f"Annuncio non idoneo al video standard: {usable} foto utilizzabili e {len(types_found)} tipi di ambiente "
           f"(servono almeno {MIN_USABLE_PHOTOS} foto e {MIN_ENVIRONMENT_TYPES} ambienti diversi tra: {_STANDARD_TYPES_IT}). "
           f"Ambienti trovati: {found_it}.")
    if missing:
        msg += " Mancano: " + ", ".join(CATEGORY_ITALIAN_LABELS[c] for c in missing) + "."
    if only_outside:
        msg += " Le foto mostrano solo esterni: servono anche gli interni."
    result.update({"ok": False, "code": "insufficient_photos", "message": msg})
    log.warning(f"[Scraper] Listing rejected (insufficient_photos): {msg}")
    return result


# 2026-10-28 (Michele): launch scope. A listing whose living room AND bedroom show no furniture is "not furnished" and out of scope for now.
# It is checked in the SAME gate as the photo rule (check_listing_scope), before any narration or voice is paid for. Page labels decide which
# photos are the living room and the bedroom; Claude vision is asked only whether furniture is visible (kitchen units do not count).
FURNISHED_SAMPLE_PER_ROOM = 2
FURNISHED_ROOMS = ("living", "bedrooms")
UNFURNISHED_MESSAGE = "Annuncio non supportato: appartamento non arredato (al momento non disponibile)."
ACCEPTANCE_SHORT_REASON = {"insufficient_photos": "foto insufficienti", "unfurnished": "non arredato"}
_VISION_FURNISHED_PROMPT = (
    "Look at this real estate interior photo. Does the room contain furniture (a sofa, table, chairs, a bed, a wardrobe, a desk, shelves "
    "or similar movable furniture)? Built-in kitchen units, fixed lights and curtains do NOT count as furniture.\n"
    "Answer with ONLY one word: furnished or empty."
)


def acceptance_short_reason(acceptance: dict) -> str:
    # short Italian reason for a push notification, from the failure code (one table for every gate)
    return ACCEPTANCE_SHORT_REASON.get((acceptance or {}).get("code"), "non idoneo")


def check_listing_furnished(photos: list, ask=None) -> dict:
    # returns ok False ONLY when every room that has photos (living, bedrooms) was judged empty by a clear majority of its sampled photos
    # with no failed call. Anything unsure (no photo, failed call, unclear answer) never blocks a listing.
    ask = ask or _vision_one_word
    detail, verdicts, seen = {}, [], set()
    for room in FURNISHED_ROOMS:
        sample = []
        for p in photos or []:
            url = p.get("url")
            if p.get("category") == room and url and url not in seen and len(sample) < FURNISHED_SAMPLE_PER_ROOM:
                seen.add(url)
                sample.append(p)
        if not sample:
            detail[room] = "no photo"
            continue
        words = [ask(p["url"], p.get("original_url"), _VISION_FURNISHED_PROMPT) for p in sample]
        if any(not ok for _, ok in words):
            detail[room] = "unknown (a vision call failed)"
            verdicts.append(None)
            continue
        empties = sum(1 for w, _ in words if w == "empty")
        furnished = sum(1 for w, _ in words if w.startswith("furnished"))
        if empties * 2 > len(words):
            detail[room] = "empty (" + str(empties) + " of " + str(len(words)) + " photos)"
            verdicts.append("empty")
        elif furnished:
            detail[room] = "furnished"
            verdicts.append("furnished")
        else:
            detail[room] = "unknown (unclear answer)"
            verdicts.append(None)
    blocked = bool(verdicts) and all(v == "empty" for v in verdicts)
    return {"ok": not blocked, "detail": detail}


def furnished_enforced() -> bool:
    # 2026-10-28: measure-only by default. An empty flat is recorded (furnished_status = unfurnished) but NOT rejected.
    # Set PVS_FURNISHED_ENFORCE=1 in .env and restart to reject unfurnished listings again.
    return os.environ.get("PVS_FURNISHED_ENFORCE", "0").strip().lower() in ("1", "true", "yes", "on")


def check_listing_scope(photos: list, ask=None) -> dict:
    # the ONE gate both workflows call before narration: the photo rule (check_listing_acceptance) first, then the furnished rule.
    # same result shape as check_listing_acceptance, so every caller reads it exactly as before
    result = check_listing_acceptance(photos)
    if not result["ok"]:
        return result
    furn = check_listing_furnished(photos, ask=ask)
    result["furnished_check"] = furn["detail"]
    result["furnished_status"] = "ok" if furn["ok"] else "unfurnished"
    if not furn["ok"]:
        if furnished_enforced():
            result.update({"ok": False, "code": "unfurnished", "message": UNFURNISHED_MESSAGE})
            log.warning("[Scraper] Listing rejected (unfurnished): " + str(furn["detail"]))
        else:
            log.info("[Scraper] Listing looks unfurnished, measure-only mode (not rejected): " + str(furn["detail"]))
    return result


SUPPORTED_DOMAINS = {"immobiliare.it", "www.immobiliare.it", "idealista.it", "www.idealista.it",
                     "casa.it", "www.casa.it", "annunci.getrix.it"}

BASE_DIR = Path(__file__).parent
REQUESTED_SITES_FILE = BASE_DIR / "scraper_site_requests.json"

EXTRACTION_PROMPT = """Fetch this real estate listing page: {url}

Extract and return ONLY a JSON object (no other text, no markdown code fences) with this exact structure:

{{
  "photos": [
    {{"url": "...", "label_it": "...", "category": "one of: exterior, living, kitchen, bedrooms, bathrooms, outdoor, laundry, office, garage, uncategorized"}}
  ],
  "description": "...",
  "price": "...",
  "address": "..."
}}

Rules:
- Only include real property photos in "photos" — EXCLUDE floor plan diagrams and any agent/agency headshot or logo images.
- "label_it" is the photo's own caption/label as shown on the page, in whatever language the site uses.
- Map each photo's label to exactly one category: exterior (building facade, outdoor view of the property itself), living (living room, dining room, study; NOT entrance hall, corridor, hallway or stairs, which must be uncategorized), kitchen, bedrooms, bathrooms, outdoor (garden, terrace, courtyard, parking area, land/terrain), laundry (laundry/utility room -- 2026-07-24: previously lumped into bathrooms, now its own category so it can appear as an extra scene when a longer video needs it), office (study/home office, distinct from a general living-area study), garage (garage, carport, covered parking specifically -- distinct from general outdoor parking). If a label doesn't clearly fit any of these, use "uncategorized".
- If the page provides a larger/original-resolution version of each photo (e.g. via a lightbox, srcset, or a "view full size" link), use that URL instead of a thumbnail/compressed variant.
- "description" is the full property description text from the listing (not a shortened meta/preview version).
- "price" and "address" as shown on the page.
"""


# ── Domain support / "request a new site" workflow ──────────────────────────

def is_supported_domain(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return domain in SUPPORTED_DOMAINS


def log_site_request(url: str) -> None:
    """Records a request for an unsupported domain so it can be reviewed for
    adding real support later, rather than silently failing or guessing at
    an unfamiliar site's structure."""
    domain = urlparse(url).netloc.lower()
    requests_log = []
    if REQUESTED_SITES_FILE.exists():
        try:
            requests_log = json.loads(REQUESTED_SITES_FILE.read_text())
        except Exception:
            requests_log = []
    requests_log.append({"domain": domain, "example_url": url,
                          "requested_at": __import__("datetime").datetime.now().isoformat()})
    REQUESTED_SITES_FILE.write_text(json.dumps(requests_log, indent=2))
    log.info(f"[Scraper] Logged unsupported-site request: {domain}")


# ── Image resolution upgrade (best-effort, cheap HEAD requests) ────────────

_RESOLUTION_UPGRADE_PATTERNS = [
    (r"/m-c\.jpg$", "/xl-c.jpg"),
    (r"/m-c\.jpg$", "/xl.jpg"),
    (r"/m-c\.jpg$", "/original.jpg"),
    (r"-c\.jpg$", ".jpg"),
    (r"_th\.jpg$", "_hd.jpg"),   # 2026-10-15: annunci.getrix.it serves thumbnails as _th and full size as _hd
]


_TRUNCATED_PHOTO_URL = re.compile(r"^(https?://[^/?#]+/image/\d+)/?$")


def normalize_photo_url(url: str) -> str:
    """2026-10-12: the page reader sometimes returns an immobiliare CDN photo URL WITHOUT its file
    name (".../image/1963262752/" -> 404; verified live: the same id answers 200 with "/m-c.jpg",
    "/xl-c.jpg" and "/xl.jpg"). Such a URL is rewritten to the canonical "/m-c.jpg" form, which the
    existing try_upgrade_resolution() then upgrades exactly like any other photo. Everything else
    is returned unchanged."""
    m = _TRUNCATED_PHOTO_URL.match(url or "")
    return (m.group(1) + "/m-c.jpg") if m else url


def try_upgrade_resolution(image_url: str) -> dict:
    """Attempts a few common CDN size-suffix substitutions via a cheap HEAD
    request, returning the first one that responds successfully. Falls back
    to the original URL if none work — this is a best-effort heuristic, not
    a confirmed-correct mechanism, since it hasn't been validated against
    which pattern (if any) actually serves a genuinely higher-resolution
    image rather than just a differently-named same-size file.

    Returns {"url": str, "upgraded": bool} — the upgraded flag makes this
    visible/loggable instead of a silent no-op when nothing works.
    """
    for pattern, replacement in _RESOLUTION_UPGRADE_PATTERNS:
        candidate = re.sub(pattern, replacement, image_url)
        if candidate == image_url:
            continue
        try:
            resp = requests.head(candidate, timeout=5)
            if resp.status_code == 200:
                return {"url": candidate, "upgraded": True}
        except Exception:
            continue
    return {"url": image_url, "upgraded": False}


# ── Shared photo fetch (2026-10-12, 3A) ─────────────────────────────────────
# ONE place that downloads a photo, used by download_photo(), rank_photos_by_quality()
# and classify_uncategorized_photo() -- they used to each call requests.get() on their
# own. try_upgrade_resolution() only checks the "upgraded" URL with a HEAD request, but
# the real GET can still answer 403 ("Bad Parameters"); the original URL is kept in
# photo["original_url"] and tried second, so one bad upgraded URL no longer fails a job.

def fetch_photo_bytes(url: str, fallback_url: str = None, timeout: int = 20, attempts: int = 1) -> dict:
    """Returns {"ok", "content", "url_used", "used_fallback", "error"}.
    Per URL: transient failures (timeout, connection error, HTTP 429/5xx) are retried up
    to `attempts` times with a short backoff; other 4xx are permanent for that URL."""
    urls = [url]
    if fallback_url and fallback_url != url:
        urls.append(fallback_url)
    errors = []
    for idx, u in enumerate(urls):
        last_error = "unknown"
        permanent = False
        for attempt in range(attempts):
            try:
                resp = requests.get(u, timeout=timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}"
                else:
                    resp.raise_for_status()  # other 4xx -> permanent for this URL
                    return {"ok": True, "content": resp.content, "url_used": u,
                            "used_fallback": idx > 0, "error": None}
            except requests.HTTPError as e:
                last_error = f"download failed: {e}"
                permanent = True
                break
            except Exception as e:
                last_error = str(e)
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
        errors.append(last_error if permanent else f"download failed after {attempts} attempts: {last_error}")
    return {"ok": False, "content": None, "url_used": None, "used_fallback": False,
            "error": " | fallback: ".join(errors)}


# ── Core extraction ─────────────────────────────────────────────────────────

# 2026-10-27: was 4096; a listing with many photos made the JSON stop in the middle (JSON parse failed, line 357). Output is billed only for what is written.
EXTRACTION_MAX_TOKENS = 12000


def extract_listing(url: str, attempt_resolution_upgrade: bool = True) -> dict:
    """
    Returns:
      {
        "ok": bool,
        "photos": [ {"url": str, "label_it": str, "category": str}, ... ],
        "description": str,
        "price": str | None,
        "address": str | None,
        "error": str | None,
      }
    """
    if not is_supported_domain(url):
        log_site_request(url)
        return {"ok": False, "photos": [], "description": "", "price": None,
                "address": None,
                "error": f"Site not yet supported: {urlparse(url).netloc}. "
                         f"Request logged — upload photos manually for now."}

    raw = ""
    json_str = ""
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = _track_claude(client.messages.create(
            model=MODEL,
            max_tokens=EXTRACTION_MAX_TOKENS,
            tools=[{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1}],
            extra_headers={"anthropic-beta": "web-fetch-2025-09-10"},
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(url=url)}],
        ))

        text_parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        raw = "".join(text_parts).strip()

        if getattr(response, "stop_reason", None) == "max_tokens":
            return {"ok": False, "photos": [], "description": "", "price": None, "address": None,
                    "error": f"Listing too large: the extraction answer was cut at {EXTRACTION_MAX_TOKENS} tokens (stop_reason=max_tokens), so it is not valid JSON."}

        if not raw:
            block_types = [getattr(b, "type", "?") for b in response.content]
            return {"ok": False, "photos": [], "description": "", "price": None,
                    "address": None,
                    "error": f"No text content in response. stop_reason={response.stop_reason}, "
                             f"content block types={block_types}"}

        json_str = raw
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence_match:
            json_str = fence_match.group(1)
        else:
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if brace_match:
                json_str = brace_match.group(0)

        data = json.loads(json_str)

        for p in data.get("photos", []):
            if p.get("url"):
                # 2026-10-15: some sites (annunci.getrix.it) write photo paths relative to the page ("/foto/7039/x_th.jpg");
                # made absolute here, in the single extraction point, so every site benefits.
                p["url"] = normalize_photo_url(urljoin(url, p["url"]))
            if p.get("category") not in CATEGORIES:
                p["category"] = "uncategorized"
            if attempt_resolution_upgrade and p.get("url"):
                p["original_url"] = p["url"]   # 2026-10-12: kept so a failing upgraded URL can fall back to it
                upgrade_result = try_upgrade_resolution(p["url"])
                p["url"] = upgrade_result["url"]
                p["resolution_upgraded"] = upgrade_result["upgraded"]

        data["ok"] = True
        data["error"] = None
        return data

    except json.JSONDecodeError as e:
        return {"ok": False, "photos": [], "description": "", "price": None,
                "address": None, "error": f"JSON parse failed: {e}. Extracted text was: {json_str[:500]}"}
    except Exception as e:
        return {"ok": False, "photos": [], "description": "", "price": None,
                "address": None, "error": str(e)}


# ── Uncategorized-photo fallback via existing vision QC ─────────────────────

_VISION_CLASSIFY_PROMPT = (
    "Look at this real estate photo. Which ONE category best describes what the photo mainly shows?\n\n"
    "- exterior: the building's exterior walls and windows seen from the street OR from an inner courtyard. If the main subject is the building's outer walls, it is exterior even if a courtyard is visible.\n"
    "- living: only when a sofa, lounge or dining table is the main subject.\n"
    "- kitchen: choose kitchen whenever cabinets, hob, sink or appliances are the main subject, even in an open-plan room.\n"
    "- bedrooms: bedroom or sleeping area (also the sleeping area of a studio flat).\n"
    "- bathrooms: bathroom, toilet, shower room.\n"
    "- outdoor: a PRIVATE outdoor space belonging to this home: balcony, terrace, private garden, or the view from that balcony/terrace, or the view FROM A WINDOW of this home (skyline, rooftops, city, sea, countryside) when the view itself is the main subject. A shared or condominium space (courtyard, portico, shared balcony or walkway) is NOT outdoor: answer other.\n"
    "- An AERIAL or DRONE photo taken from above, a map or satellite image, and a landmark or monument photographed from outside the property (not as seen from this home's own balcony, terrace or window) are NOT exterior and NOT outdoor: answer other.\n"
    "- other: entrance hall, corridor, hallway, stairs, shared building areas (courtyard, portico, lobby, lift, communal garden), "
    "floor plan, close-up of a detail, a single tree or plant close up, or anything that is not one of the categories above.\n\n"
    "Answer with ONLY one word: exterior, living, kitchen, bedrooms, bathrooms, outdoor or other."
)
VISION_MAX_SIDE = 768


def _image_b64_for_vision(content: bytes) -> str:
    """Downscaled JPEG (max side VISION_MAX_SIDE) as base64: enough to recognise a room, far cheaper and faster than the
    full-resolution original. Falls back to the original bytes if Pillow cannot read the image."""
    import base64, io
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content)).convert("RGB")
        img.thumbnail((VISION_MAX_SIDE, VISION_MAX_SIDE))
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return base64.b64encode(content).decode("utf-8")


def _vision_word_from_b64(b64_images: list, prompt: str, label: str = "") -> tuple:
    """The ONE place that sends one or more photos (already base64 JPEG) and a short question to Claude vision and returns the
    answer as one lowercase word. (word, ok): ok is False only when the call itself failed.
    2026-10-29: split out of _vision_one_word so a question that needs a second image (the photo-quality check sends the whole
    photo and a crop at its real pixels) uses the same sender instead of a copy of it."""
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        content = [{"type": "text", "text": prompt}]
        for b64 in b64_images:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        response = _track_claude(client.messages.create(
            model=MODEL, max_tokens=20, messages=[{"role": "user", "content": content}],
        ))
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip().lower()
        return re.sub(r"[^a-z]", "", raw), True
    except Exception as e:
        log.warning(f"[Scraper] Vision question failed for {label}: {e}")
        return "", False


def _vision_one_word(image_url: str, fallback_url: str, prompt: str) -> tuple:
    """Downloads a listing photo, sends it downscaled with a short question to Claude vision (see _vision_word_from_b64) and
    returns the answer as one lowercase word. (word, ok): ok is False only when the call itself failed (download or API)."""
    try:
        fetched = fetch_photo_bytes(image_url, fallback_url, timeout=15)
        if not fetched["ok"]:
            raise RuntimeError(fetched["error"])
        b64 = _image_b64_for_vision(fetched["content"])
    except Exception as e:
        log.warning(f"[Scraper] Vision question failed for {image_url}: {e}")
        return "", False
    return _vision_word_from_b64([b64], prompt, image_url)


def _classify_photo_vision(image_url: str, fallback_url: str = None) -> tuple:
    """Single implementation of "which room is this photo" (Claude vision). Returns (category, ok):
    category is one of CATEGORIES or "uncategorized" (the model answered "other"/anything else);
    ok is False only when the call itself failed (download or API), so callers can keep a previous label."""
    word, ok = _vision_one_word(image_url, fallback_url, _VISION_CLASSIFY_PROMPT)
    if not ok:
        return "uncategorized", False
    return (word if word in CATEGORIES else "uncategorized"), True


# ── Photo technical quality via Claude vision (2026-10-29) ───────────────────────────────────────────────────────────────
# Job cc33f8af: a portal photo full of JPEG blocks and with the portal's watermark across the main subject gave a bad clip
# start frame. The ranking prompt now also penalises such photos (rank_photos_by_quality, no extra call), but it skips a category
# with one candidate and it sees the photo scaled down, where blocks disappear. This is the absolute check on the photos
# that were chosen: the whole photo plus a crop at its real pixels.
PHOTO_QUALITY_PROMPT = (
    "You will see two images of the SAME real estate photo: first the whole photo scaled down, then a crop of its centre at the "
    "original pixels (100%). Judge only the technical quality of the picture, because a video model will build a 5 second clip "
    "from it as the first frame. Ordinary phone or camera photos with normal sharpness are ok: answer another word ONLY when the "
    "problem is clearly visible.\n"
    "- soft: clearly blurred, out of focus or smeared, with no fine detail left.\n"
    "- blocky: clearly pixelated, with visible JPEG blocks, banding or heavy noise.\n"
    "- watermark: a large semi-transparent text, logo or stamp across the main subject.\n"
    "- ok: none of these.\n"
    "Answer with ONLY one word: ok, soft, blocky or watermark."
)
PHOTO_QUALITY_WORDS = ("ok", "soft", "blocky", "watermark")
PHOTO_QUALITY_POOR = ("soft", "blocky", "watermark")
QUALITY_JUDGE_PER_CATEGORY = 4      # the best-ranked candidates of each category that get a verdict (the rest are never reached)


def _native_crop_b64(content: bytes, side: int = VISION_MAX_SIDE) -> str:
    """Centre crop of the photo at its REAL pixels (no scaling), base64 JPEG: what a scaled-down picture hides."""
    import base64, io
    from PIL import Image
    img = Image.open(io.BytesIO(content)).convert("RGB")
    w, h = img.size
    cw, ch = min(side, w), min(side, h)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    buf = io.BytesIO(); img.crop((x0, y0, x0 + cw, y0 + ch)).save(buf, "JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def assess_photo_quality(content: bytes, label: str = "") -> dict:
    """{"verdict": ok|soft|blocky|watermark|unknown, "call_ok": bool}. "unknown" = the call failed or the answer was not one of
    the four words; unknown is never treated as a problem."""
    try:
        images = [_image_b64_for_vision(content), _native_crop_b64(content)]
    except Exception as e:
        log.warning(f"[Scraper] Photo quality: could not prepare {label}: {e}")
        return {"verdict": "unknown", "call_ok": False}
    word, ok = _vision_word_from_b64(images, PHOTO_QUALITY_PROMPT, label)
    if not ok:
        return {"verdict": "unknown", "call_ok": False}
    return {"verdict": word if word in PHOTO_QUALITY_WORDS else "unknown", "call_ok": True}


def photo_quality_check_enabled() -> bool:
    return os.environ.get("PVS_QUALITY_CHECK", "1").strip().lower() not in ("0", "false", "no", "off")


def photo_quality_enforce_enabled() -> bool:
    """On by default (Michele 2026-10-29: the discard happens in the selection, so a blurred photo is never chosen). PVS_QUALITY_ENFORCE=0
    keeps only the measurement (verdicts saved in the selection report, nothing removed)."""
    return os.environ.get("PVS_QUALITY_ENFORCE", "1").strip().lower() not in ("0", "false", "no", "off")


def filter_poor_quality_candidates(by_category: dict, assess=None, enforce=None) -> dict:
    """The photo-quality filter of the SELECTION (one place, shared by the standard and the premium selection through
    _categorize_and_rank_photos, so both the URL path and the Relinx path get it). Runs on the best-ranked candidates of each category
    (QUALITY_JUDGE_PER_CATEGORY): downloads each, asks Claude vision for the verdict (whole photo + crop at real pixels), tags the
    photo p["quality"], and, when enforcing, removes the soft / blocky / watermarked ones from the pool (p["quality_rejected"] = True),
    so the selection simply takes the next candidate. When too few photos are left the selection reports a gap and the job fails with
    a reason (see _quality_gap_note). Never raises; a failed call is "unknown" and keeps the photo."""
    if not photo_quality_check_enabled():
        return {"enabled": False}
    assess = assess or assess_photo_quality
    enforce = photo_quality_enforce_enabled() if enforce is None else bool(enforce)
    try:
        items = [(cat, p) for cat, plist in by_category.items() for p in plist[:QUALITY_JUDGE_PER_CATEGORY]]

        def one(item):
            cat, p = item
            try:
                fetched = fetch_photo_bytes(p.get("url"), p.get("original_url"), timeout=15)
                if not fetched["ok"]:
                    return {"verdict": "unknown", "call_ok": False}
                return assess(fetched["content"], label=f"{cat}")
            except Exception as e:
                log.warning(f"[Scraper] Photo quality failed for {cat}: {e}")
                return {"verdict": "unknown", "call_ok": False}
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as ex:
            results = list(ex.map(one, items))
        poor = 0
        for (cat, p), r in zip(items, results):
            p["quality"] = r["verdict"]
            if r["verdict"] in PHOTO_QUALITY_POOR:
                poor += 1
                p["quality_poor"] = True
                if enforce:
                    p["quality_rejected"] = True
        if enforce:
            for cat in by_category:
                by_category[cat] = [p for p in by_category[cat] if not p.get("quality_rejected")]
        summary = {"enabled": True, "enforced": enforce, "checked": len(items), "poor": poor,
                   "unknown": sum(1 for r in results if r["verdict"] == "unknown")}
        log.info(f"[Scraper] Photo quality (selection): {summary}")
        return summary
    except Exception as e:
        log.warning(f"[Scraper] Photo quality filter failed as a whole: {e}")
        return {"enabled": True, "error": str(e)[:160]}


# Phrase inside the gap text that marks "photos were thrown away for quality"; api_server reads it to pick the partner failure code.
QUALITY_GAP_MARKER = "discarded for insufficient image quality"


def _quality_gap_note(photos: list) -> str:
    """Sentence added to a "not enough photos" gap when photos were discarded for quality, so the operator and the customer get the reason."""
    n = len({id(p) for p in photos if p.get("quality_rejected")})
    if not n:
        return ""
    return (f" {n} photo(s) of the listing were {QUALITY_GAP_MARKER} "
            f"(blurred, pixelated or with a watermark across the subject).")


# 2026-10-27: a photo the listing page labels "living" is sometimes the entrance hall, a corridor or a staircase (villa job
# e1dccbd4: the only "living" photo was a corridor). A separate, narrow question on purpose: the general classifier says "other"
# for a lounge with no sofa, which would wrongly throw away EMPTY apartments' living rooms.
_VISION_HALL_PROMPT = (
    "Look at this real estate photo. Does it mainly show an ENTRANCE HALL, a CORRIDOR, a hallway, a staircase or stairs landing, "
    "or a lobby (a passage, not a room you stay in)? An empty or unfurnished living room, lounge or open-plan room is NOT a hall.\n"
    "Answer with ONLY one word: hall or room."
)


def _is_hall_photo(image_url: str, fallback_url: str = None) -> tuple:
    """(is_hall, ok). ok False = the call failed, callers keep the page label."""
    word, ok = _vision_one_word(image_url, fallback_url, _VISION_HALL_PROMPT)
    return word == "hall", ok


def classify_uncategorized_photo(image_url: str, fallback_url: str = None) -> str:
    """Room type of one photo via Claude vision (see _classify_photo_vision). Never raises; "uncategorized" if unsure.
    Limited to the 6 PRIORITY_ORDER categories on purpose (a value outside it would vanish in selection)."""
    return _classify_photo_vision(image_url, fallback_url)[0]


MAX_PHOTOS_TO_REFINE = 12
MAX_LIVING_TO_CHECK = 8     # 2026-10-27: first living-labelled photos checked for hall / corridor / stairs (ranking only compares 6 anyway)
CLASSIFY_WORKERS = 4


def refine_exterior_outdoor_with_vision(photos: list, max_photos: int = MAX_PHOTOS_TO_REFINE) -> dict:
    """2026-10-12 (A+): ONE shared check for the URL path and the Relinx path. Interior categories (living, kitchen,
    bedrooms, bathrooms) keep the label that came with the photo (listing page or CRM). Only photos labelled exterior or
    outdoor are looked at by Claude vision, because that is where labels are wrong: an entrance hall or corridor read as
    facade, a shared portico or condominium courtyard read as balcony.
      vision says exterior/outdoor -> that category (exterior and outdoor may swap)
      vision says anything else    -> category "uncategorized" (photo leaves the selection; interiors are never assigned here)
      vision call failed           -> label kept (p["category_source"] = "page_fallback")
    Photos already classified by vision (p["category_source"] == "vision", i.e. resolved from "uncategorized") are skipped.
    Returns a summary dict stored in the job's selection_report."""
    from concurrent.futures import ThreadPoolExecutor
    cands = [p for p in photos if p.get("category") in ("exterior", "outdoor") and p.get("category_source") != "vision" and p.get("url")]
    todo, over = cands[:max_photos], cands[max_photos:]
    def work(p):
        return _classify_photo_vision(p["url"], p.get("original_url"))
    with ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as ex:
        results = list(ex.map(work, todo))
    confirmed = swapped = excluded = fallback = 0
    for p, (cat, ok) in zip(todo, results):
        p["category_page"] = p.get("category")
        if not ok:
            p["category_source"] = "page_fallback"; fallback += 1
        elif cat in ("exterior", "outdoor"):
            p["category_source"] = "vision_refine"
            if cat == p["category"]:
                confirmed += 1
            else:
                swapped += 1
            p["category"] = cat
        else:
            p["category_source"] = "vision_refine"; p["category"] = "uncategorized"; excluded += 1
    for p in over:
        p["category_page"] = p.get("category"); p["category_source"] = "page_not_checked"
    # 2026-10-27: photos labelled "living" are checked for the entrance hall / corridor / stairs mix-up (see _VISION_HALL_PROMPT).
    # A hall leaves the selection (category "uncategorized"); anything else keeps the page label. Standard video only has the
    # six rooms; a premium "entrance" scene is a separate backlog item.
    # 2026-10-28 (Michele): the agency label comes FIRST, Claude vision only when there is no label. A living photo that has a caption on the page keeps it
    # (an empty flat reads as a corridor to vision but its caption says living room); only a living photo WITHOUT a caption is checked for the hall mix-up.
    living = [p for p in photos if p.get("category") == "living" and p.get("category_source") is None and p.get("url")
              and not str(p.get("label_it") or "").strip()][:MAX_LIVING_TO_CHECK]
    with ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as ex:
        hall_results = list(ex.map(lambda p: _is_hall_photo(p["url"], p.get("original_url")), living))
    halls = 0
    for p, (is_hall, ok) in zip(living, hall_results):
        p["category_page"] = p.get("category")
        if ok and is_hall:
            p["category"] = "uncategorized"; p["category_source"] = "vision_hall"; halls += 1
        else:
            p["category_source"] = "page_label_checked" if ok else "page_fallback"
    summary = {"method": "exterior_outdoor_check", "checked": len(todo), "confirmed": confirmed, "living_checked": len(living), "halls_removed_from_living": halls,
               "swapped_exterior_outdoor": swapped, "excluded_as_other": excluded,
               "kept_page_label_after_failure": fallback, "not_checked_over_cap": len(over)}
    log.info(f"[Scraper] Exterior/outdoor check: {summary}")
    return summary


def resolve_uncategorized_photos(photos: list) -> list:
    """Runs the vision-QC fallback on every 'uncategorized' photo, in place."""
    for p in photos:
        if p.get("category") == "uncategorized":
            p["category"] = classify_uncategorized_photo(p["url"], p.get("original_url"))
            p["category_source"] = "vision"
    return photos


# ── Download selected photos ──────────────────────────────────────────────
# CHANGED July 10 2026: previously ran watermark removal eagerly during
# scraping itself. Simplified per feedback — since scraped scenes already
# pass through the standard scene-review UI before generation (same as
# manual uploads), there's no need to spend fal.ai cost removing watermarks
# during the scrape, especially if a scene gets swapped/rejected before
# generation ever happens. Now just downloads the raw image; the existing
# per-scene "remove_watermark" toggle (already built into the standard
# pipeline) is pre-checked instead — see build_standard_video_scenes_config
# — so actual removal happens at generation time via the same one existing
# mechanism manual uploads already use, not a separate eager pass here.

DOWNLOAD_ATTEMPTS = 3

# 2026-10-29: a photo whose long side is under this is not a usable start frame for the video model. The video is 1920 px wide, so a
# photo of this size is enlarged by 1920 / MIN = 1.9x. Measured on the 360 photos of every job we have (block 212): the real photos of
# the listings are 1024 px or more (1024, 1195, 1200, 1350, 1440, 1575, 1600), the rubbish is far below (a 486x273 thumbnail in 14 jobs,
# 4x2 pixel files in bd3f0f77). Nothing was seen between 486 and 1024, so any value in that gap separates the two groups; 1000 keeps every
# real photo seen so far. The check is on the pixels of the downloaded file, not on the size the page declares.
MIN_PHOTO_LONG_SIDE = 1000


def photo_usability(content: bytes) -> dict:
    """{"ok", "width", "height", "reason"}: ok when the bytes open as an image and the long side is at least MIN_PHOTO_LONG_SIDE."""
    import io
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as im:
            w, h = im.size
    except Exception as e:
        return {"ok": False, "width": None, "height": None, "reason": f"file non leggibile come immagine ({type(e).__name__})"}
    if max(w, h) < MIN_PHOTO_LONG_SIDE:
        return {"ok": False, "width": w, "height": h, "reason": f"foto troppo piccola: {w}x{h} px (lato lungo minimo {MIN_PHOTO_LONG_SIDE} px)"}
    return {"ok": True, "width": w, "height": h, "reason": None}


def download_photo(photo_url: str, output_dir: Path, filename_stem: str, fallback_url: str = None) -> dict:
    """
    Downloads one scraped photo. Returns:
      {"ok": bool, "path": str | None, "error": str | None, "url_used": str | None, "used_fallback": bool}
    2026-10-12: transient failures (timeouts, connection errors, HTTP 429/5xx) are retried
    with a short backoff; permanent ones (other 4xx, e.g. 404) are not. If the (possibly
    upgraded) URL fails, fallback_url (the original one) is tried -- see fetch_photo_bytes().
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dest_path = output_dir / f"{filename_stem}.jpg"
    fetched = fetch_photo_bytes(photo_url, fallback_url, timeout=20, attempts=DOWNLOAD_ATTEMPTS)
    if not fetched["ok"]:
        return {"ok": False, "path": None, "error": fetched["error"], "url_used": None, "used_fallback": False}
    use = photo_usability(fetched["content"])
    if not use["ok"]:     # permanent: downloading again gives the same file, so the retry rounds skip it ("unusable")
        return {"ok": False, "path": None, "error": use["reason"], "url_used": fetched["url_used"],
                "used_fallback": fetched["used_fallback"], "unusable": True}
    dest_path.write_bytes(fetched["content"])
    return {"ok": True, "path": str(dest_path), "error": None,
            "url_used": fetched["url_used"], "used_fallback": fetched["used_fallback"]}


DOWNLOAD_RETRY_WAITS = (8, 20)   # 2026-10-27: extra rounds for photos that still failed (a source CDN throttling bursts is transient)


def download_selected_photos(selection: dict, output_dir: Path) -> dict:
    """
    Downloads every photo in a select_photos() result - only the selected subset, not the full scraped list.
    Watermark removal is NOT done here (see module note above) - it's handled at generation time via the existing per-scene toggle.

    Returns the same {"selected": {...}, "gaps": [...]} structure, with each selected photo dict augmented with "local_path".
    2026-10-27: photos that still fail after download_photo's own retries are tried again in DOWNLOAD_RETRY_WAITS rounds (the
    first live golden-set run lost a whole draft because 6 of 6 downloads failed at the same moment). Order inside each category is
    kept. Photos that fail every round are dropped and reported in "download_failures" with the real error, and each is logged.
    This one function serves BOTH the from-url and the partner-payload preparation, so the retry is in one place only.
    """
    todo = [(cat, i, p) for cat, photos in selection["selected"].items() for i, p in enumerate(photos)]
    got, errors, unusable = {}, {}, []
    for rnd in range(len(DOWNLOAD_RETRY_WAITS) + 1):
        if rnd:
            log.warning(f"[Scraper] {len(todo)} photo(s) failed to download, retry round {rnd} in {DOWNLOAD_RETRY_WAITS[rnd - 1]}s")
            time.sleep(DOWNLOAD_RETRY_WAITS[rnd - 1])
        still = []
        for cat, i, p in todo:
            result = download_photo(p["url"], output_dir, f"{cat}_{i:02d}", p.get("original_url"))
            if result["ok"]:
                p["local_path"] = result["path"]
                p["url_used"] = result["url_used"]
                p["used_fallback"] = result["used_fallback"]
                got[(cat, i)] = p
            elif result.get("unusable"):
                errors[(cat, i)] = result["error"]
                unusable.append((cat, i, p))      # never retried: the file itself is the problem
            else:
                errors[(cat, i)] = result["error"]
                still.append((cat, i, p))
        todo = still
        if not todo:
            break
    download_failures = []
    for cat, i, p in unusable:
        download_failures.append({"category": cat, "url": p["url"], "error": errors[(cat, i)], "unusable": True})
        log.warning(f"[Scraper] photo dropped, not usable: {cat}[{i}] {p['url'][:90]} -> {errors[(cat, i)]}")
    for cat, i, p in todo:
        download_failures.append({"category": cat, "url": p["url"], "error": errors[(cat, i)]})
        log.warning(f"[Scraper] photo dropped after {len(DOWNLOAD_RETRY_WAITS) + 1} rounds: {cat}[{i}] {p['url'][:90]} -> {errors[(cat, i)]}")
    for cat, photos in selection["selected"].items():
        selection["selected"][cat] = [got[(cat, i)] for i in range(len(photos)) if (cat, i) in got]
    selection["download_failures"] = download_failures
    return selection


# ── Selection report (2026-10-12, 3A) ───────────────────────────────────────
# Saved in every job built from a listing/partner payload (job["selection_report"]) so it is
# possible to say AFTER the fact which photos existed, which were chosen, why a category was
# not used, whether the quality ranking really ran, and which downloads failed and why.

def build_selection_report(photos: list, selection: dict, scene_count_requested=None, premium: bool = False) -> dict:
    from datetime import datetime
    candidates = {}
    seen = set()
    for p in photos:
        u = p.get("url")
        if u in seen:
            continue
        seen.add(u)
        candidates.setdefault(p.get("category") or "uncategorized", []).append(u)

    selected = {}
    for cat, plist in selection.get("selected", {}).items():
        selected[cat] = [{
            "url": p.get("url"), "original_url": p.get("original_url"),
            "url_used": p.get("url_used"), "used_fallback": bool(p.get("used_fallback", False)),
            "resolution_upgraded": p.get("resolution_upgraded"),
            "rank_position": p.get("rank_position"), "rank_status": p.get("rank_status"),
            "quality": p.get("quality"),
        } for p in plist]

    used = {("outdoor" if c in ("outdoor_early", "outdoor_late") else c)
            for c, plist in selection.get("selected", {}).items() if plist}
    available = [c for c in PRIORITY_ORDER if candidates.get(c)]
    ranking = {}
    for p in photos:
        c = p.get("category")
        if c and p.get("rank_status") and c not in ranking:
            ranking[c] = p["rank_status"]

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "premium": bool(premium),
        "scene_count_requested": scene_count_requested,
        "photos_total": len(seen),
        "candidates_by_category": {c: len(v) for c, v in candidates.items()},
        "candidate_urls": candidates,
        "categories_available": available,
        "categories_used": [c for c in available if c in used],
        "categories_available_not_used": [c for c in available if c not in used],
        "selected": selected,
        "total_selected": selection.get("total_selected"),
        "ranking_by_category": ranking,
        "resolution_upgraded_count": sum(1 for p in photos if p.get("resolution_upgraded")),
        "fallback_used_count": sum(1 for lst in selected.values() for s in lst if s["used_fallback"]),
        "gaps": list(selection.get("gaps", [])),
        "download_failures": list(selection.get("download_failures", [])),
        # 2026-10-29: photo-quality filter of the selection (Claude vision): how many got a verdict and which were discarded
        "quality_checked": len({id(p) for p in photos if p.get("quality")}),
        "quality_rejected": [{"category": p.get("category"), "url": p.get("url"), "verdict": p.get("quality")}
                             for p in photos if p.get("quality_rejected")],
    }
    log.info(f"[Scraper] selection report: scenes_requested={scene_count_requested} "
             f"candidates={report['candidates_by_category']} used={report['categories_used']} "
             f"not_used={report['categories_available_not_used']} ranking={ranking} "
             f"fallback_used={report['fallback_used_count']} download_failures={len(report['download_failures'])}")
    for f in report["download_failures"]:
        log.warning(f"[Scraper] photo download failed ({f.get('category')}): {f.get('url')} -> {f.get('error')}")
    return report


# ── Narration/caption auto-generation from scraped description ─────────────
# Per the agreed decision: auto-generate narration/captions from the scraped
# listing text rather than leaving it fully manual. Plain text generation —
# no web_fetch tool/beta header needed here, since the description text is
# already in hand from extract_listing().

NARRATION_PROMPT = """You are writing a short, natural-sounding Italian voiceover script for a real estate property video, based on this listing description:

---
{description}
---

Property details: {address}, {price}{agency_instruction}

Write a single continuous narration script (in Italian) covering this property naturally and completely. Should flow as ONE continuous piece, no headers, no scene labels. {opening_instruction}

The description above may also include promotional or biographical text about the real estate agency itself (e.g. company history, founding year, mission statement, values) that has nothing to do with THIS specific property — ignore any such agency-about-us content entirely; describe only the property itself.

{feature_scope_instruction}

{scene_order_instruction}

STAY OBJECTIVE AND FACTUAL — this is important, not a minor style note:
- Do NOT add subjective or promotional adjectives that aren't grounded in the description (e.g. don't call a location "prestigious," "esclusivo," "meraviglioso," or similar, unless the description itself uses language like that). A small town is not automatically "prestigious" just because it's in a real estate video.
- Describe features plainly and factually (size, room count, what's present) rather than editorializing about how impressive they are.
- If the description itself is promotional in tone, you may reflect that tone — but do not ADD MORE embellishment than what's actually there. When in doubt, favor the more neutral, factual phrasing.
- A calm, clear, informative tone is the goal — not a marketing voiceover.

DO NOT include phone numbers or the price in the spoken narration — phone numbers are not pronounced intelligibly by text-to-speech and neither is needed in the voiceover itself.

AVOID legal/administrative real estate jargon that means nothing to a general viewer or sounds jarring when spoken aloud — for example, do not say "nuda proprietà" (a specific bare-ownership legal structure) or generic filler like "appartamento di proprietà" (just say "appartamento") unless that jargon is actually essential to understanding the listing. Use natural, plain descriptive language a real person would use when showing someone a property.

IMPORTANT: clearly state whether the property is FOR SALE or FOR RENT ("in vendita" or "in affitto") near the beginning of the narration, based on what the listing description actually says — do not leave this ambiguous or assume one over the other.

Include one brief sentence about the property's location and accessibility (e.g. proximity to services, central position) if the description supports it.

{closing_instruction}

Return ONLY the narration text (no JSON, no markdown, no preamble, no quotation marks around it).

Base everything on the actual property description above — don't invent details, features, or qualities not mentioned there.
"""

CAPTIONS_PROMPT = """Based on this property description:
---
{description}
---

Write a short on-screen caption (3-6 words, in Italian) for each of these scenes/categories: {categories}

Stay objective and factual — describe what's actually in the description plainly, don't add promotional or subjective adjectives (e.g. "moderna," "stupendo," "esclusivo") unless the description itself uses that language. A caption like "Cucina abitabile" is better than "Cucina abitabile moderna" if "moderna" isn't actually stated anywhere in the description.

Return ONLY a JSON object (no other text, no markdown fences): {{"category_name": "caption", ...}}
Base captions on the actual description — don't invent details or qualities not mentioned there.
"""

EXTEND_PROMPT = """The narration below was measured at {actual_secs:.1f} seconds of spoken audio, but should be closer to {target_secs:.0f} seconds. Extend it by about {extra_words} more words, using ONLY additional real detail from the original property description below — do not invent any facts, features, or details not present in the description, and do not add subjective/promotional adjectives (e.g. "prestigioso," "esclusivo") that aren't grounded in the description's own language. Stay factual and objective. Do not include phone numbers or price in the narration.

The property description may also include promotional or biographical text about the real estate agency itself (company history, founding year, mission, values) — do not pull any such agency-about-us content into the narration.

Preserve the narration's existing opening sentence (the agency introduction, if present) and closing sentence (the invitation to contact the agency, if present) essentially unchanged — add the extra detail to the descriptive portion in between, not by altering the opening/closing.

Original property description:
---
{description}
---

Current narration to extend:
---
{narration}
---

Return ONLY the full extended narration text (no JSON, no markdown, no preamble)."""

SHORTEN_PROMPT = """The narration below was measured at {actual_secs:.1f} seconds of spoken audio, but needs to fit within {target_secs:.0f} seconds — it MUST be shorter than that, not just close to it. Rewrite it at no more than {target_words} words. This is a hard ceiling — err on the side of cutting too much rather than too little.

Keep the most important property details (location, size, standout features) and drop secondary ones first. Always preserve the narration's existing opening sentence (the agency introduction, if present) and closing sentence (the invitation to contact the agency, if present) essentially unchanged — cut length from the descriptive middle portion, not from these bookends. Keep it flowing naturally. Stay factual and objective — don't add subjective or promotional adjectives that weren't already justified by the source material.

Current narration to shorten:
---
{narration}
---

Return ONLY the shortened narration text (no JSON, no markdown, no preamble)."""


TTS_MEASURE_ATTEMPTS = 3


def _retry_tts(once, attempts: int = TTS_MEASURE_ATTEMPTS) -> dict:
    """2026-10-24 (Patch Q): the ONE retry-with-backoff wrapper for the TTS steps (backoff 2 s, 4 s). `once` is a function with no
    arguments that returns a dict with "ok"; the last result is returned."""
    last = {"ok": False, "duration_secs": None, "audio_path": None}
    for n in range(attempts):
        last = once()
        if last.get("ok"):
            return last
        log.warning(f"[Scraper] TTS measurement attempt {n + 1}/{attempts} failed")
        if n < attempts - 1:
            time.sleep(2 * (n + 1))
    return last


def _measure_tts_duration(text: str, voice_id: str = None, attempts: int = TTS_MEASURE_ATTEMPTS, scene_secs: list = None) -> dict:
    """2026-10-12: retries the real TTS measurement on transient failure (backoff 2 s, 4 s).
    A single provider hiccup used to fail the whole job ("TTS measurement failed on initial narration").
    2026-10-15: scene_secs (fixed scene lengths) makes the audio come out already synchronised with the scenes."""
    return _retry_tts(lambda: _measure_tts_duration_once(text, voice_id, scene_secs), attempts)


def _measure_tts_duration_once(text: str, voice_id: str = None, scene_secs: list = None) -> dict:
    """Generates the real narration audio and measures its actual duration -- the
    only reliable way to know how long narration text will actually take
    to speak. Never estimated from word/character count for any decision
    that matters.

    2026-10-15 (Michele): this used to make ONE TTS call on the whole text, a different
    mechanism from the manual workflow (no pauses between sentences, no scene sync). It now
    goes through the single shared narration path (narration.synthesize_sentences /
    assemble_narration), so both workflows produce the same kind of audio. The sentence clips
    are returned so a different scene count can be applied later without paying for TTS again."""
    import tempfile
    from narration import synthesize_sentences, assemble_narration

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    try:
        syn = synthesize_sentences(text, voice_id)
        if not syn["ok"]:
            return {"ok": False, "duration_secs": None, "audio_path": None, "error": syn.get("error")}
        res = assemble_narration(syn["sentences"], syn["clips"], tmp_path, scene_secs=scene_secs)
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {"ok": False, "duration_secs": None, "audio_path": None}
        return {"ok": True, "duration_secs": res["duration_secs"], "audio_path": tmp_path,
                "sync": res.get("sync"), "sentences": syn["sentences"], "clips": syn["clips"]}
    except Exception as e:
        log.error(f"[Scraper] TTS measurement failed: {e}")
        return {"ok": False, "duration_secs": None, "audio_path": None, "error": str(e)}


def _resync_measurement(measurement: dict, scene_count: int):
    """Re-assembles the already generated sentence clips for a given scene count (no TTS call).
    Returns (audio_path, duration_secs, sync) or None when the clips are not available."""
    import tempfile
    from narration import assemble_narration
    if not measurement.get("clips"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    res = assemble_narration(measurement["sentences"], measurement["clips"], tmp_path,
                             scene_secs=[SCENE_CLIP_SECS] * scene_count)
    return tmp_path, res["duration_secs"], res.get("sync")


def _fade_out_and_trim(audio_path: str, target_secs: float, search_window_secs: float = 4.0) -> str:
    """
    Trims audio at or before target_secs. CHANGED July 9 2026: previously
    always cut at the exact millisecond mark and applied an 800ms fade —
    but since that fade lands on ACTUAL SPOKEN WORDS (not silence), it made
    the last words unintelligible, confirmed by direct listening.

    Now searches for a real pause (detected silence gap) at or shortly
    before target_secs and cuts there instead — a trim landing IN a
    natural gap between sentences needs no audible fade at all. Only
    falls back to a hard cut + short fade if no suitable gap is found
    nearby, which should now be rare.
    """
    from pydub import AudioSegment
    from pydub.silence import detect_silence

    audio = AudioSegment.from_file(audio_path)
    target_ms = int(target_secs * 1000)
    if len(audio) <= target_ms:
        return audio_path

    window_start_ms = max(0, target_ms - int(search_window_secs * 1000))
    search_region = audio[window_start_ms:target_ms + 500]
    silence_thresh = audio.dBFS - 16  # quieter than average speech level, relative not absolute

    try:
        silences = detect_silence(search_region, min_silence_len=200, silence_thresh=silence_thresh)
    except Exception:
        silences = []

    if silences:
        # cut at the MIDDLE of the last detected gap at or before target —
        # a real pause, so no fade is needed to avoid clipping a word
        last_gap_start, last_gap_end = silences[-1]
        cut_point = window_start_ms + (last_gap_start + last_gap_end) // 2
        cut_point = min(cut_point, target_ms + 500)
        trimmed = audio[:cut_point]
        log.info(f"[Scraper] Trimmed at a natural pause ({cut_point / 1000:.1f}s) instead of "
                 f"mid-speech — no fade needed.")
    else:
        # no natural gap found nearby — fall back to a hard cut with a
        # short fade (worse case, but rarer now that phone/price were
        # removed from narration, which also shortened it overall)
        trimmed = audio[:target_ms].fade_out(400)
        log.warning(f"[Scraper] No natural pause found near {target_secs}s — used a hard cut + short fade.")

    trimmed.export(audio_path, format="mp3")
    return audio_path


# 2026-10-12 (Michele): no on-screen/scene captions for URL jobs until the graphics are improved.
# One switch, used by both scene builders and by the caption generator (which then skips its Claude call).
SCENE_CAPTIONS_ENABLED = False


def _scene_caption(captions: dict, category: str) -> str:
    return captions.get(category, category) if SCENE_CAPTIONS_ENABLED else ""


def generate_captions_for_categories(description: str, categories: list) -> dict:
    """Generates short on-screen captions for exactly the given categories —
    called AFTER scene count/category selection is known (see
    generate_narration_and_derive_scenes), not before, since which
    categories end up selected depends on the real narration length."""
    if not SCENE_CAPTIONS_ENABLED:
        return {}
    prompt = CAPTIONS_PROMPT.format(description=description, categories=", ".join(categories))
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = _track_claude(client.messages.create(model=MODEL, max_tokens=1024,
                                             messages=[{"role": "user", "content": prompt}]))
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        json_str = raw
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence_match:
            json_str = fence_match.group(1)
        else:
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if brace_match:
                json_str = brace_match.group(0)
        return json.loads(json_str)
    except Exception as e:
        log.warning(f"[Scraper] Caption generation failed, using category names as fallback: {e}")
        return {cat: cat for cat in categories}


# ── Narration-first scene count derivation ──────────────────────────────────
# Redesigned July 9 2026 per explicit guidance: do NOT estimate timing from
# word/character count and force-fit narration into a pre-fixed video
# length. Instead — write one natural narration, measure it ONCE with real
# TTS, then DERIVE how many fixed-length scenes the video needs to contain
# it. This is simpler, cheaper (usually just 1 TTS call, at most 2), and
# avoids ever needing to awkwardly trim or pad narration to fit an
# arbitrary pre-decided box.

SCENE_CLIP_SECS = 5        # Luma Ray 2's native duration — zero snapping distortion

# 2026-07-21 unification (architecture assessment item 6): these now ALIAS
# the single shared source of truth in narration.py, instead of being an
# independent hardcoded pair. This file previously baked its own lead/trail
# silence directly into the narration audio (build_final_audio_track()),
# and assembly's _overlay_narration_audio() then added its OWN separate
# lead/trail blank-video padding on top -- confirmed real double-padding
# on every scraped job. Real padding now only ever applies ONCE, at
# assembly time, for both manual and scraped jobs (see create_job_from_url()
# in api_server.py). Kept as aliases, not removed, so every calculation
# below and build_final_audio_track() (now only used by this file's own
# standalone __main__ test block, not the live pipeline) keep working
# unchanged -- only the VALUES are now shared, not independently redefined.
from narration import LEAD_SECS, TRAIL_SECS, MAX_OVERFLOW_SECS, TOO_SHORT_THRESHOLD_SECS
LEAD_SILENCE_SECS  = LEAD_SECS    # was an independent 1.0 -- now the same 1.0 as narration.py
TRAIL_SILENCE_SECS = TRAIL_SECS   # was an independent 2.0 -- now the same 1.0 (the WhatsApp-trim evidence behind narration.py's value applies equally to scraped videos)
MIN_SCENES = 5             # 25s
MAX_SCENES = 7             # 35s -- stay "roughly 30s", not drift as wide as 20-40s
TARGET_SCENES = 6          # 30s -- the anchor; derived scene count should land here in the common case

# 2026-10-15 (Michele): the lead/trail blank frames are added AROUND the scenes at assembly time
# (api_server._overlay_narration_audio), they are not carved out of the scene time. So the speech has to fit
# scenes*5 s, may be at most TOO_SHORT_THRESHOLD_SECS shorter, and may run MAX_OVERFLOW_SECS past the last
# scene (absorbed by the trailing blank). Same two numbers narration.py uses for the manual workflow.
def _speech_band(scenes: int):
    return (scenes * SCENE_CLIP_SECS - TOO_SHORT_THRESHOLD_SECS, scenes * SCENE_CLIP_SECS + MAX_OVERFLOW_SECS)

MIN_SPEECH_SECS_FOR_RANGE, MAX_SPEECH_SECS_FOR_RANGE = _speech_band(MIN_SCENES)[0], _speech_band(MAX_SCENES)[1]

# 2026-10-12 (3B, Michele's decision): the STANDARD video is always exactly 6 scenes = 30 s (facade, living,
# kitchen, bedroom, bathroom, balcony/garden). 2026-10-15: speech band 26-32 s (was 24-28 with the buffers counted twice).
# Premium keeps its own wider band.
STANDARD_SCENES = TARGET_SCENES
STANDARD_MIN_SPEECH_SECS, STANDARD_MAX_SPEECH_SECS = _speech_band(STANDARD_SCENES)

# 2026-07-24 (backlog item 35): premium ~1-minute template. Same
# tightened-band mechanism as the standard format, just a wider target --
# a manual per-job toggle, URL-scrape only per explicit product decision.
MIN_SCENES_PREMIUM = 11    # ~55s
MAX_SCENES_PREMIUM = 13    # ~65s
MIN_SPEECH_SECS_FOR_RANGE_PREMIUM = _speech_band(MIN_SCENES_PREMIUM)[0]
MAX_SPEECH_SECS_FOR_RANGE_PREMIUM = _speech_band(MAX_SCENES_PREMIUM)[1]

# Premium sequence: outdoor appears twice -- once right after the facade,
# once again at the closing, per explicit product decision. Represented
# as two distinct pseudo-category keys (outdoor_early/outdoor_late) rather
# than a single "outdoor" entry, since build_standard_video_scenes_config()'s
# existing pattern groups ALL of one category's photos together and has
# no way to split them across two sequence positions -- this reuses that
# same "iterate an ordered category list, group by key" pattern rather
# than inventing a parallel one, just with outdoor pre-split into two keys.
PREMIUM_PRIORITY_ORDER = [
    "exterior", "outdoor_early", "living", "kitchen", "bedrooms",
    "bathrooms", "laundry", "office", "garage", "outdoor_late",
]
# Categories eligible for "expand instances" (fallback tier 1) --
# prioritizes outdoor and large rooms per explicit product decision.
_PREMIUM_EXPAND_PRIORITY = ["outdoor_early", "outdoor_late", "bedrooms", "living", "bathrooms", "kitchen"]
# New-to-the-template categories (fallback tier 2) -- only used if the
# listing actually has photos in them.
_PREMIUM_EXTRA_CATEGORIES = ["laundry", "office", "garage"]


def _claude_text_reply(client, prompt: str, max_tokens: int = 1024) -> str:
    response = _track_claude(client.messages.create(model=MODEL, max_tokens=max_tokens,
                                                    messages=[{"role": "user", "content": prompt}]))
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()


_IT_SPELL = None


def _italian_unknown_words():
    """The Italian dictionary lookup for italian_check (pyspellchecker): function(list of lowercase words) -> set of the unknown ones,
    or None when the package is not installed (italian_check then proofreads the whole text, which finds far fewer typos)."""
    global _IT_SPELL
    if _IT_SPELL is None:
        try:
            from spellchecker import SpellChecker
            _IT_SPELL = SpellChecker(language="it")
        except Exception as e:
            log.warning(f"[Scraper] Italian dictionary not available (pip install pyspellchecker): {e}")
            _IT_SPELL = False
    return (lambda words: set(_IT_SPELL.unknown(words))) if _IT_SPELL else None


def _proofread(texts: list, description: str = "", address: str = "", agency_name: str = "") -> dict:
    """2026-10-26: Italian spelling/grammar check of a narration (italian_check.py, ONE implementation for all narration paths).
    A dictionary finds the unknown words, Claude judges only those (a whole-text proofreading missed "garantono" with both Haiku 4.5 and
    Sonnet 5.5). Never raises. Returns italian_check.proofread()'s dict; checked=False when the Claude call did not work (the text goes on unchanged)."""
    import italian_check as ic
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        res = ic.proofread(texts, lambda prompt: _claude_text_reply(client, prompt, max_tokens=600),
                           " ".join(x for x in (description, address, agency_name) if x), unknown_fn=_italian_unknown_words())
    except Exception as e:
        log.warning(f"[Scraper] Italian check failed, text kept as it is: {e}")
        return {"texts": list(texts), "fixed": [], "remaining": [], "checked": False}
    if res["fixed"] or res["remaining"] or not res["checked"]:
        log.info(f"[Scraper] Italian check: checked={res['checked']} fixed={res['fixed']} remaining={res['remaining']}")
    return res


def _write_standard_scene_script(description: str, address: str, price: str, agency_name: str, sequence: list) -> dict:
    """2026-10-22 (Patch B): one sentence per scene for the standard video (see scene_script.py). Up to 3 Claude
    attempts (2026-10-22: was 2); each retry is told why the previous one was rejected by the fact check. Never raises.
    Returns {"ok", "sentences", "attempts", "problems", "error"}; ok=False means 'use the single-text narration'."""
    import scene_script as ss
    from narration import split_into_sentences
    labels = [CATEGORY_ITALIAN_LABELS.get(c, c) for c in sequence]
    base_prompt = ss.build_prompt(description, address, agency_name, labels)
    feedback, problems = "", []
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        for attempt in (1, 2, 3):
            sentences = ss.parse(_claude_text_reply(client, base_prompt + feedback))
            problems = (["the reply was not a JSON array of strings"] if sentences is None else
                        ss.validate(sentences, description, agency_name, price, split_fn=split_into_sentences))
            if not problems:
                lc = _proofread(sentences, description, address, agency_name)   # 2026-10-26: Italian check, applied only if the fact check still passes
                if lc["fixed"] and not lc["remaining"] and not ss.validate(lc["texts"], description, agency_name, price, split_fn=split_into_sentences):
                    sentences = lc["texts"]
                elif lc["fixed"] or lc["remaining"]:
                    log.warning(f"[Scraper] Per-scene script: Italian corrections not used (remaining {lc['remaining']}), original kept")
                return {"ok": True, "sentences": sentences, "attempts": attempt, "problems": [], "error": None}
            log.warning(f"[Scraper] Per-scene script attempt {attempt} rejected: {problems} | sentences: {sentences}")
            feedback = ("\n\nYour previous answer was REJECTED for these reasons. Fix all of them, return the full JSON array again:\n- "
                        + "\n- ".join(problems))
        return {"ok": False, "sentences": None, "attempts": 3, "problems": problems,
                "error": "per-scene script rejected by the fact check 3 times"}
    except Exception as e:
        return {"ok": False, "sentences": None, "attempts": 0, "problems": problems, "error": f"per-scene script failed: {e}"}


def _tighten_scene_script(sentences: list, bad: list, description: str, address: str, price: str, agency_name: str):
    """One rewrite of ONLY the sentences that are spoken too long for their scene. Returns the new 6 sentences when
    they pass the same fact check AND the untouched sentences are really unchanged; otherwise None."""
    import scene_script as ss
    from narration import split_into_sentences
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        revised = ss.parse(_claude_text_reply(client, ss.build_tighten_prompt(sentences, bad, description, agency_name)))
    except Exception as e:
        log.warning(f"[Scraper] Tighten pass failed, keeping the first script: {e}")
        return None
    if not revised or len(revised) != len(sentences):
        log.warning(f"[Scraper] Tighten rewrite not used: the reply was not {len(sentences)} sentences ({revised})")
        return None
    changed = {i for i, _ in bad}
    moved = [i + 1 for i in range(len(sentences)) if i not in changed and revised[i] != sentences[i]]
    if moved:
        log.warning(f"[Scraper] Tighten rewrite not used: it changed sentences that must stay as they are: {moved} ({revised})")
        return None
    problems = ss.validate(revised, description, agency_name, price, split_fn=split_into_sentences)
    if problems:
        log.warning(f"[Scraper] Tighten rewrite not used: it fails the fact check: {problems} ({revised})")
        return None
    return revised


# ── Anchor-driven timeline (2026-10-23, backlog 82, Patch J) ────────────────────────────────────────────────
# OFF by default: set PVS_ANCHORED_TIMELINE=1 in .env (and restart) to try it. When it is on and the standard 6-scene
# sequence is known, the narration is a free text whose room phrases are timed on the real audio; every failure
# (text rejected twice, no speech recogniser, plan outside the speed limits) falls back to the previous modes.
ANCHORED_MAX_ATTEMPTS = 7      # 2026-10-23 (Patch N): total Claude calls (was 3 in Patch M, where the estimate used them all up before any voice was measured)
ANCHORED_MAX_MEASURED = 3      # Patch N: texts that may be voiced and measured (each costs one TTS call + one speech recognition)
ANCHORED_SOFT_RETRIES = 2      # Patch N: a text rejected ONLY on the estimate is rewritten at most this many times in a row, then the real voice decides
ANCHORED_MIN_COVERAGE = 0.6      # share of the written words that must be found in the recorded audio


def anchored_timeline_enabled() -> bool:
    return os.environ.get("PVS_ANCHORED_TIMELINE", "0").strip().lower() in ("1", "true", "yes", "on")


def _anchored_narration(description: str, address: str, price: str, voice_id: str, agency_name: str, scene_sequence: list) -> dict:
    """Free narration + room anchors + real timing. Returns {"ok": True, "result": <dict in the shape of
    generate_narration_and_derive_scenes>, "tts_calls": n} or {"ok": False, "reason": str, "tts_calls": n}. Never raises."""
    import scene_script as ss
    import scene_timing as st
    import word_align as wa
    import word_timing as wt
    from narration import split_into_sentences
    tts_calls = 0
    labels = [CATEGORY_ITALIAN_LABELS.get(c, c) for c in scene_sequence]
    n = len(scene_sequence)
    base_prompt = ss.build_anchored_prompt(description, address, agency_name, labels)
    feedback, reason = "", "not attempted"
    measured, soft = 0, 0
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        for attempt in range(1, ANCHORED_MAX_ATTEMPTS + 1):
            parsed = ss.parse_anchored(_claude_text_reply(client, base_prompt + feedback, max_tokens=1500))
            if parsed is None:
                reason = "the reply was not the expected JSON object"
                feedback = "\n\nYour previous answer was not a JSON object with \"text\" and \"anchors\". Return exactly that object."
                log.warning(f"[Scraper] Anchored narration attempt {attempt}: {reason}")
                continue
            text, anchors = parsed
            problems = ss.validate_free_text(text, anchors, description, agency_name, price, split_fn=split_into_sentences, labels=labels)
            if problems and all(x.startswith(ss.ESTIMATE_PREFIX) for x in problems) and (soft >= ANCHORED_SOFT_RETRIES or attempt == ANCHORED_MAX_ATTEMPTS):
                # Patch N: only the ESTIMATE objects and it has had its tries: the measured audio is the real judge
                log.info(f"[Scraper] Anchored narration attempt {attempt}: only the estimate objects ({problems}), sending the text to the real voice")
                problems = []
            elif problems and all(x.startswith(ss.ESTIMATE_PREFIX) for x in problems):
                soft += 1
            if problems:
                reason = f"text rejected: {problems}"
                feedback = (f"\n\nYour previous text was (edit THIS text, do not start from zero):\n{text}\n\n"
                            "It was REJECTED for these reasons. Fix all of them, return the full JSON object again:\n- "
                            + "\n- ".join(problems))
                log.warning(f"[Scraper] Anchored narration attempt {attempt} rejected: {problems} | text: {text}")
                continue
            meas = _measure_tts_duration(text, voice_id)
            tts_calls += 1
            measured += 1
            soft = 0       # after a real measurement the next text gets its own estimate tries
            if not meas["ok"]:
                return {"ok": False, "reason": "TTS measurement failed", "tts_calls": tts_calls}
            recognised = wt.transcribe_words(meas["audio_path"])
            if recognised is None:
                return {"ok": False, "reason": "word timing (speech recogniser) not available", "tts_calls": tts_calls}
            tk = wa.tokens(text)
            al = wa.align(tk, recognised)
            if al["coverage"] < ANCHORED_MIN_COVERAGE:
                return {"ok": False, "reason": f"only {al['coverage']:.0%} of the text was found in the audio", "tts_calls": tts_calls}
            anchor_times, infos = [None] * n, []
            for a in anchors:
                if a["scene"] - 1 >= n:
                    continue
                idx = wa.find_phrase(tk, a["phrase"])[0]
                t = al["times"][idx][0]
                anchor_times[a["scene"] - 1] = t
                infos.append({"scene": a["scene"], "phrase": a["phrase"], "word_at": round(t, 3)})
            speech_secs = max(float(meas["duration_secs"]), float(al["end"]))
            plan = st.plan_from_anchors(anchor_times, speech_secs, [SCENE_CLIP_SECS] * n)
            log.info(f"[Scraper] Anchored narration attempt {attempt}: {len(ss.words(text))} words, speech {speech_secs:.1f}s "
                     f"({len(ss.words(text)) / max(speech_secs, 1.0):.2f} words/s), anchors {infos}, "
                     f"ok={plan['ok']}, speeds {[c['speed'] for c in plan['clips']]} | text: {text}")
            if plan["ok"]:
                timeline = {"mode": "anchored", "targets": plan["targets"], "cuts": plan["cuts"], "speeds": [c["speed"] for c in plan["clips"]],
                            "video_secs": plan["video_secs"], "anchors": infos, "anchor_offsets": plan["anchors"],
                            "align_coverage": round(al["coverage"], 3), "speech_secs": round(speech_secs, 3)}
                result = {
                    "ok": True, "narration_text": text, "audio_path": meas["audio_path"], "speech_duration_secs": speech_secs,
                    "scene_count": n, "video_duration_secs": plan["video_secs"], "tts_calls_used": tts_calls, "was_trimmed": False,
                    "sync": None, "error": None, "narration_mode": "anchored", "script_attempts": attempt, "script_tightened": False,
                    "script_fallback_reason": None, "timeline": timeline,
                }
                return {"ok": True, "result": result, "tts_calls": tts_calls}
            wps = len(ss.words(text)) / max(speech_secs, 1.0)
            reason = f"timing outside the speed limits: {plan['problems']}"
            feedback = ss.build_anchor_feedback(plan["problems"], infos, labels, wps, previous_text=text, speech_secs=speech_secs)
            if attempt == ANCHORED_MAX_ATTEMPTS or measured >= ANCHORED_MAX_MEASURED:
                break
        return {"ok": False, "reason": reason, "tts_calls": tts_calls}
    except Exception as e:
        log.warning(f"[Scraper] Anchored narration failed: {e}")
        return {"ok": False, "reason": f"error: {e}", "tts_calls": tts_calls}



# ── Block narration (2026-10-24, Patch Q) ────────────────────────────────────────────────────────────────────
# The video leads: 6 Luma clips of 5 s. The voice is written as 3 blocks of two scenes (scene_script.build_blocks_prompt), every block is
# recorded on its own (the shared sentence-TTS path of narration.py), measured, and fitted to its slot with the pause between blocks and a
# small tempo change (scene_timing.plan_blocks); the clip speeds / cut points come from the SAME solver as before (plan_from_anchors).
BLOCK_MAX_ATTEMPTS = 6          # Claude calls (a block rewritten on facts, length, or measured duration each costs one)


def _synthesize_block(text: str, voice_id: str = None) -> dict:
    """One block (2 sentences) -> {"ok", "clips" (the 2 pydub segments), "sentence_secs"}; retried like every TTS step."""
    from narration import synthesize_sentences

    def once():
        syn = synthesize_sentences(text, voice_id)
        if not syn["ok"]:
            return {"ok": False, "error": syn.get("error")}
        clips = list(syn["clips"])
        if len(clips) == 3:
            # Patch R4: sentence 2 + the closing invitation (its own sentence) = ONE timing unit, with a real pause between them
            import scene_timing as st
            from narration import join_clips
            clips = [clips[0], join_clips(clips[1:], pause_ms=int(round(st.CLOSING_PAUSE_SECS * 1000)))]
        if len(clips) != 2:
            return {"ok": False, "error": f"the block has {len(clips)} sentences, not 2"}
        return {"ok": True, "clips": clips, "sentence_secs": [len(c) / 1000.0 for c in clips]}
    return _retry_tts(once)


def _block_segment(clips: list, rate: float, offset: float = None) -> object:
    """The block as ONE segment at normal tempo, with the silence between its two sentences written so that, AFTER the tempo
    change `rate`, the second sentence starts exactly SECOND_OFFSET s after the block starts (scene_timing.sentence_pause)."""
    import scene_timing as st
    from narration import join_clips
    d1 = len(clips[0]) / 1000.0
    kw = {} if offset is None else {"offset": offset}
    return join_clips(clips, pause_ms=int(round(st.sentence_pause_pre(d1, rate, **kw) * 1000)))


def _assemble_block_audio(segments: list, rates: list, starts: list) -> dict:
    """Places the blocks (tempo + silence) in ONE audio file. Returns {"ok", "audio_path", "duration_secs", "starts_secs"}."""
    import tempfile
    from narration import assemble_blocks
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = f.name
    res = assemble_blocks(segments, rates, starts, path)
    res["audio_path"] = path
    return res


def _block_narration(description: str, address: str, price: str, voice_id: str, agency_name: str, scene_sequence: list) -> dict:
    """Narration in 3 blocks fitted to the fixed 5 s clips. Returns {"ok": True, "result": <dict in the shape of
    generate_narration_and_derive_scenes>, "tts_calls": n} or {"ok": False, "reason": str, "tts_calls": n}. Never raises."""
    import scene_script as ss
    import scene_timing as st
    from narration import split_into_sentences
    n = len(scene_sequence)
    labels = [CATEGORY_ITALIAN_LABELS.get(c, c) for c in scene_sequence]
    base_prompt = ss.build_blocks_prompt(description, address, agency_name, labels, scene_sequence)
    feedback, reason = "", "not attempted"
    tts_calls, cache = 0, {}
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        for attempt in range(1, BLOCK_MAX_ATTEMPTS + 1):
            raw_reply = _claude_text_reply(client, base_prompt + feedback, max_tokens=1200)
            blocks = ss.parse_blocks(raw_reply)
            if blocks is None:
                reason = "the reply was not the expected JSON object"
                # 2026-10-25 (Patch R3): the feedback of the previous attempt is KEPT (draft dd4d2b79: a lost feedback made attempt 6 start
                # from zero and ignore the measured-duration corrections of attempts 2-4)
                feedback = feedback + '\n\nYour previous answer was not a JSON object {"blocks": [3 strings]}. Return exactly that object, nothing else.'
                log.warning(f"[Scraper] Block narration attempt {attempt}: {reason} | reply starts: {str(raw_reply)[:300]!r}")
                continue
            problems = ss.validate_blocks(blocks, description, agency_name, price, split_fn=split_into_sentences, scene_sequence=scene_sequence)
            if problems:
                reason = f"blocks rejected: {problems}"
                feedback = ("\n\nYour previous blocks were:\n" + json.dumps({"blocks": blocks}, ensure_ascii=False)
                            + "\n\nThey were REJECTED for these reasons. Fix all of them, return the full JSON object again:\n- " + "\n- ".join(problems))
                log.warning(f"[Scraper] Block narration attempt {attempt} rejected: {problems} | blocks: {blocks}")
                continue
            # 2026-10-26: Italian spelling/grammar check BEFORE any voice is spent on the text (draft 7ff8ec4b: "garantono"). The corrections are word
            # replacements; they are used only if the text still passes every check above. Anything left over goes back to the model as feedback.
            lc = _proofread(blocks, description, address, agency_name)
            if lc["fixed"] or lc["remaining"]:
                fixed_ok = (not ss.validate_blocks(lc["texts"], description, agency_name, price, split_fn=split_into_sentences, scene_sequence=scene_sequence))
                if lc["fixed"] and not lc["remaining"] and fixed_ok:
                    log.info(f"[Scraper] Block narration attempt {attempt}: Italian corrections applied {lc['fixed']}")
                    blocks = lc["texts"]
                elif attempt < BLOCK_MAX_ATTEMPTS:
                    import italian_check as _ic
                    reason = f"Italian errors: {lc['fixed'] + lc['remaining']}"
                    feedback = ("\n\nYour previous blocks were:\n" + json.dumps({"blocks": blocks}, ensure_ascii=False)
                                + "\n\nThey were REJECTED because of language errors. Fix them, keep everything else, return the full JSON object again:\n- "
                                + "\n- ".join(_ic.feedback_lines(lc["fixed"] + lc["remaining"])))
                    log.warning(f"[Scraper] Block narration attempt {attempt} rejected: {reason} | blocks: {blocks}")
                    continue
                else:
                    log.warning(f"[Scraper] Block narration: last attempt keeps its text, Italian errors left: {lc['fixed'] + lc['remaining']}")
            syn_list = []
            for bi, b in enumerate(blocks):
                if b not in cache:
                    # only the last block carries the closing invitation: spoken as its own sentence (Patch R4)
                    syn = _synthesize_block(ss.closing_as_sentence(b, agency_name) if bi == len(blocks) - 1 else b, voice_id)
                    tts_calls += 1
                    if not syn["ok"]:
                        return {"ok": False, "reason": "TTS failed on a narration block", "tts_calls": tts_calls}
                    cache[b] = syn
                syn_list.append(cache[b])
            # Patch R5 (2026-10-25): ONE authority. The clip plan (speed limits) decides whether the blocks fit; tempo of each block and
            # the silences between blocks are chosen by scene_timing.plan_blocks_joint (the old plan_blocks pre-judged with its own windows).
            sent_secs = [c["sentence_secs"] for c in syn_list]
            offs_nominal = st.second_sentence_offsets(n)
            plan = st.plan_blocks_joint(sent_secs, n)
            segs = [_block_segment(c["clips"], r, o) for c, r, o in zip(syn_list, plan["rates"], offs_nominal)]
            durations = [len(sg) / 1000.0 for sg in segs]
            log.info(f"[Scraper] Block narration attempt {attempt}: sentences {[['%.1f' % x for x in ss_] for ss_ in sent_secs]}, "
                     f"blocks {['%.1f' % d for d in durations]}, starts {plan['starts']}, rates {plan['rates']}, gaps {plan['gaps']}, "
                     f"speeds {[c['speed'] for c in plan['clip_plan']['clips']]}, ok={plan['ok']}, "
                     f"problems {plan['problems']} | blocks: {blocks}")
            if not plan["ok"]:
                reason = f"sentences outside their scenes: {plan['problems']}"
                if attempt < BLOCK_MAX_ATTEMPTS:
                    feedback = ss.build_sync_feedback(plan["problems"], blocks)
                    continue
                # last attempt: do not throw the text away - the checks below try the block starts alone (less strict); only if the clip
                # speeds still cannot follow, the narration falls back (reason recorded)
                log.warning(f"[Scraper] Block narration: last attempt does not fit sentence by sentence ({plan['problems']}); trying block starts only")
            audio = _assemble_block_audio(segs, plan["rates"], plan["starts"])
            if not audio.get("ok"):
                return {"ok": False, "reason": "block audio assembly failed", "tts_calls": tts_calls}
            speech_secs = float(audio["duration_secs"])
            per = n // len(blocks)
            real_starts = [float(x) for x in audio["starts_secs"]]
            second_offsets = [(sent_secs[b][0] + st.sentence_pause_pre(sent_secs[b][0], plan["rates"][b], offset=offs_nominal[b])) / plan["rates"][b]
                              for b in range(len(blocks))]
            full = st.sentence_anchor_times(real_starts, second_offsets, n, per)          # every scene tied to its own sentence
            blocks_only = [None] * n
            for b in range(1, len(blocks)):
                blocks_only[b * per] = real_starts[b]
            clip_plan = st.plan_from_anchors(full, speech_secs, [SCENE_CLIP_SECS] * n)
            sentence_sync = clip_plan["ok"]
            if not sentence_sync:
                log.warning(f"[Scraper] Block narration attempt {attempt}: scenes cannot all follow their sentence: {clip_plan['problems']}")
                if attempt < BLOCK_MAX_ATTEMPTS:
                    reason = f"sentences outside their scenes: {clip_plan['problems']}"
                    feedback = ss.build_sync_feedback(clip_plan["problems"], blocks)
                    continue
                clip_plan = st.plan_from_anchors(blocks_only, speech_secs, [SCENE_CLIP_SECS] * n)      # last try: block starts only
                if not clip_plan["ok"]:
                    reason = f"clip speeds outside the limits: {clip_plan['problems']}"
                    log.warning(f"[Scraper] Block narration attempt {attempt}: {reason}")
                    return {"ok": False, "reason": reason, "tts_calls": tts_calls}
            # the check with the real audio: a room is only named while its picture is on screen (word timing of the final mp3)
            word_check = {"checked": False, "violations": 0, "rooms": []}
            if any(ss.named_rooms(x) for b_ in blocks for x in split_into_sentences(b_)):
                import word_timing as wt
                import word_align as wa
                recognised = wt.transcribe_words(audio["audio_path"])
                if recognised is None:
                    word_check["note"] = "speech recogniser not available: room words NOT verified"
                    log.warning(f"[Scraper] Block narration attempt {attempt}: {word_check['note']}")
                else:
                    al = wa.align(wa.tokens(" ".join(blocks)), recognised)
                    if al["coverage"] < ANCHORED_MIN_COVERAGE:
                        word_check["note"] = f"only {al['coverage']:.0%} of the text found in the audio: room words NOT verified"
                        log.warning(f"[Scraper] Block narration attempt {attempt}: {word_check['note']}")
                    else:
                        rooms = ss.check_room_words(blocks, scene_sequence, al["times"], clip_plan["cuts"], split_into_sentences)
                        bad = [r_ for r_ in rooms if not r_["ok"]]
                        word_check = {"checked": True, "violations": len(bad), "rooms": rooms, "coverage": round(al["coverage"], 3)}
                        log.info(f"[Scraper] Block narration attempt {attempt}: room words {rooms}")
                        if bad and attempt < BLOCK_MAX_ATTEMPTS:
                            reason = f"room words outside their pictures: {bad}"
                            feedback = ss.build_word_check_feedback(bad, blocks)
                            continue
                        if bad:
                            log.warning(f"[Scraper] Block narration: accepted on the last attempt WITH room words outside their pictures: {bad}")
            used = full if sentence_sync else blocks_only
            infos = []
            for i_, t_ in enumerate(used):
                if t_ is not None and i_ > 0:
                    infos.append({"scene": i_ + 1, "phrase": f"(block {i_ // per + 1}, sentence {i_ % per + 1})", "word_at": round(float(t_), 3)})
            timeline = {"mode": "anchored", "method": "blocks", "sentence_sync": sentence_sync, "targets": clip_plan["targets"],
                        "cuts": clip_plan["cuts"], "speeds": [c["speed"] for c in clip_plan["clips"]], "video_secs": clip_plan["video_secs"],
                        "anchors": infos, "anchor_offsets": clip_plan["anchors"], "speech_secs": round(speech_secs, 3),
                        "word_check": word_check,
                        "blocks": [{"text": b, "start": real_starts[i], "rate": plan["rates"][i], "secs": round(durations[i], 3),
                                    "sentence_secs": [round(x, 3) for x in sent_secs[i]], "second_start": round(real_starts[i] + second_offsets[i], 3)}
                                   for i, b in enumerate(blocks)]}
            result = {
                "ok": True, "narration_text": " ".join(blocks[:-1] + [ss.closing_as_sentence(blocks[-1], agency_name)]), "audio_path": audio["audio_path"], "speech_duration_secs": speech_secs,
                "scene_count": n, "video_duration_secs": clip_plan["video_secs"], "tts_calls_used": tts_calls, "was_trimmed": False,
                "sync": None, "error": None, "narration_mode": "anchored", "script_attempts": attempt, "script_tightened": False,
                "script_fallback_reason": None, "timeline": timeline,
            }
            return {"ok": True, "result": result, "tts_calls": tts_calls}
        return {"ok": False, "reason": reason, "tts_calls": tts_calls}
    except Exception as e:
        log.warning(f"[Scraper] Block narration failed: {e}")
        return {"ok": False, "reason": f"error: {e}", "tts_calls": tts_calls}


# ── Scene facts: what each of the 6 scenes plainly shows (2026-10-28, Michele option 1) ──
# The voice writers only knew the listing text: a thin listing gave short sentences and room names heard over the wrong scene (draft 832cb4f4).
# ONE vision call looks at the 6 selected photos. Its facts are appended to the listing text that BOTH the prompt and the validator read,
# so every existing fact rule applies to them unchanged. Facts hold no digits, so the number checks still come from the listing alone.
def scene_facts_enabled() -> bool:
    return os.environ.get("PVS_SCENE_FACTS", "0").strip().lower() in ("1", "true", "yes", "on")


SCENE_FACTS_PROMPT = (
    "You see {n} photos of ONE property, in the order of the scenes of a short video: photo 1 is scene 1, and so on.\n"
    "For each photo write ONE short Italian phrase (4 to 12 words) that says only what is PLAINLY VISIBLE: natural light, windows, "
    "the colour of the floor and walls, the sense of space, a view. Rules:\n"
    "- Describe only what you can clearly see. No numbers at all (say finestre, not due finestre). Give COLOURS, never materials "
    "(say pavimento rosso, not terracotta or cotto; pareti chiare, not intonaco).\n"
    "- Never name the room or its use (no cucina, bagno, stanza, camera) and never say it is empty: the scene already says which room it is.\n"
    "- For a view, say what is seen (alberi, edifici, cielo), never what kind of place it is (no piazza, cortile, strada).\n"
    "- No judgement of condition or value (new, renovated, luxury, recent), no price, no location.\n"
    "- If the room is empty, do not mention furniture: speak of light, windows, floor and space.\n"
    "- If you cannot say anything certain about a photo, write an empty string for it.\n"
    "Answer with ONLY a JSON array of {n} strings, in the photo order."
)
_SCENE_FACT_VISIBLE_OK = ("piscin", "giardin", "terrazz", "balcon", "vista", "mare", "lago", "parco", "pergol", "portic", "veranda", "uliv", "cancell", "camin")
_SCENE_FACT_WORDS = ("ristruttur", "recent", "lusso", "pregio", "€", "euro", "prezzo", "vuot", "terracott", "cotto", "ceramic", "legno",
                     "stanza", "cucina", "bagno", "camera", "soggiorno", "salone",
                     "piazz", "cortil", "strad", "cement", "pietra", "mattoni", "intonac", "metall", "ferro", "vetro", "granit", "graniglia", "plastic")


def _scene_fact_banned() -> tuple:
    # a fact is a place where a word becomes allowed in the voice, so it must not introduce a word a photo cannot prove: the promotional
    # stems and the feature stems of the validator (scene_script) are read from there, except the few that a photo can show
    import scene_script as ss
    return _SCENE_FACT_WORDS + tuple(ss._PROMO_STEMS) + tuple(x for x in ss._FEATURE_STEMS if x not in _SCENE_FACT_VISIBLE_OK)


def parse_scene_facts(raw: str, n: int):
    # n short strings, or None when the reply is not usable. A phrase with a banned word, a digit or over 14 words becomes empty.
    try:
        data = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
    except Exception:
        return None
    if not isinstance(data, list) or len(data) != n or not all(isinstance(x, str) for x in data):
        return None
    facts, banned = [], _scene_fact_banned()
    for x in data:
        x = " ".join(x.split())
        if len(x.split()) > 14 or any(c.isdigit() for c in x) or any(w in x.lower() for w in banned):
            x = ""
        facts.append(x)
    return facts if any(facts) else None


def describe_scenes_for_narration(scene_photos: list) -> dict:
    # ONE vision call for the scene photos in scene order. Never raises: {"ok": True, "facts": [...]} or {"ok": False, "error": str}
    n = len(scene_photos)
    try:
        content = [{"type": "text", "text": SCENE_FACTS_PROMPT.format(n=n)}]
        for i, p in enumerate(scene_photos):
            fetched = fetch_photo_bytes(p.get("url"), p.get("original_url"), timeout=15)
            if not fetched["ok"]:
                why = fetched.get("error")
                return {"ok": False, "error": f"photo {i + 1} could not be downloaded: {why}"}
            content.append({"type": "text", "text": f"Photo {i + 1}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _image_b64_for_vision(fetched["content"])}})
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = _track_claude(client.messages.create(model=MODEL, max_tokens=700, messages=[{"role": "user", "content": content}]))
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        facts = parse_scene_facts(raw, n)
        if facts is None:
            return {"ok": False, "error": "the reply was not a usable list of facts: " + raw[:200]}
        return {"ok": True, "facts": facts}
    except Exception as e:
        return {"ok": False, "error": f"error: {e}"}


def scene_facts_block(facts: list, scene_sequence: list) -> str:
    # scene numbers are WORDS and there is no room label here: digits would weaken the number checks, and the labels hold words such as
    # giardino and terrazza that the validator would then accept for every listing
    words = ["one", "two", "three", "four", "five", "six", "seven", "eight"]
    lines = [f"Scene {words[i]}: {fact}" for i, fact in enumerate(facts) if fact and i < len(words)]
    return "WHAT THE PHOTOS PLAINLY SHOW (in the order of the video; true facts about this property, usable like the rest of the listing text):\n" + "\n".join(lines)


def standard_scene_photos(selection: dict) -> list:
    return [photo for _, photo in standard_scene_slots(selection)]


def generate_narration_and_derive_scenes(
    description: str, address: str = None, price: str = None, voice_id: str = None,
    premium: bool = False, agency_name: str = None, scene_category_order: list = None,
    scene_sequence: list = None, scene_photos: list = None,
) -> dict:
    # the ONE entry point of both workflows. With PVS_SCENE_FACTS on (standard 6-scene video only) the plainly visible facts of the scene
    # photos are appended to the listing text, then the unchanged narration core runs. Any failure leaves the listing text as it was.
    facts, facts_error = None, None
    if (scene_photos and scene_facts_enabled() and (not premium) and scene_sequence
            and len(scene_sequence) == STANDARD_SCENES and len(scene_photos) == STANDARD_SCENES):
        info = describe_scenes_for_narration(scene_photos)
        if info["ok"]:
            facts = info["facts"]
            description = (description or "") + "\n\n" + scene_facts_block(facts, scene_sequence)
        else:
            facts_error = info["error"]
            log.warning(f"[Scraper] Scene facts not used: {facts_error}")
    result = _generate_narration_core(description, address, price, voice_id, premium, agency_name, scene_category_order, scene_sequence)
    if isinstance(result, dict):
        result["scene_facts"] = facts
        result["scene_facts_error"] = facts_error
    return result


def _generate_narration_core(
    description: str, address: str = None, price: str = None, voice_id: str = None,
    premium: bool = False, agency_name: str = None, scene_category_order: list = None,
    scene_sequence: list = None,
) -> dict:
    """
    Writes ONE natural narration (no artificial length target), measures
    it ONCE with real TTS, then derives how many fixed SCENE_CLIP_SECS
    scenes the video needs (narration + lead + trail silence, rounded up).

    Keeps the result within a tightened band around 30s (MIN_SCENES=5 to
    MAX_SCENES=7, i.e. 25-35s) rather than letting it drift freely — if the
    natural narration falls outside MIN_SPEECH_SECS_FOR_RANGE /
    MAX_SPEECH_SECS_FOR_RANGE, ONE correction pass is made (shorten if too
    long, extend with real description content if too short), then
    re-measured. This is symmetric: too-long and too-short are both
    actively corrected toward the band, not just clamped afterward — a
    silent clamp-only approach could otherwise leave several scenes near
    the end playing with no narration if a listing's real content happens
    to be sparse.

    Bounded to at most 2 real TTS calls (1 initial + 1 correction pass). A
    fade-out trim remains as an absolute last-resort safety net if a
    single shorten pass still isn't enough.

    Returns:
      {"ok": bool, "narration_text": str, "audio_path": str | None (bare
       narration, NOT yet padded with lead/trail — see
       build_final_audio_track), "speech_duration_secs": float | None,
       "scene_count": int | None, "video_duration_secs": int | None,
       "tts_calls_used": int, "was_trimmed": bool, "error": str | None}
    """
    if agency_name:
        agency_instruction = f"\nAgency: {agency_name}"
        opening_instruction = f'Open the narration with the agency presenting the property, e.g. "{agency_name} presenta..." (adapt naturally to flow well).'
        closing_instruction = (f'End the narration with a brief, natural closing line inviting the viewer to contact {agency_name} by name '
                                f'for more information (e.g. "Contattate {agency_name} per maggiori informazioni") -- do NOT include a phone '
                                f'number or email, just the agency name and a general invitation to get in touch.')
    else:
        agency_instruction = ""
        opening_instruction = ""
        closing_instruction = ('End the narration with a brief, natural closing line inviting the viewer to contact the agency for more '
                                'information (e.g. "Contattate l\'agenzia per maggiori informazioni" or similar) -- do NOT include a phone '
                                'number or email in this closing line, just a general invitation to get in touch.')

    feature_scope_instruction = (
        "This is a longer-format video (~60 seconds) -- you may cover the property's features in fuller detail than a quick "
        "highlight reel, while still avoiding an exhaustive room-by-room list."
        if premium else
        "This is a SHORT-format video (~30 seconds) -- mention only 2-3 standout features of the property rather than "
        "describing every room; a brief highlight, not an exhaustive tour. The finished narration must take about 29 seconds "
        "to speak aloud (roughly 68-78 Italian words in total, including the opening and the closing line)."
    )

    if scene_category_order:
        labels = [CATEGORY_ITALIAN_LABELS.get(c, c) for c in scene_category_order]
        scene_order_instruction = (
            "The video will show the property in this exact order: " + ", poi ".join(labels) + ". "
            "Describe the property's features roughly following this same order, so the narration matches what's "
            "visible on screen at each point -- don't jump back to an earlier room after moving on."
        )
    else:
        scene_order_instruction = ""

    # 2026-10-22 (Patch B, Michele): the STANDARD video gets one sentence per scene, written knowing which room each
    # scene shows (scene_script.py). Used only when the caller passes the 6-scene sequence; anything else (premium,
    # no sequence, a script the fact check rejects twice) keeps the single-text path below, unchanged.
    # 2026-10-23 (Patch J): the anchor-driven timeline is tried first when it is switched on; any failure falls through
    # to the modes below, unchanged. The TTS calls it spent are added to the count.
    anchored_calls, anchored_fallback = 0, None
    if anchored_timeline_enabled() and (not premium) and scene_sequence and len(scene_sequence) == STANDARD_SCENES:
        _an = _block_narration(description, address, price, voice_id, agency_name, scene_sequence)   # 2026-10-24 (Patch Q): blocks replace the free anchored text
        anchored_calls = _an["tts_calls"]
        if _an["ok"]:
            return _an["result"]
        anchored_fallback = _an["reason"]
        log.warning(f"[Scraper] Anchored timeline not used, falling back to the previous narration modes: {anchored_fallback}")

    per_scene = False
    script_info = None
    narration_text = None
    if (not premium) and scene_sequence and len(scene_sequence) == STANDARD_SCENES:
        script_info = _write_standard_scene_script(description, address, price, agency_name, scene_sequence)
        if script_info["ok"]:
            narration_text = " ".join(script_info["sentences"])
            per_scene = True
        else:
            log.warning(f"[Scraper] Per-scene script not used, falling back to the single-text narration: "
                        f"{script_info.get('error')} {script_info.get('problems')}")

    client = None
    if not per_scene:
        prompt = NARRATION_PROMPT.format(
            description=description, address=address or "non specificato", price=price or "non specificato",
            agency_instruction=agency_instruction, opening_instruction=opening_instruction,
            feature_scope_instruction=feature_scope_instruction, closing_instruction=closing_instruction,
            scene_order_instruction=scene_order_instruction,
        )
        try:
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = _track_claude(client.messages.create(model=MODEL, max_tokens=2048,
                                                 messages=[{"role": "user", "content": prompt}]))
            narration_text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        except Exception as e:
            return {"ok": False, "narration_text": "", "audio_path": None, "speech_duration_secs": None,
                    "scene_count": None, "video_duration_secs": None, "tts_calls_used": 0,
                    "was_trimmed": False, "error": f"initial narration generation failed: {e}"}

    if not narration_text:
        return {"ok": False, "narration_text": "", "audio_path": None, "speech_duration_secs": None,
                "scene_count": None, "video_duration_secs": None, "tts_calls_used": 0,
                "was_trimmed": False, "error": "empty narration returned"}

    if not per_scene:
        _lc = _proofread([narration_text], description, address, agency_name)   # 2026-10-26: Italian check of the single text (replacements only)
        if _lc["fixed"] and not _lc["remaining"]:
            narration_text = _lc["texts"][0]

    # 2026-10-15: the standard video has a FIXED scene count, so the audio is built already synchronised with it.
    # Premium derives its scene count from the speech, so it is measured plain first and synchronised afterwards.
    _fixed_scene_secs = None if premium else [SCENE_CLIP_SECS] * STANDARD_SCENES
    measurement = _measure_tts_duration(narration_text, voice_id, scene_secs=_fixed_scene_secs)
    tts_calls_used = 1 + anchored_calls
    if not measurement["ok"]:
        return {"ok": False, "narration_text": narration_text, "audio_path": None,
                "speech_duration_secs": None, "scene_count": None, "video_duration_secs": None,
                "tts_calls_used": tts_calls_used, "was_trimmed": False,
                "error": "TTS measurement failed on initial narration"}

    speech_secs = measurement["duration_secs"]
    audio_path = measurement["audio_path"]
    sync = measurement.get("sync")
    was_trimmed = False

    # Per-scene mode: sentences 1-5 must be spoken within their own scene. If the real TTS shows some are too long,
    # ONE rewrite pass shortens only those sentences (the others stay unchanged), then the audio is measured again.
    # Adopted only if it is valid and no worse; otherwise the first version stays. Same two-TTS-call budget as before.
    scene_script_sentences = script_info["sentences"] if per_scene else None
    script_tightened = False
    if per_scene:
        import scene_script as _ss
        bad = _ss.spill_problems(sync, STANDARD_SCENES)
        if bad and (tts_calls_used - anchored_calls) < 2:
            revised_sents = _tighten_scene_script(scene_script_sentences, bad, description, address, price, agency_name)
            log.info(f"[Scraper] Tighten pass: sentences too long {bad} -> rewrite {'received' if revised_sents else 'not usable'}")
            if revised_sents:
                remeasure = _measure_tts_duration(" ".join(revised_sents), voice_id, scene_secs=_fixed_scene_secs)
                tts_calls_used += 1
                if remeasure["ok"] and len(_ss.spill_problems(remeasure.get("sync"), STANDARD_SCENES)) <= len(bad):
                    scene_script_sentences = revised_sents
                    narration_text = " ".join(revised_sents)
                    speech_secs, audio_path = remeasure["duration_secs"], remeasure["audio_path"]
                    measurement, sync = remeasure, remeasure.get("sync")
                    script_tightened = True
                else:
                    log.info(f"[Scraper] Tighten pass: rewrite measured but not better (remaining too long: {_ss.spill_problems(remeasure.get('sync'), STANDARD_SCENES)}), first script kept")

    # Single correction pass if outside the tightened band — symmetric:
    # both directions are actively corrected, not just clamped.
    if premium:
        _min_speech, _max_speech = MIN_SPEECH_SECS_FOR_RANGE_PREMIUM, MAX_SPEECH_SECS_FOR_RANGE_PREMIUM
        _min_scenes, _max_scenes = MIN_SCENES_PREMIUM, MAX_SCENES_PREMIUM
    else:
        _min_speech, _max_speech = STANDARD_MIN_SPEECH_SECS, STANDARD_MAX_SPEECH_SECS
        _min_scenes = _max_scenes = STANDARD_SCENES

    if speech_secs > _max_speech:
        target_speech = _max_speech - 2.0  # margin under the ceiling, not right at the edge
        naive_target_words = len(narration_text.split()) * (target_speech / speech_secs)
        target_words = max(15, int(naive_target_words * 0.85))  # models tend to undershoot cuts
        if not per_scene:   # per-scene mode never rewrites the whole text (it would break one-sentence-per-scene)
            try:
                shorten_prompt = SHORTEN_PROMPT.format(actual_secs=speech_secs, target_secs=target_speech,
                                                         target_words=target_words, narration=narration_text)
                response = _track_claude(client.messages.create(model=MODEL, max_tokens=2048,
                                                     messages=[{"role": "user", "content": shorten_prompt}]))
                revised = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
                if revised:
                    remeasure = _measure_tts_duration(revised, voice_id, scene_secs=_fixed_scene_secs)
                    tts_calls_used += 1
                    if remeasure["ok"]:
                        narration_text, speech_secs, audio_path = revised, remeasure["duration_secs"], remeasure["audio_path"]
                        measurement, sync = remeasure, remeasure.get("sync")
            except Exception as e:
                log.warning(f"[Scraper] Shorten pass failed, proceeding as-is: {e}")

        if speech_secs > _max_speech and audio_path:
            # still over after one pass — hard cap and fade-trim rather
            # than build an ever-longer video
            audio_path = _fade_out_and_trim(audio_path, _max_speech)
            speech_secs = _max_speech
            was_trimmed = True
            sync = None   # the audio was cut after the sync plan was made: the plan no longer describes it

    elif speech_secs < _min_speech and not per_scene:
        target_speech = _min_speech + 3.0  # margin above the floor
        words_per_second = len(narration_text.split()) / speech_secs  # measured from this narration, not a hardcoded estimate -- 2026-10-02 fix: WORDS_PER_SECOND_ESTIMATE was referenced but never defined anywhere, crashing with NameError (500 on /v1/videos) any time narration landed below the minimum speech length
        extra_words = int((target_speech - speech_secs) * words_per_second)
        try:
            extend_prompt = EXTEND_PROMPT.format(actual_secs=speech_secs, target_secs=target_speech,
                                                   extra_words=extra_words, description=description,
                                                   narration=narration_text)
            response = _track_claude(client.messages.create(model=MODEL, max_tokens=2048,
                                                 messages=[{"role": "user", "content": extend_prompt}]))
            revised = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
            if revised:
                remeasure = _measure_tts_duration(revised, voice_id, scene_secs=_fixed_scene_secs)
                tts_calls_used += 1
                if remeasure["ok"]:
                    narration_text, speech_secs, audio_path = revised, remeasure["duration_secs"], remeasure["audio_path"]
                    measurement, sync = remeasure, remeasure.get("sync")
        except Exception as e:
            log.warning(f"[Scraper] Extend pass failed, proceeding as-is "
                        f"(may result in a shorter-than-usual video — acceptable if the listing "
                        f"genuinely has little content, not silently forced): {e}")
        # NOTE: if still short after one extend attempt (e.g. genuinely
        # sparse listing), we deliberately do NOT loop further or invent
        # content — scene_count will just land at MIN_SCENES with a bit
        # more trailing silence than usual, which is preferable to padding
        # with unsupported claims.

    # 2026-10-15: the lead/trail blank frames are added around the scenes, so the scenes only need to cover the speech
    # (minus the MAX_OVERFLOW_SECS the trailing blank absorbs). It used to add 2 s here, counting the buffers twice.
    needed_secs = max(0.0, speech_secs - MAX_OVERFLOW_SECS)
    scene_count = math.ceil(needed_secs / SCENE_CLIP_SECS)
    scene_count = max(_min_scenes, min(_max_scenes, scene_count))

    # Always prefer the TIGHTEST-fitting scene count, not just whatever
    # ceil() lands on — rounding up can otherwise leave far more than
    # TRAIL_SILENCE_SECS of dead air (e.g. 28.4s speech needing 31.4s
    # total rounds all the way up to 35s, leaving 5.6s trailing instead of
    # ~2-3s). Since scene_count is already a ceiling, the trim needed to
    # drop to one fewer scene is mathematically always LESS than one full
    # SCENE_CLIP_SECS (i.e. under 5s) — a small, safe edit, not a big cut.
    # Only kept at the higher scene count if the lower one would be
    # unreachable (i.e. already at MIN_SCENES).
    if scene_count > _min_scenes and audio_path:
        lower_scene_count = scene_count - 1
        max_speech_for_lower = _speech_band(lower_scene_count)[1]
        if speech_secs > max_speech_for_lower:
            trim_amount = speech_secs - max_speech_for_lower
            audio_path = _fade_out_and_trim(audio_path, max_speech_for_lower)
            speech_secs = max_speech_for_lower
            scene_count = lower_scene_count
            was_trimmed = True
            sync = None
            log.info(f"[Scraper] Trimmed {trim_amount:.1f}s to fit {lower_scene_count} scenes "
                     f"instead of {lower_scene_count + 1} (avoids excess trailing silence)")

    if premium and not was_trimmed:
        for _ in range(3):   # pauses added by the sync can push the speech past the last scene: add a scene (11 -> 13 at most) and re-assemble
            resynced = _resync_measurement(measurement, scene_count)
            if not resynced:
                break
            audio_path, speech_secs, sync = resynced
            wanted = max(_min_scenes, min(_max_scenes, math.ceil(max(0.0, speech_secs - MAX_OVERFLOW_SECS) / SCENE_CLIP_SECS)))
            if wanted <= scene_count:
                break
            scene_count = wanted

    video_duration_secs = scene_count * SCENE_CLIP_SECS

    return {
        "ok": True,
        "narration_text": narration_text,
        "audio_path": audio_path,
        "speech_duration_secs": speech_secs,
        "scene_count": scene_count,
        "video_duration_secs": video_duration_secs,
        "tts_calls_used": tts_calls_used,
        "was_trimmed": was_trimmed,
        "sync": sync,
        "error": None,
        # 2026-10-22 (Patch B): how the text was produced. "per_scene" = one sentence per scene, fact-checked;
        # "single_text" = the previous one-text path (premium, or the per-scene script was rejected / unavailable).
        "narration_mode": "per_scene" if per_scene else "single_text",
        "script_attempts": (script_info or {}).get("attempts"),
        "script_tightened": script_tightened,
        "script_fallback_reason": ((script_info or {}).get("error") if (script_info and not per_scene) else None),
        "timeline": None,
        "timeline_fallback_reason": anchored_fallback,   # 2026-10-23 (Patch J): why the anchor-driven timeline was not used (None = not tried)
    }



def build_final_audio_track(audio_path: str, video_duration_secs: int) -> str:
    """Builds the COMPLETE audio track: lead silence + narration + trailing
    silence, padded to exactly video_duration_secs — ready to overlay
    directly onto the video. Called once scene_count (and therefore real
    video_duration_secs) is known."""
    from pydub import AudioSegment
    narration_audio = AudioSegment.from_file(audio_path)
    lead_silence = AudioSegment.silent(duration=int(LEAD_SILENCE_SECS * 1000))
    track_so_far_ms = len(lead_silence) + len(narration_audio)
    target_ms = int(video_duration_secs * 1000)
    trail_ms = max(int(TRAIL_SILENCE_SECS * 1000), target_ms - track_so_far_ms)
    trail_silence = AudioSegment.silent(duration=trail_ms)
    full_track = lead_silence + narration_audio + trail_silence
    final_path = audio_path.replace(".mp3", "_full_track.mp3")
    full_track.export(final_path, format="mp3")
    return final_path



# ── Build scenes_config for the standard automated video ───────────────────
# Converts a selection into the exact format api_server.py's job pipeline
# expects. Uses a single continuous narration track (applied separately at
# assembly time, same mechanism as the existing narration-first workflow),
# so each scene's own "voiceover" is left empty rather than duplicating audio.
#
# ASSUMPTION FLAGGED: space_type mapping below (exterior/outdoor/living/
# kitchen -> "large", bedrooms/bathrooms -> "small") is a reasonable default,
# not independently re-verified against the full set of valid space_type
# values in this session — check against real video_generation.py behavior
# before trusting on a real generation run.

_CATEGORY_TO_SPACE_TYPE = {
    "exterior": "large", "outdoor": "large", "living": "large", "kitchen": "large",
    "bedrooms": "small", "bathrooms": "small",
}

# 2026-10-26: the table lives in camera_plan.CATEGORY_MOVEMENT (ONE source; the two outside categories are derived from camera_plan.ROOM_MOVEMENT).
# History: July 10 2026 the table used invented movement names that matched no real option of the UI, so the dropdown always showed its
# first option; every value in camera_plan is checked by test_camera_plan.py against the UI list and the Luma prompt tokens.
_CATEGORY_TO_POV_MOVEMENT = camera_plan.CATEGORY_MOVEMENT


def build_standard_video_scenes_config(selection: dict, captions: dict, clip_duration_secs: int = 5, remove_watermark: bool = True) -> list:
    """
    Returns a scenes_config list in PRIORITY_ORDER, ONE SCENE PER SELECTED
    PHOTO (not one scene per category — a category can have more than one
    selected photo when scene_count > 6, e.g. exterior getting 2 photos).
    Each scene: {caption, voiceover, space_type, pov_movement, duration,
    local_image_path, category}.

    BUG FIXED July 9 2026: this previously only ever took photos[0] per
    category, silently dropping any additional photos a category received
    from select_photos_for_scene_count() when scene_count > 6 — confirmed
    via a live test where 7 photos were selected but only 6 scenes were
    built, silently losing the second exterior photo.

    CHANGED July 10 2026: "remove_watermark" is pre-set to True on every
    scene — scraped photos almost certainly carry the source portal's
    watermark, and this reuses the SAME existing per-scene toggle manual
    uploads already have, rather than a separate eager removal pass during
    scraping (see download_selected_photos).

    2026-10-29: remove_watermark is the value every scene gets: True (the default) for a listing scraped from a portal, whose
    photos carry the portal's watermark; the partner API passes False, because the photos a partner sends are the agency's own
    originals and our removal only smears the area it paints over (job cc33f8af, the tree).
    """
    scenes = []
    for category, photo in standard_scene_slots(selection):
        scenes.append({
            "caption": _scene_caption(captions, category),
            "voiceover": "",  # continuous narration track applied separately, not per-scene
            "space_type": _CATEGORY_TO_SPACE_TYPE.get(category, "large"),
            "pov_movement": _CATEGORY_TO_POV_MOVEMENT.get(category, camera_plan.DEFAULT_MOVEMENT),
            "duration": clip_duration_secs,
            "local_image_path": photo.get("local_path"),
            "category": category,
            "remove_watermark": bool(remove_watermark),
        })
    return scenes


def standard_scene_slots(selection: dict) -> list:
    """2026-10-22 (Patch B): the ONE place that says which scene shows which category, in video order:
    (category, photo) per selected photo, walking PRIORITY_ORDER. Both build_standard_video_scenes_config()
    and the per-scene narration (generate_narration_and_derive_scenes) read it, so the sentence written for
    scene N is about the room scene N really shows."""
    slots = []
    for category in PRIORITY_ORDER:
        for photo in selection["selected"].get(category, []):
            slots.append((category, photo))
    return slots


def standard_scene_sequence(selection: dict) -> list:
    """Just the categories of standard_scene_slots(), e.g. ['exterior','living','kitchen','bedrooms','bathrooms','outdoor']."""
    return [category for category, _ in standard_scene_slots(selection)]


# ── Photo selection: priority order + gap detection ─────────────────────────

def _categorize_and_rank_photos(photos: list, categories: list) -> dict:
    """
    Shared setup step used by every photo-selection function: groups
    photos by category (deduplicating by URL as a hard safeguard against
    the same photo ever being selected twice), then ranks each
    category's candidates by real quality via rank_photos_by_quality().

    Extracted 2026-07-24 -- this exact categorize+rank logic was
    duplicated identically between select_photos_for_scene_count() and
    select_photos_for_scene_count_premium(); this is the one shared
    place it lives now.
    """
    by_category = {cat: [] for cat in categories}
    seen_urls = set()
    for p in photos:
        cat = p.get("category")
        url = p.get("url")
        if cat in by_category and url not in seen_urls:
            by_category[cat].append(p)
            seen_urls.add(url)

    # Rank each category's candidates by real quality (no people, key room
    # elements present, natural light, spacious framing) BEFORE selecting —
    # only categories with more than one candidate incur the extra vision
    # call, and rank_photos_by_quality() itself skips the work for len<=1.
    for cat in by_category:
        by_category[cat] = rank_photos_by_quality(cat, by_category[cat])

    # 2026-10-29: the technical-quality filter (blurred / pixelated / watermark over the subject) acts HERE, on the ranked pool, so a
    # bad photo is never selected and the next candidate takes its place
    filter_poor_quality_candidates(by_category)

    return by_category


QUALITY_RANKING_PROMPT = """You are selecting the best photo(s) of a "{category}" for a real estate video. You'll see {n} candidate photos, labeled Photo 1 through Photo {n}.

Rank them from best to worst based on:
- NO people visible in the photo — this is a significant penalty, avoid photos with people
- NO cars or other vehicles visible in the shot — same penalty as people; prefer a clean, uncluttered view of the property itself
- Clearly shows the defining features of a {category} (e.g. a visible bed for a bedroom, sink/counter/appliances for a kitchen, toilet/shower/sink for a bathroom, a clear building facade for exterior)
- The defining feature must be DIRECTLY visible, never only as a reflection: a bedroom photo where the bed shows up just in a mirror does NOT show the bed. If the room is empty (no furniture), judge by the page description given with each photo and by what the room clearly is (windows, fittings, layout).
- Mirrors, mirrored wardrobes and large glass surfaces dominating the frame are a penalty: reflections make the AI video model drift and invent things. A photo with the same room and no big reflective surface is better.
- A clear, fixed point of interest FAR from the camera in the middle of the frame (a window with a view, the far end of the room, a balcony opening) is a plus: it gives the video camera a safe, natural place to move toward. A photo whose centre is a near object, a blank wall close up, or a door is weaker.
- Natural light present, well-lit rather than dark or harshly artificial
- Technical quality of the picture itself: sharp and clean is better. Clearly visible blur, pixelation, blocky JPEG compression, heavy noise, or a large semi-transparent watermark, text or logo across the main subject (a portal's stamp over the room or the building) are a significant penalty: the video model builds the whole clip from this one picture and cannot repair them. An ordinary phone photo with normal sharpness is fine, only clearly visible problems count.
- The room/space is shown fully and spaciously in frame, not a cramped or heavily cropped angle — a fuller, more complete view is better. This also matters practically: a fuller frame gives the AI video-generation model more real visual information to work with, which reduces the risk of it inventing or distorting details in an ambiguous or heavily-cropped area.

Return ONLY a JSON array of integers, the photo numbers ordered best to worst, e.g. [3, 1, 2]. No other text.
"""


def _tag_rank(photos: list, status: str) -> list:
    """Records on each photo dict how it was ordered (shown later in selection_report)."""
    for i, p in enumerate(photos):
        p["rank_status"] = status
        p["rank_position"] = i + 1
    return photos


def rank_photos_by_quality(category: str, candidates: list, max_to_compare: int = 6) -> list:
    """
    Ranks candidate photos for a category by real visual quality, per the
    agreed criteria above — replaces the previous behavior of just taking
    whichever photo was listed first with no quality judgment at all.

    Caps the comparison pool at max_to_compare (default 6) to bound cost
    and time — for categories with many candidates (e.g. 24 outdoor
    photos on a large villa), only the first max_to_compare are actually
    compared. This is a deliberate cost/quality tradeoff, not exhaustive
    optimization across every candidate.

    Returns the candidates list REORDERED best-first. Falls back to the
    original, unranked order if the vision call fails for any reason —
    this is a quality improvement, not something that should block
    selection if it errors.
    """
    if len(candidates) <= 1:
        return _tag_rank(candidates, "single_candidate")

    pool = candidates[:max_to_compare]
    remainder = candidates[max_to_compare:]

    try:
        import base64
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        content = [{"type": "text", "text": QUALITY_RANKING_PROMPT.format(category=category, n=len(pool))}]
        for i, photo in enumerate(pool):
            fetched = fetch_photo_bytes(photo["url"], photo.get("original_url"), timeout=15)
            if not fetched["ok"]:
                raise RuntimeError(fetched["error"])
            b64 = base64.b64encode(fetched["content"]).decode("utf-8")
            lab = str(photo.get("label_it") or "").strip()[:80]
            content.append({"type": "text", "text": f"Photo {i + 1}:" + (f" (page description: {lab})" if lab else "")})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})

        response = _track_claude(client.messages.create(model=MODEL, max_tokens=200,
                                             messages=[{"role": "user", "content": content}]))
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        order_match = re.search(r"\[[\d,\s]+\]", raw)
        if not order_match:
            return _tag_rank(candidates, "fallback_original_order: unparseable model reply")
        order = json.loads(order_match.group(0))
        ranked = [pool[i - 1] for i in order if 1 <= i <= len(pool)]
        ranked_ids = {id(p) for p in ranked}
        for p in pool:
            if id(p) not in ranked_ids:
                ranked.append(p)  # safety: include anything the model's ranking missed
        result = ranked + remainder
        for i, p in enumerate(result):
            p["rank_status"] = "ranked" if i < len(ranked) else "not_compared"
            p["rank_position"] = i + 1
        return result
    except Exception as e:
        log.warning(f"[Scraper] Quality ranking failed for {category}, using original order: {e}")
        return _tag_rank(candidates, "fallback_original_order: " + str(e)[:160])


def select_photos_for_scene_count(photos: list, scene_count: int) -> dict:
    """
    Selects exactly scene_count photos across PRIORITY_ORDER categories —
    this is what answers the "how many photos per category" question that
    was previously just a fixed placeholder: the answer is now derived
    from how much the property's real narration actually needs to say.

    FLEXIBLE CATEGORY HANDLING: if a category has zero candidates, its slot
    is backfilled from OTHER categories that have surplus photos rather
    than left as a gap. A real, reported gap only happens if there simply
    aren't enough USABLE photos across ALL categories combined.

    BUG FIXED July 10 2026 — when scene_count < 6, this previously took
    PRIORITY_ORDER[:scene_count] (the first N categories BY LIST POSITION),
    which meant "outdoor" (last in the list) was silently excluded EVERY
    time scene_count came in under 6 — regardless of how many good photos
    it had. Confirmed via real testing: outdoor had 20+ strong candidates
    and still got dropped entirely. Now drops whichever category has the
    FEWEST available photos first, using list position only as a tiebreak
    — availability decides what gets cut, not raw position in the list.

    Also deduplicates candidates by URL before selection, as a hard
    safeguard against the same photo ever being selected twice (confirmed
    via testing that this happened at least once — deduplicating at the
    source removes any possibility of it, regardless of exact cause).

    Returns the same {"selected": {...}, "gaps": [...]} shape as before,
    plus "scene_count_requested" for confirmation.
    """
    by_category = _categorize_and_rank_photos(photos, PRIORITY_ORDER)

    if scene_count >= len(PRIORITY_ORDER):
        base_categories = list(PRIORITY_ORDER)
    else:
        # Drop (len(PRIORITY_ORDER) - scene_count) categories — whichever
        # have the FEWEST available photos, using later list position only
        # as a tiebreak when counts are equal. This is what stops a
        # photo-rich category (e.g. outdoor) from being dropped just
        # because of where it sits in the priority list.
        num_to_drop = len(PRIORITY_ORDER) - scene_count
        drop_order = sorted(PRIORITY_ORDER, key=lambda cat: (len(by_category[cat]), -PRIORITY_ORDER.index(cat)))
        dropped = set(drop_order[:num_to_drop])
        base_categories = [cat for cat in PRIORITY_ORDER if cat not in dropped]

    selected = {cat: [] for cat in PRIORITY_ORDER}
    remaining = scene_count

    # Pass 1: one photo per base category, wherever available
    for cat in base_categories:
        if by_category[cat]:
            selected[cat].append(by_category[cat][0])
            remaining -= 1

    # Pass 2: backfill remaining slots (missing categories' slots, AND any
    # extra slots when scene_count > 6) from whichever categories have
    # surplus, in priority order — this is the actual "double up" behavior.
    while remaining > 0:
        progress = False
        for cat in PRIORITY_ORDER:
            if remaining <= 0:
                break
            already = len(selected[cat])
            available = by_category[cat]
            if len(available) > already:
                selected[cat].append(available[already])
                remaining -= 1
                progress = True
        if not progress:
            break  # truly no more photos available anywhere

    total_selected = sum(len(v) for v in selected.values())
    gaps = []
    if total_selected < scene_count:
        gaps.append(f"Only {total_selected} usable photo(s) found across all categories combined, "
                    f"needed {scene_count} — this listing may need manual photo upload." + _quality_gap_note(photos))

    return {
        "selected": {cat: photos_list for cat, photos_list in selected.items() if photos_list},
        "gaps": gaps,
        "total_selected": total_selected,
        "scene_count_requested": scene_count,
    }


def select_photos_for_scene_count_premium(photos: list, scene_count: int) -> dict:
    """
    2026-07-24 (backlog item 35): premium ~1-minute template selection.

    Explicit product decisions this implements:
    - Sequence includes a taxonomy of "main" + expanded instances per room
      type (e.g. multiple bedrooms/bathrooms/outdoor spaces), not just one
      photo per category -- built by reusing rank_photos_by_quality()'s
      existing best-first ordering: the first selected photo in a
      category is implicitly "main", any additional ones are "small"/
      "small_2" etc (no new quality mechanism needed -- that ranking
      already combines visual quality with content representativeness,
      e.g. "clearly shows a visible bed for a bedroom").
    - Outdoor appears both early (right after the facade) and again at
      the closing, via the two pseudo-category keys defined in
      PREMIUM_PRIORITY_ORDER.
    - Three-tier fallback when a category is sparse, in this exact
      order: (1) expand instances in OTHER large-room/outdoor categories
      that do have surplus, (2) add categories not in the base template
      (laundry/office/garage) if the listing has them, (3) last resort --
      reuse additional photos of the SAME room/space, same as the
      standard format's existing backfill.
    """
    real_categories = ["exterior", "outdoor", "living", "kitchen", "bedrooms", "bathrooms"] + _PREMIUM_EXTRA_CATEGORIES
    by_category = _categorize_and_rank_photos(photos, real_categories)

    # Split outdoor's ranked list into two pseudo-categories up front --
    # the best-ranked photo goes early (right after the facade), the
    # second-best (if it exists) is reserved for the closing.
    outdoor_ranked = by_category.pop("outdoor")
    by_category["outdoor_early"] = outdoor_ranked[:1]
    by_category["outdoor_late"] = outdoor_ranked[1:2]
    _outdoor_overflow = outdoor_ranked[2:]  # any additional outdoor photos beyond the two reserved slots

    selected = {cat: [] for cat in PREMIUM_PRIORITY_ORDER}
    remaining = scene_count

    # Pass 1: one slot each for the six core categories (outdoor's two
    # slots both count as "core" here, not fallback expansion).
    for cat in ["exterior", "outdoor_early", "living", "kitchen", "bedrooms", "bathrooms", "outdoor_late"]:
        if by_category.get(cat) and remaining > 0:
            selected[cat].append(by_category[cat][0])
            remaining -= 1

    # Pass 2 (Tier 1 -- expand instances, prioritizing large rooms/outdoor).
    # Includes the outdoor overflow pool so a photo-rich outdoor category
    # can still contribute a 3rd/4th shot here, not just its two reserved
    # early/late slots.
    _expand_pool = dict(by_category)
    _expand_pool["outdoor_early"] = by_category["outdoor_early"] + _outdoor_overflow
    while remaining > 0:
        progress = False
        for cat in _PREMIUM_EXPAND_PRIORITY:
            if remaining <= 0:
                break
            already = len(selected[cat])
            available = _expand_pool.get(cat, [])
            if len(available) > already:
                selected[cat].append(available[already])
                remaining -= 1
                progress = True
        if not progress:
            break

    # Pass 3 (Tier 2 -- add categories not in the base template, only if
    # the listing actually has photos there).
    for cat in _PREMIUM_EXTRA_CATEGORIES:
        if remaining <= 0:
            break
        if by_category.get(cat):
            selected[cat].append(by_category[cat][0])
            remaining -= 1

    # Pass 4 (Tier 3 -- last resort: reuse any remaining surplus photo,
    # anywhere, same room shown from a different angle).
    while remaining > 0:
        progress = False
        for cat in PREMIUM_PRIORITY_ORDER:
            if remaining <= 0:
                break
            already = len(selected[cat])
            available = _expand_pool.get(cat, by_category.get(cat, []))
            if len(available) > already:
                selected[cat].append(available[already])
                remaining -= 1
                progress = True
        if not progress:
            break  # truly no more photos available anywhere

    total_selected = sum(len(v) for v in selected.values())
    gaps = []
    if total_selected < scene_count:
        gaps.append(f"Only {total_selected} usable premium photo(s) found across all categories combined, "
                    f"needed {scene_count} -- this listing may not have enough photos for the premium template." + _quality_gap_note(photos))

    return {
        "selected": {cat: v for cat, v in selected.items() if v},
        "gaps": gaps,
        "total_selected": total_selected,
        "scene_count_requested": scene_count,
    }


def build_premium_video_scenes_config(selection: dict, captions: dict, clip_duration_secs: int = 5, remove_watermark: bool = True) -> list:
    """
    Premium counterpart to build_standard_video_scenes_config() -- same
    "one scene per selected photo" pattern, but iterates
    PREMIUM_PRIORITY_ORDER (which includes the outdoor_early/outdoor_late
    split) instead of PRIORITY_ORDER, mapping both back to the real
    "outdoor" category for caption/space_type/pov_movement lookups, since
    captions and the category-lookup tables are keyed by real category
    names, not the pseudo-split ones.
    """
    scenes = []
    for pseudo_category in PREMIUM_PRIORITY_ORDER:
        real_category = "outdoor" if pseudo_category in ("outdoor_early", "outdoor_late") else pseudo_category
        photos = selection["selected"].get(pseudo_category, [])
        for photo in photos:
            scenes.append({
                "caption": _scene_caption(captions, real_category),
                "voiceover": "",  # continuous narration track applied separately, not per-scene
                "space_type": _CATEGORY_TO_SPACE_TYPE.get(real_category, "large"),
                "pov_movement": _CATEGORY_TO_POV_MOVEMENT.get(real_category, camera_plan.DEFAULT_MOVEMENT),
                "duration": clip_duration_secs,
                "local_image_path": photo.get("local_path"),
                "category": real_category,
                "remove_watermark": bool(remove_watermark),
            })
    return scenes


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 listing_scraper.py <listing_url>")
        sys.exit(1)

    result = extract_listing(sys.argv[1])
    if not result["ok"]:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)

    print(f"--- Extraction: {len(result['photos'])} photos found ---")
    by_cat = {}
    upgraded_count = 0
    for p in result["photos"]:
        by_cat.setdefault(p["category"], 0)
        by_cat[p["category"]] += 1
        if p.get("resolution_upgraded"):
            upgraded_count += 1
    for cat, count in by_cat.items():
        print(f"  {cat}: {count}")
    print(f"  Resolution upgrade: {upgraded_count}/{len(result['photos'])} photos got a higher-res URL")

    print("\n--- Resolving uncategorized photos via vision QC fallback ---")
    result["photos"] = resolve_uncategorized_photos(result["photos"])
    by_cat = {}
    for p in result["photos"]:
        by_cat.setdefault(p["category"], 0)
        by_cat[p["category"]] += 1
    for cat, count in by_cat.items():
        print(f"  {cat}: {count}")

    print(f"\nDescription: {result['description'][:100]}...")
    print(f"Price: {result['price']}")
    print(f"Address: {result['address']}")

    # NEW ORDER: narration is generated and measured FIRST — scene count
    # (and therefore how many photos to select) is DERIVED from the real
    # measured narration length, not decided upfront.
    print("\n--- Generating natural narration and measuring real TTS duration ---")
    narration = generate_narration_and_derive_scenes(result["description"], result["address"], result["price"])
    if not narration["ok"]:
        print(f"NARRATION GENERATION FAILED: {narration['error']}")
        sys.exit(1)

    print(f"\nNarration ({narration['tts_calls_used']} TTS call(s) used, "
          f"speech duration: {narration['speech_duration_secs']:.1f}s"
          f"{', TRIMMED via fade-out safety net' if narration['was_trimmed'] else ''}):\n")
    print(narration["narration_text"])
    print(f"\n--> Derived scene count: {narration['scene_count']} scenes x {SCENE_CLIP_SECS}s "
          f"= {narration['video_duration_secs']}s video")

    print(f"\n--- Selecting {narration['scene_count']} photos across categories (priority order) ---")
    selection = select_photos_for_scene_count(result["photos"], narration["scene_count"])
    for cat, photos in selection["selected"].items():
        print(f"  {cat}: {len(photos)} selected")
    if selection["gaps"]:
        print("\n  GAPS DETECTED — manual upload needed for:")
        for gap in selection["gaps"]:
            print(f"    {gap}")
    else:
        print("\n  No gaps — all categories satisfied.")

    print("\n--- Downloading selected photos + removing watermarks (default ON for scraped photos) ---")
    test_scratch_dir = BASE_DIR / "jobs" / "_test_scratch" / "scraper_test"
    selection = download_selected_photos(selection, test_scratch_dir)
    for cat, photos in selection["selected"].items():
        for p in photos:
            print(f"  {cat}: {p.get('local_path')} (watermark removal deferred to generation-time toggle)")
    if selection["download_failures"]:
        print("\n  DOWNLOAD FAILURES:")
        for f in selection["download_failures"]:
            print(f"    {f['category']}: {f['error']}")

    print("\n--- Generating on-screen captions for selected categories ---")
    selected_categories = [cat for cat, photos in selection["selected"].items() if photos]
    if selected_categories:
        captions = generate_captions_for_categories(result["description"], selected_categories)
    else:
        captions = {}
        print("\n--- Skipping caption generation - no photos selected ---")
    for cat, caption in captions.items():
        print(f"  {cat}: {caption}")

    print("\n--- Building final audio track (lead silence + narration + trailing silence) ---")
    final_audio_path = build_final_audio_track(narration["audio_path"], narration["video_duration_secs"])
    print(f"Full audio track, exactly {narration['video_duration_secs']}s total: {final_audio_path}")
    print("Listen to this one — it's the exact track that would overlay onto the video.")

    scenes_config = build_standard_video_scenes_config(selection, captions, clip_duration_secs=SCENE_CLIP_SECS)
    print(f"\n--- scenes_config ready for job creation ({len(scenes_config)} scenes) ---")
    for s in scenes_config:
        print(f"  {s['category']}: {s['duration']}s, space_type={s['space_type']}, image={s['local_image_path']}")

    # ── Copy artifacts to STABLE, predictable filenames for browser viewing ──
    # Every run overwrites the same fixed names in jobs/_test_scratch/ (the
    # project's existing test-isolation directory), rather than leaving
    # random-named /tmp files that need fragile glob-matching in a separate
    # shell command to find. Always accessible at:
    #   http://<server>:8000/test-scratch/test_narration.mp3
    #   http://<server>:8000/test-scratch/test_<category>_<NN>.jpg
    import shutil as _shutil
    scratch_root = BASE_DIR / "jobs" / "_test_scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)

    if final_audio_path and os.path.exists(final_audio_path):
        dest_audio = scratch_root / "test_narration.mp3"
        _shutil.copy2(final_audio_path, dest_audio)
        print(f"\nCopied narration to stable path: {dest_audio}")

    for s in scenes_config:
        src = s.get("local_image_path")
        if src and os.path.exists(src):
            dest = scratch_root / f"test_{Path(src).name}"
            _shutil.copy2(src, dest)

    print(f"\n--- Browser-viewable URLs (server must be running) ---")
    print(f"  Narration: http://<your-server-ip>:8000/test-scratch/test_narration.mp3")
    for s in scenes_config:
        src = s.get("local_image_path")
        if src:
            print(f"  {s['category']}: http://<your-server-ip>:8000/test-scratch/test_{Path(src).name}")

