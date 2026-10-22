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

def get_claude_cost():
    """Real Claude API cost for the current job, in EUR."""
    i = _claude_usage["input_tokens"]; o = _claude_usage["output_tokens"]
    usd = (i / 1_000_000) * CLAUDE_INPUT_PER_MTOK + (o / 1_000_000) * CLAUDE_OUTPUT_PER_MTOK
    return {
        "input_tokens": i, "output_tokens": o, "calls": _claude_usage["calls"],
        "cost_eur": round(usd * USD_TO_EUR, 4),
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
- Map each photo's label to exactly one category: exterior (building facade, outdoor view of the property itself), living (living room, dining room, study, hallway, stairs), kitchen, bedrooms, bathrooms, outdoor (garden, terrace, courtyard, parking area, land/terrain), laundry (laundry/utility room -- 2026-07-24: previously lumped into bathrooms, now its own category so it can appear as an extra scene when a longer video needs it), office (study/home office, distinct from a general living-area study), garage (garage, carport, covered parking specifically -- distinct from general outdoor parking). If a label doesn't clearly fit any of these, use "uncategorized".
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
            max_tokens=4096,
            tools=[{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1}],
            extra_headers={"anthropic-beta": "web-fetch-2025-09-10"},
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(url=url)}],
        ))

        text_parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        raw = "".join(text_parts).strip()

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
    "- outdoor: a PRIVATE outdoor space belonging to this home: balcony, terrace, private garden, or the view from that balcony/terrace. A shared or condominium space (courtyard, portico, shared balcony or walkway) is NOT outdoor: answer other.\n"
    "- other: entrance hall, corridor, hallway, stairs, shared building areas (courtyard, portico, lobby, lift, communal garden), "
    "floor plan, close-up of a detail, view from a window, a tree or vegetation, or anything that is not one of the categories above.\n\n"
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


def _classify_photo_vision(image_url: str, fallback_url: str = None) -> tuple:
    """Single implementation of "which room is this photo" (Claude vision). Returns (category, ok):
    category is one of CATEGORIES or "uncategorized" (the model answered "other"/anything else);
    ok is False only when the call itself failed (download or API), so callers can keep a previous label."""
    try:
        fetched = fetch_photo_bytes(image_url, fallback_url, timeout=15)
        if not fetched["ok"]:
            raise RuntimeError(fetched["error"])
        b64 = _image_b64_for_vision(fetched["content"])
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        content = [
            {"type": "text", "text": _VISION_CLASSIFY_PROMPT},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        ]
        response = _track_claude(client.messages.create(
            model=MODEL, max_tokens=20, messages=[{"role": "user", "content": content}],
        ))
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip().lower()
        raw = re.sub(r"[^a-z]", "", raw)
        return (raw if raw in CATEGORIES else "uncategorized"), True
    except Exception as e:
        log.warning(f"[Scraper] Vision classification failed for {image_url}: {e}")
        return "uncategorized", False


def classify_uncategorized_photo(image_url: str, fallback_url: str = None) -> str:
    """Room type of one photo via Claude vision (see _classify_photo_vision). Never raises; "uncategorized" if unsure.
    Limited to the 6 PRIORITY_ORDER categories on purpose (a value outside it would vanish in selection)."""
    return _classify_photo_vision(image_url, fallback_url)[0]


MAX_PHOTOS_TO_REFINE = 12
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
    summary = {"method": "exterior_outdoor_check", "checked": len(todo), "confirmed": confirmed,
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
    dest_path.write_bytes(fetched["content"])
    return {"ok": True, "path": str(dest_path), "error": None,
            "url_used": fetched["url_used"], "used_fallback": fetched["used_fallback"]}


def download_selected_photos(selection: dict, output_dir: Path) -> dict:
    """
    Downloads every photo in a select_photos() result — only the selected
    subset, not the full scraped list. Watermark removal is NOT done here
    (see module note above) — it's handled at generation time via the
    existing per-scene toggle.

    Returns the same {"selected": {...}, "gaps": [...]} structure, with each
    selected photo dict augmented with "local_path". Photos that fail to
    download entirely are dropped and reported in a new "download_failures"
    list rather than silently disappearing.
    """
    download_failures = []
    for category, photos in selection["selected"].items():
        kept = []
        for i, p in enumerate(photos):
            stem = f"{category}_{i:02d}"
            result = download_photo(p["url"], output_dir, stem, p.get("original_url"))
            if result["ok"]:
                p["local_path"] = result["path"]
                p["url_used"] = result["url_used"]
                p["used_fallback"] = result["used_fallback"]
                kept.append(p)
            else:
                download_failures.append({"category": category, "url": p["url"], "error": result["error"]})
        selection["selected"][category] = kept

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


def _measure_tts_duration(text: str, voice_id: str = None, attempts: int = TTS_MEASURE_ATTEMPTS, scene_secs: list = None) -> dict:
    """2026-10-12: retries the real TTS measurement on transient failure (backoff 2 s, 4 s).
    A single provider hiccup used to fail the whole job ("TTS measurement failed on initial narration").
    2026-10-15: scene_secs (fixed scene lengths) makes the audio come out already synchronised with the scenes."""
    last = {"ok": False, "duration_secs": None, "audio_path": None}
    for n in range(attempts):
        last = _measure_tts_duration_once(text, voice_id, scene_secs)
        if last.get("ok"):
            return last
        log.warning(f"[Scraper] TTS measurement attempt {n + 1}/{attempts} failed")
        if n < attempts - 1:
            time.sleep(2 * (n + 1))
    return last


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
                return {"ok": True, "sentences": sentences, "attempts": attempt, "problems": [], "error": None}
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
        revised = ss.parse(_claude_text_reply(client, ss.build_tighten_prompt(sentences, bad, description)))
    except Exception as e:
        log.warning(f"[Scraper] Tighten pass failed, keeping the first script: {e}")
        return None
    if not revised or len(revised) != len(sentences):
        return None
    changed = {i for i, _ in bad}
    if any(revised[i] != sentences[i] for i in range(len(sentences)) if i not in changed):
        return None
    if ss.validate(revised, description, agency_name, price, split_fn=split_into_sentences):
        return None
    return revised


def generate_narration_and_derive_scenes(
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

    # 2026-10-15: the standard video has a FIXED scene count, so the audio is built already synchronised with it.
    # Premium derives its scene count from the speech, so it is measured plain first and synchronised afterwards.
    _fixed_scene_secs = None if premium else [SCENE_CLIP_SECS] * STANDARD_SCENES
    measurement = _measure_tts_duration(narration_text, voice_id, scene_secs=_fixed_scene_secs)
    tts_calls_used = 1
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
        if bad and tts_calls_used < 2:
            revised_sents = _tighten_scene_script(scene_script_sentences, bad, description, address, price, agency_name)
            if revised_sents:
                remeasure = _measure_tts_duration(" ".join(revised_sents), voice_id, scene_secs=_fixed_scene_secs)
                tts_calls_used += 1
                if remeasure["ok"] and len(_ss.spill_problems(remeasure.get("sync"), STANDARD_SCENES)) <= len(bad):
                    scene_script_sentences = revised_sents
                    narration_text = " ".join(revised_sents)
                    speech_secs, audio_path = remeasure["duration_secs"], remeasure["audio_path"]
                    measurement, sync = remeasure, remeasure.get("sync")
                    script_tightened = True

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

# BUG FIXED July 10 2026 — the previous version of this table used
# entirely INVENTED movement names ("wide_reveal", "pullback_arc",
# "gentle_arc", "soft_orbit") that don't match ANY real option in
# ui.html's MOVEMENT_OPTS. Since none of those values ever matched a real
# <option>, the dropdown always fell back to showing its first/starred
# option ("Entra ed esplora") regardless of category — confirmed via real
# testing this was the actual cause of "camera movement never changes."
# Verified against the real MOVEMENT_OPTS list this time before choosing
# defaults — these ARE real, selectable values:
#   walk_in_explore, walk_in_gentle, walk_in_turn_left, walk_in_turn_right,
#   walk_through, stand_look_around, subtle_rotate, approach_reveal,
#   walk_toward, reveal_pullback, step_out_onto
_CATEGORY_TO_POV_MOVEMENT = {
    "exterior": "reveal_pullback",   # explicitly labeled for facade/exterior in the UI itself
    "outdoor": "walk_toward",        # explicitly labeled "per esterni" (for exteriors)
    "living": "walk_in_explore",     # the app's own starred/recommended default
    "kitchen": "walk_in_gentle",     # gentle lateral tracking, compact functional space
    "bedrooms": "stand_look_around", # calm, minimal — avoid dramatic movement in a private room
    "bathrooms": "subtle_rotate",    # explicitly labeled "per piccoli ambienti" (for small rooms)
}


def build_standard_video_scenes_config(selection: dict, captions: dict, clip_duration_secs: int = 5) -> list:
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
    """
    scenes = []
    for category, photo in standard_scene_slots(selection):
        scenes.append({
            "caption": _scene_caption(captions, category),
            "voiceover": "",  # continuous narration track applied separately, not per-scene
            "space_type": _CATEGORY_TO_SPACE_TYPE.get(category, "large"),
            "pov_movement": _CATEGORY_TO_POV_MOVEMENT.get(category, "gentle_arc"),
            "duration": clip_duration_secs,
            "local_image_path": photo.get("local_path"),
            "category": category,
            "remove_watermark": True,
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

    return by_category


QUALITY_RANKING_PROMPT = """You are selecting the best photo(s) of a "{category}" for a real estate video. You'll see {n} candidate photos, labeled Photo 1 through Photo {n}.

Rank them from best to worst based on:
- NO people visible in the photo — this is a significant penalty, avoid photos with people
- NO cars or other vehicles visible in the shot — same penalty as people; prefer a clean, uncluttered view of the property itself
- Clearly shows the defining features of a {category} (e.g. a visible bed for a bedroom, sink/counter/appliances for a kitchen, toilet/shower/sink for a bathroom, a clear building facade for exterior)
- Natural light present, well-lit rather than dark or harshly artificial
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
            content.append({"type": "text", "text": f"Photo {i + 1}:"})
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
                    f"needed {scene_count} — this listing may need manual photo upload.")

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
                    f"needed {scene_count} -- this listing may not have enough photos for the premium template.")

    return {
        "selected": {cat: v for cat, v in selected.items() if v},
        "gaps": gaps,
        "total_selected": total_selected,
        "scene_count_requested": scene_count,
    }


def build_premium_video_scenes_config(selection: dict, captions: dict, clip_duration_secs: int = 5) -> list:
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
                "pov_movement": _CATEGORY_TO_POV_MOVEMENT.get(real_category, "gentle_arc"),
                "duration": clip_duration_secs,
                "local_image_path": photo.get("local_path"),
                "category": real_category,
                "remove_watermark": True,
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

