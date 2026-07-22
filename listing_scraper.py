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
import logging
from pathlib import Path
from urllib.parse import urlparse

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

def _track_claude(response):
    try:
        u = response.usage
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

SUPPORTED_DOMAINS = {"immobiliare.it", "www.immobiliare.it", "idealista.it", "www.idealista.it",
                     "casa.it", "www.casa.it"}

BASE_DIR = Path(__file__).parent
REQUESTED_SITES_FILE = BASE_DIR / "scraper_site_requests.json"

EXTRACTION_PROMPT = """Fetch this real estate listing page: {url}

Extract and return ONLY a JSON object (no other text, no markdown code fences) with this exact structure:

{{
  "photos": [
    {{"url": "...", "label_it": "...", "category": "one of: exterior, living, kitchen, bedrooms, bathrooms, outdoor, uncategorized"}}
  ],
  "description": "...",
  "price": "...",
  "address": "..."
}}

Rules:
- Only include real property photos in "photos" — EXCLUDE floor plan diagrams and any agent/agency headshot or logo images.
- "label_it" is the photo's own caption/label as shown on the page, in whatever language the site uses.
- Map each photo's label to exactly one category: exterior (building facade, outdoor view of the property itself), living (living room, dining room, study, hallway, stairs), kitchen, bedrooms, bathrooms (including laundry/utility rooms), outdoor (garden, terrace, courtyard, parking area, land/terrain). If a label doesn't clearly fit any of these, use "uncategorized".
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
]


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
            if p.get("category") not in CATEGORIES:
                p["category"] = "uncategorized"
            if attempt_resolution_upgrade and p.get("url"):
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

def classify_uncategorized_photo(image_url: str) -> str:
    """
    For any photo Claude couldn't confidently label, falls back to the
    existing Florence-2 vision analysis already used elsewhere in the
    pipeline (vision_analysis.py's analyse_input()), per the agreed design:
    site labels first, AI classification as fallback.

    ASSUMPTION FLAGGED: this assumes analyse_input()'s return dict contains
    a "space_type" (or similarly named) field whose value can be mapped to
    one of our 6 categories. This has NOT been independently re-verified in
    this session — check real output the first time this actually runs,
    since analyse_input() was originally built for camera-movement decisions
    (e.g. "large"/"small" space types), which may not map 1:1 onto
    exterior/living/kitchen/bedrooms/bathrooms/outdoor without adjustment.
    """
    try:
        import tempfile
        from vision_analysis import analyse_input

        resp = requests.get(image_url, timeout=15)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name

        try:
            result = analyse_input(tmp_path)
            # best-effort mapping — VERIFY against real analyse_input() output
            space_type = str(result.get("space_type", "")).lower()
            mapping_hints = {
                "kitchen": "kitchen", "bathroom": "bathrooms", "bedroom": "bedrooms",
                "living": "living", "exterior": "exterior", "outdoor": "outdoor",
                "garden": "outdoor", "facade": "exterior",
            }
            for hint, category in mapping_hints.items():
                if hint in space_type:
                    return category
            return "uncategorized"
        finally:
            os.remove(tmp_path)
    except Exception as e:
        log.warning(f"[Scraper] Vision QC fallback failed for {image_url}: {e}")
        return "uncategorized"


def resolve_uncategorized_photos(photos: list) -> list:
    """Runs the vision-QC fallback on every 'uncategorized' photo, in place."""
    for p in photos:
        if p.get("category") == "uncategorized":
            p["category"] = classify_uncategorized_photo(p["url"])
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

def download_photo(photo_url: str, output_dir: Path, filename_stem: str) -> dict:
    """
    Downloads one scraped photo. Returns:
      {"ok": bool, "path": str | None, "error": str | None}
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dest_path = output_dir / f"{filename_stem}.jpg"
    try:
        resp = requests.get(photo_url, timeout=20)
        resp.raise_for_status()
        dest_path.write_bytes(resp.content)
        return {"ok": True, "path": str(dest_path), "error": None}
    except Exception as e:
        return {"ok": False, "path": None, "error": f"download failed: {e}"}


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
            result = download_photo(p["url"], output_dir, stem)
            if result["ok"]:
                p["local_path"] = result["path"]
                kept.append(p)
            else:
                download_failures.append({"category": category, "url": p["url"], "error": result["error"]})
        selection["selected"][category] = kept

    selection["download_failures"] = download_failures
    return selection


# ── Narration/caption auto-generation from scraped description ─────────────
# Per the agreed decision: auto-generate narration/captions from the scraped
# listing text rather than leaving it fully manual. Plain text generation —
# no web_fetch tool/beta header needed here, since the description text is
# already in hand from extract_listing().

NARRATION_PROMPT = """You are writing a short, natural-sounding Italian voiceover script for a real estate property video, based on this listing description:

---
{description}
---

Property details: {address}, {price}

Write a single continuous narration script (in Italian) covering this property naturally and completely. Do NOT target a specific word count or duration; write however much is naturally needed to cover the property's real features well, neither padded nor rushed. Should flow as ONE continuous piece, no headers, no scene labels.

STAY OBJECTIVE AND FACTUAL — this is important, not a minor style note:
- Do NOT add subjective or promotional adjectives that aren't grounded in the description (e.g. don't call a location "prestigious," "esclusivo," "meraviglioso," or similar, unless the description itself uses language like that). A small town is not automatically "prestigious" just because it's in a real estate video.
- Describe features plainly and factually (size, room count, what's present) rather than editorializing about how impressive they are.
- If the description itself is promotional in tone, you may reflect that tone — but do not ADD MORE embellishment than what's actually there. When in doubt, favor the more neutral, factual phrasing.
- A calm, clear, informative tone is the goal — not a marketing voiceover.

DO NOT include phone numbers or the price in the spoken narration — phone numbers are not pronounced intelligibly by text-to-speech and neither is needed in the voiceover itself.

AVOID legal/administrative real estate jargon that means nothing to a general viewer or sounds jarring when spoken aloud — for example, do not say "nuda proprietà" (a specific bare-ownership legal structure) or generic filler like "appartamento di proprietà" (just say "appartamento") unless that jargon is actually essential to understanding the listing. Use natural, plain descriptive language a real person would use when showing someone a property.

IMPORTANT: clearly state whether the property is FOR SALE or FOR RENT ("in vendita" or "in affitto") near the beginning of the narration, based on what the listing description actually says — do not leave this ambiguous or assume one over the other.

End the narration with a brief, natural closing line inviting the viewer to contact the agency for more information (e.g. "Contattate l'agenzia per maggiori informazioni" or similar) — do NOT include a phone number or email in this closing line, just a general invitation to get in touch.

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

Keep the most important property details (location, size, standout features) and drop secondary ones first. Keep it flowing naturally. Stay factual and objective — don't add subjective or promotional adjectives that weren't already justified by the source material.

Current narration to shorten:
---
{narration}
---

Return ONLY the shortened narration text (no JSON, no markdown, no preamble)."""


def _measure_tts_duration(text: str, voice_id: str = None) -> dict:
    """Generates real TTS audio and measures its actual duration — the
    only reliable way to know how long narration text will actually take
    to speak. Never estimated from word/character count for any decision
    that matters — every scene-count and fit decision below is made from
    this real measurement, not a guess."""
    import tempfile
    from voice_generation import generate_speech
    from pydub import AudioSegment

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    try:
        ok = generate_speech(text, tmp_path, voice_id=voice_id)
        if not ok or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {"ok": False, "duration_secs": None, "audio_path": None}
        duration_secs = len(AudioSegment.from_file(tmp_path)) / 1000.0
        return {"ok": True, "duration_secs": duration_secs, "audio_path": tmp_path}
    except Exception as e:
        log.error(f"[Scraper] TTS measurement failed: {e}")
        return {"ok": False, "duration_secs": None, "audio_path": None, "error": str(e)}


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


def generate_captions_for_categories(description: str, categories: list) -> dict:
    """Generates short on-screen captions for exactly the given categories —
    called AFTER scene count/category selection is known (see
    generate_narration_and_derive_scenes), not before, since which
    categories end up selected depends on the real narration length."""
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
from narration import LEAD_SECS, TRAIL_SECS
LEAD_SILENCE_SECS  = LEAD_SECS    # was an independent 1.0 -- now the same 1.0 as narration.py
TRAIL_SILENCE_SECS = TRAIL_SECS   # was an independent 2.0 -- now the same 1.0 (the WhatsApp-trim evidence behind narration.py's value applies equally to scraped videos)
MIN_SCENES = 5             # 25s — tightened from an earlier 4-8 range per explicit requirement to
MAX_SCENES = 7             # 35s — stay "roughly 30s", not drift as wide as 20-40s
TARGET_SCENES = 6          # 30s — the anchor; derived scene count should land here in the common case
MIN_SPEECH_SECS_FOR_RANGE = (MIN_SCENES * SCENE_CLIP_SECS) - LEAD_SILENCE_SECS - TRAIL_SILENCE_SECS  # 22s
MAX_SPEECH_SECS_FOR_RANGE = (MAX_SCENES * SCENE_CLIP_SECS) - LEAD_SILENCE_SECS - TRAIL_SILENCE_SECS  # 32s


def generate_narration_and_derive_scenes(
    description: str, address: str = None, price: str = None, voice_id: str = None,
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
    prompt = NARRATION_PROMPT.format(description=description, address=address or "non specificato",
                                       price=price or "non specificato")
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

    measurement = _measure_tts_duration(narration_text, voice_id)
    tts_calls_used = 1
    if not measurement["ok"]:
        return {"ok": False, "narration_text": narration_text, "audio_path": None,
                "speech_duration_secs": None, "scene_count": None, "video_duration_secs": None,
                "tts_calls_used": tts_calls_used, "was_trimmed": False,
                "error": "TTS measurement failed on initial narration"}

    speech_secs = measurement["duration_secs"]
    audio_path = measurement["audio_path"]
    was_trimmed = False

    # Single correction pass if outside the tightened band — symmetric:
    # both directions are actively corrected, not just clamped.
    if speech_secs > MAX_SPEECH_SECS_FOR_RANGE:
        target_speech = MAX_SPEECH_SECS_FOR_RANGE - 2.0  # margin under the ceiling, not right at the edge
        naive_target_words = len(narration_text.split()) * (target_speech / speech_secs)
        target_words = max(15, int(naive_target_words * 0.85))  # models tend to undershoot cuts
        try:
            shorten_prompt = SHORTEN_PROMPT.format(actual_secs=speech_secs, target_secs=target_speech,
                                                     target_words=target_words, narration=narration_text)
            response = _track_claude(client.messages.create(model=MODEL, max_tokens=2048,
                                                 messages=[{"role": "user", "content": shorten_prompt}]))
            revised = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
            if revised:
                remeasure = _measure_tts_duration(revised, voice_id)
                tts_calls_used += 1
                if remeasure["ok"]:
                    narration_text, speech_secs, audio_path = revised, remeasure["duration_secs"], remeasure["audio_path"]
        except Exception as e:
            log.warning(f"[Scraper] Shorten pass failed, proceeding as-is: {e}")

        if speech_secs > MAX_SPEECH_SECS_FOR_RANGE and audio_path:
            # still over after one pass — hard cap and fade-trim rather
            # than build an ever-longer video
            audio_path = _fade_out_and_trim(audio_path, MAX_SPEECH_SECS_FOR_RANGE)
            speech_secs = MAX_SPEECH_SECS_FOR_RANGE
            was_trimmed = True

    elif speech_secs < MIN_SPEECH_SECS_FOR_RANGE:
        target_speech = MIN_SPEECH_SECS_FOR_RANGE + 3.0  # margin above the floor
        extra_words = int((target_speech - speech_secs) * WORDS_PER_SECOND_ESTIMATE)
        try:
            extend_prompt = EXTEND_PROMPT.format(actual_secs=speech_secs, target_secs=target_speech,
                                                   extra_words=extra_words, description=description,
                                                   narration=narration_text)
            response = _track_claude(client.messages.create(model=MODEL, max_tokens=2048,
                                                 messages=[{"role": "user", "content": extend_prompt}]))
            revised = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
            if revised:
                remeasure = _measure_tts_duration(revised, voice_id)
                tts_calls_used += 1
                if remeasure["ok"]:
                    narration_text, speech_secs, audio_path = revised, remeasure["duration_secs"], remeasure["audio_path"]
        except Exception as e:
            log.warning(f"[Scraper] Extend pass failed, proceeding as-is "
                        f"(may result in a shorter-than-usual video — acceptable if the listing "
                        f"genuinely has little content, not silently forced): {e}")
        # NOTE: if still short after one extend attempt (e.g. genuinely
        # sparse listing), we deliberately do NOT loop further or invent
        # content — scene_count will just land at MIN_SCENES with a bit
        # more trailing silence than usual, which is preferable to padding
        # with unsupported claims.

    needed_secs = speech_secs + LEAD_SILENCE_SECS + TRAIL_SILENCE_SECS
    scene_count = math.ceil(needed_secs / SCENE_CLIP_SECS)
    scene_count = max(MIN_SCENES, min(MAX_SCENES, scene_count))

    # Always prefer the TIGHTEST-fitting scene count, not just whatever
    # ceil() lands on — rounding up can otherwise leave far more than
    # TRAIL_SILENCE_SECS of dead air (e.g. 28.4s speech needing 31.4s
    # total rounds all the way up to 35s, leaving 5.6s trailing instead of
    # ~2-3s). Since scene_count is already a ceiling, the trim needed to
    # drop to one fewer scene is mathematically always LESS than one full
    # SCENE_CLIP_SECS (i.e. under 5s) — a small, safe edit, not a big cut.
    # Only kept at the higher scene count if the lower one would be
    # unreachable (i.e. already at MIN_SCENES).
    if scene_count > MIN_SCENES and audio_path:
        lower_scene_count = scene_count - 1
        max_speech_for_lower = (lower_scene_count * SCENE_CLIP_SECS) - LEAD_SILENCE_SECS - TRAIL_SILENCE_SECS
        if speech_secs > max_speech_for_lower:
            trim_amount = speech_secs - max_speech_for_lower
            audio_path = _fade_out_and_trim(audio_path, max_speech_for_lower)
            speech_secs = max_speech_for_lower
            scene_count = lower_scene_count
            was_trimmed = True
            log.info(f"[Scraper] Trimmed {trim_amount:.1f}s to fit {lower_scene_count} scenes "
                     f"instead of {lower_scene_count + 1} (avoids excess trailing silence)")

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
        "error": None,
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
    for category in PRIORITY_ORDER:
        photos = selection["selected"].get(category, [])
        for photo in photos:
            scenes.append({
                "caption": captions.get(category, category),
                "voiceover": "",  # continuous narration track applied separately, not per-scene
                "space_type": _CATEGORY_TO_SPACE_TYPE.get(category, "large"),
                "pov_movement": _CATEGORY_TO_POV_MOVEMENT.get(category, "gentle_arc"),
                "duration": clip_duration_secs,
                "local_image_path": photo.get("local_path"),
                "category": category,
                "remove_watermark": True,
            })
    return scenes


# ── Photo selection: priority order + gap detection ─────────────────────────

def select_photos(photos: list, target_per_category: dict = None) -> dict:
    """
    Selects photos per category following PRIORITY_ORDER, per the agreed
    rule: surface gaps and require manual upload rather than silently
    degrading (e.g. reusing exterior shots to pad out a missing kitchen
    category).

    target_per_category: e.g. {"exterior": 1, "living": 2, "kitchen": 1,
    "bedrooms": 2, "bathrooms": 1, "outdoor": 1} — defaults to 1 each if not
    specified; this default is a placeholder and should be confirmed against
    real product requirements (how many total scenes does a typical video
    need?) rather than treated as final.

    Returns:
      {
        "selected": {category: [photo, ...], ...},
        "gaps": [category, ...],   # categories with fewer photos than requested
        "total_selected": int,
      }
    """
    if target_per_category is None:
        target_per_category = {cat: 1 for cat in PRIORITY_ORDER}

    by_category = {cat: [] for cat in PRIORITY_ORDER}
    for p in photos:
        cat = p.get("category")
        if cat in by_category:
            by_category[cat].append(p)

    selected = {}
    gaps = []
    for cat in PRIORITY_ORDER:
        wanted = target_per_category.get(cat, 1)
        available = by_category[cat]
        selected[cat] = available[:wanted]
        if len(available) < wanted:
            gaps.append({"category": cat, "wanted": wanted, "found": len(available)})

    return {
        "selected": selected,
        "gaps": gaps,
        "total_selected": sum(len(v) for v in selected.values()),
    }


QUALITY_RANKING_PROMPT = """You are selecting the best photo(s) of a "{category}" for a real estate video. You'll see {n} candidate photos, labeled Photo 1 through Photo {n}.

Rank them from best to worst based on:
- NO people visible in the photo — this is a significant penalty, avoid photos with people
- NO cars or other vehicles visible in the shot — same penalty as people; prefer a clean, uncluttered view of the property itself
- Clearly shows the defining features of a {category} (e.g. a visible bed for a bedroom, sink/counter/appliances for a kitchen, toilet/shower/sink for a bathroom, a clear building facade for exterior)
- Natural light present, well-lit rather than dark or harshly artificial
- The room/space is shown fully and spaciously in frame, not a cramped or heavily cropped angle — a fuller, more complete view is better. This also matters practically: a fuller frame gives the AI video-generation model more real visual information to work with, which reduces the risk of it inventing or distorting details in an ambiguous or heavily-cropped area.

Return ONLY a JSON array of integers, the photo numbers ordered best to worst, e.g. [3, 1, 2]. No other text.
"""


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
        return candidates

    pool = candidates[:max_to_compare]
    remainder = candidates[max_to_compare:]

    try:
        import base64
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        content = [{"type": "text", "text": QUALITY_RANKING_PROMPT.format(category=category, n=len(pool))}]
        for i, photo in enumerate(pool):
            resp = requests.get(photo["url"], timeout=15)
            resp.raise_for_status()
            b64 = base64.b64encode(resp.content).decode("utf-8")
            content.append({"type": "text", "text": f"Photo {i + 1}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})

        response = _track_claude(client.messages.create(model=MODEL, max_tokens=200,
                                             messages=[{"role": "user", "content": content}]))
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        order_match = re.search(r"\[[\d,\s]+\]", raw)
        if not order_match:
            return candidates
        order = json.loads(order_match.group(0))
        ranked = [pool[i - 1] for i in order if 1 <= i <= len(pool)]
        ranked_ids = {id(p) for p in ranked}
        for p in pool:
            if id(p) not in ranked_ids:
                ranked.append(p)  # safety: include anything the model's ranking missed
        return ranked + remainder
    except Exception as e:
        log.warning(f"[Scraper] Quality ranking failed for {category}, using original order: {e}")
        return candidates


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
    by_category = {cat: [] for cat in PRIORITY_ORDER}
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

