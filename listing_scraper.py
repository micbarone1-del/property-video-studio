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
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
import anthropic
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

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
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            tools=[{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1}],
            extra_headers={"anthropic-beta": "web-fetch-2025-09-10"},
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(url=url)}],
        )

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


# ── Download + watermark removal for selected photos ────────────────────────
# Scraped photos come from a public listing portal and are highly likely to
# carry that portal's own watermark — unlike manually uploaded photos, where
# watermark removal is an opt-in toggle (since an agent's own photos usually
# aren't watermarked), removal is the DEFAULT here, not optional. Skipping it
# risks shipping a client video with a competitor portal's logo burned in.

def download_and_dewatermark(photo_url: str, output_dir: Path, filename_stem: str) -> dict:
    """
    Downloads one scraped photo and runs it through the existing
    watermark_removal.py pipeline by default.

    Returns:
      {"ok": bool, "path": str | None, "watermark_removed": bool, "error": str | None}

    If watermark removal itself fails, falls back to the raw downloaded
    image rather than losing the photo entirely — but flags this clearly
    (watermark_removed=False, error populated) so a failure doesn't silently
    ship a possibly-watermarked image without anyone knowing.
    """
    from watermark_removal import remove_watermark

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"{filename_stem}_raw.jpg"
    clean_path = output_dir / f"{filename_stem}.jpg"

    try:
        resp = requests.get(photo_url, timeout=20)
        resp.raise_for_status()
        raw_path.write_bytes(resp.content)
    except Exception as e:
        return {"ok": False, "path": None, "watermark_removed": False,
                "error": f"download failed: {e}"}

    try:
        wm_result = remove_watermark(str(raw_path), str(clean_path))
        if wm_result.get("ok"):
            return {"ok": True, "path": str(clean_path), "watermark_removed": True, "error": None}
        log.warning(f"[Scraper] Watermark removal failed for {photo_url}: {wm_result.get('error')}")
        return {"ok": True, "path": str(raw_path), "watermark_removed": False,
                "error": f"watermark removal failed, using original: {wm_result.get('error')}"}
    except Exception as e:
        log.warning(f"[Scraper] Watermark removal crashed for {photo_url}: {e}")
        return {"ok": True, "path": str(raw_path), "watermark_removed": False,
                "error": f"watermark removal crashed, using original: {e}"}


def download_selected_photos(selection: dict, output_dir: Path) -> dict:
    """
    Downloads and de-watermarks every photo in a select_photos() result —
    only the selected subset, not the full scraped list, to avoid spending
    watermark-removal cost on photos that won't even be used.

    Returns the same {"selected": {...}, "gaps": [...]} structure, with each
    selected photo dict augmented with "local_path" and "watermark_removed".
    Photos that fail to download entirely are dropped and reported in a new
    "download_failures" list rather than silently disappearing.
    """
    download_failures = []
    for category, photos in selection["selected"].items():
        kept = []
        for i, p in enumerate(photos):
            stem = f"{category}_{i:02d}"
            result = download_and_dewatermark(p["url"], output_dir, stem)
            if result["ok"]:
                p["local_path"] = result["path"]
                p["watermark_removed"] = result["watermark_removed"]
                if result["error"]:
                    p["watermark_removal_note"] = result["error"]
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

The video will show these rooms/spaces, in this order: {categories}

Write:
1. A single continuous narration script (in Italian) for the whole video — warm, professional real estate tone, roughly 15-25 seconds of spoken audio per scene (~40-60 words per scene, so about {total_words} words total for {n_scenes} scenes). Should flow as ONE continuous piece, not separated per scene with headers or labels.
2. A short on-screen caption (3-6 words, in Italian) for EACH scene/category listed above.

Return ONLY a JSON object (no other text, no markdown fences):
{{
  "continuous_narration": "...",
  "captions": {{"category_name": "...", ...}}
}}

Base everything on the actual property description above — don't invent details not mentioned there (e.g. don't state a room count or feature that isn't in the description).
"""


def generate_narration_from_description(description: str, selected_categories: list,
                                          address: str = None, price: str = None) -> dict:
    """
    Generates a continuous narration script + per-scene on-screen captions
    from the scraped listing description, via the Claude API (same key as
    extraction, plain text generation — no web_fetch tool needed here).

    Returns:
      {"ok": bool, "continuous_narration": str, "captions": {category: str, ...}, "error": str | None}
    """
    n_scenes = max(len(selected_categories), 1)
    prompt = NARRATION_PROMPT.format(
        description=description,
        address=address or "non specificato",
        price=price or "non specificato",
        categories=", ".join(selected_categories),
        total_words=n_scenes * 50,
        n_scenes=n_scenes,
    )
    raw = ""
    json_str = ""
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        raw = "".join(text_parts).strip()

        json_str = raw
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence_match:
            json_str = fence_match.group(1)
        else:
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if brace_match:
                json_str = brace_match.group(0)

        data = json.loads(json_str)
        return {"ok": True, "continuous_narration": data.get("continuous_narration", ""),
                "captions": data.get("captions", {}), "error": None}
    except json.JSONDecodeError as e:
        return {"ok": False, "continuous_narration": "", "captions": {},
                "error": f"JSON parse failed: {e}. Extracted text was: {json_str[:500]}"}
    except Exception as e:
        return {"ok": False, "continuous_narration": "", "captions": {}, "error": str(e)}


# ── Narration-length adaptation for a fixed video duration ─────────────────
# Standard automated output: 6 scenes x 5s = 30s exactly (5s is Luma Ray 2's
# native duration, the current default/lowest-hallucination-risk tier — 4s
# and 6s both snap to 5s on Luma anyway, so there's no finer-grained control
# available at the video-clip level; the video's TOTAL length is fixed, and
# narration adapts to fit it, not the other way around).
#
# Uses REAL TTS measurement (not a word-count guess) to confirm actual fit,
# matching this project's existing narration-first philosophy. Bounded to
# at most 2 real TTS calls to control cost — accepts the closest result
# after that rather than looping indefinitely.

STANDARD_VIDEO_DURATION_SECS = 30  # 6 scenes x 5s
DURATION_TOLERANCE_SECS = 2        # accept anything within +/-2s without further adjustment
WORDS_PER_SECOND_ESTIMATE = 2.3    # rough Italian speaking-pace estimate for the FIRST draft only —
                                     # every subsequent decision uses real measured TTS duration, not this guess

EXTEND_PROMPT = """The narration below was measured at {actual_secs:.1f} seconds of spoken audio, but the video needs {target_secs} seconds. Extend it by about {extra_words} more words, using ONLY additional real detail from the original property description below — do not invent any facts, features, or details not present in the description.

Original property description:
---
{description}
---

Current narration to extend:
---
{narration}
---

Return ONLY the full extended narration text (no JSON, no markdown, no preamble)."""

SHORTEN_PROMPT = """The narration below was measured at {actual_secs:.1f} seconds of spoken audio when read aloud, but the video needs {target_secs} seconds — it MUST be shorter than that, not just close to it. Rewrite it at no more than {target_words} words. This is a hard ceiling, not a target to approach — err on the side of cutting too much rather than too little, since a version that's slightly too short can be extended, but a version that's still too long will get its ending cut off mid-sentence in the final video.

Keep the most important property details (location, size, standout features) and drop secondary ones first. Keep it flowing naturally — don't just truncate the end.

Current narration to shorten:
---
{narration}
---

Return ONLY the shortened narration text (no JSON, no markdown, no preamble)."""


def _measure_tts_duration(text: str, voice_id: str = None) -> dict:
    """Generates real TTS audio and measures its actual duration — the
    only reliable way to know how long narration text will actually take
    to speak, per this project's existing narration-first approach."""
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
    finally:
        pass  # caller is responsible for cleaning up audio_path if returned


def _pad_audio_with_silence(audio_path: str, extra_secs: float) -> str:
    """Appends trailing silence to an audio file — used for small gaps
    where inventing more narration text would be overkill (a couple of
    seconds of natural pause reads as normal pacing, not dead air)."""
    from pydub import AudioSegment
    audio = AudioSegment.from_file(audio_path)
    silence = AudioSegment.silent(duration=int(extra_secs * 1000))
    padded = audio + silence
    padded.export(audio_path, format="mp3")
    return audio_path


def _fade_out_and_trim(audio_path: str, target_secs: float, fade_ms: int = 800) -> str:
    """Last-resort safety net: if the correction loop still couldn't land
    within tolerance, trim to the target duration with a short fade-out
    rather than leaving an uncontrolled overshoot for the video-assembly
    step to abruptly (and audibly badly) cut off mid-sentence."""
    from pydub import AudioSegment
    audio = AudioSegment.from_file(audio_path)
    target_ms = int(target_secs * 1000)
    if len(audio) <= target_ms:
        return audio_path
    trimmed = audio[:target_ms].fade_out(fade_ms)
    trimmed.export(audio_path, format="mp3")
    return audio_path


def generate_narration_matching_duration(
    description: str, selected_categories: list, address: str = None, price: str = None,
    target_duration_secs: float = STANDARD_VIDEO_DURATION_SECS,
    tolerance_secs: float = DURATION_TOLERANCE_SECS,
    voice_id: str = None,
    max_correction_rounds: int = 2,
) -> dict:
    """
    Generates narration sized to fit a FIXED target video duration (the
    video length is fixed by scene count x clip duration; narration adapts
    to it, not the other way around) — using real TTS measurement, not a
    word-count guess, to confirm the fit.

    Strategy:
      1. Generate an initial narration text, TTS it, measure real duration.
      2. Loop up to max_correction_rounds times: if too long, ask for a
         stricter rewrite (hard word ceiling, explicit "cut too much rather
         than too little" instruction); if too short, ask for an EXTENDED
         version using only real description content. Re-measure via real
         TTS after each attempt.
      3. If still outside tolerance after all rounds: pad with silence if
         short (safe, invents nothing), or apply a graceful fade-out trim
         if still long (avoids an abrupt mid-sentence cutoff — this is the
         genuine safety net, not just accepting a mismatch).

    Bounded to at most (1 + max_correction_rounds) real TTS calls — default
    3 total — to control cost while prioritizing actually landing within
    tolerance, since an audio track that's still too long risks getting
    its ending cut off in the final video.

    Returns:
      {"ok": bool, "narration_text": str, "audio_path": str | None,
       "final_duration_secs": float | None, "captions": dict,
       "tts_calls_used": int, "was_trimmed": bool, "error": str | None}
    """
    base = generate_narration_from_description(description, selected_categories, address, price)
    if not base["ok"]:
        return {"ok": False, "narration_text": "", "audio_path": None,
                "final_duration_secs": None, "captions": {}, "tts_calls_used": 0,
                "was_trimmed": False, "error": f"initial narration generation failed: {base['error']}"}

    narration_text = base["continuous_narration"]
    captions = base["captions"]
    tts_calls_used = 0
    audio_path = None
    actual_secs = None

    measurement = _measure_tts_duration(narration_text, voice_id)
    tts_calls_used += 1
    if not measurement["ok"]:
        return {"ok": False, "narration_text": narration_text, "audio_path": None,
                "final_duration_secs": None, "captions": captions, "tts_calls_used": tts_calls_used,
                "was_trimmed": False, "error": "TTS measurement failed on initial narration"}

    actual_secs = measurement["duration_secs"]
    audio_path = measurement["audio_path"]

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    for _round in range(max_correction_rounds):
        diff = actual_secs - target_duration_secs
        if abs(diff) <= tolerance_secs:
            break  # within tolerance — done, no more correction needed

        if diff > tolerance_secs:
            # too long — shrink, with an explicit safety margin below the
            # naive proportional estimate, since models tend to undershoot
            # how much they actually cut when only given a soft target
            naive_target_words = len(narration_text.split()) * (target_duration_secs / actual_secs)
            target_words = max(15, int(naive_target_words * 0.85))  # 15% safety margin
            prompt = SHORTEN_PROMPT.format(actual_secs=actual_secs, target_secs=target_duration_secs,
                                            target_words=target_words, narration=narration_text)
        else:
            extra_words = int(abs(diff) * WORDS_PER_SECOND_ESTIMATE)
            prompt = EXTEND_PROMPT.format(actual_secs=actual_secs, target_secs=target_duration_secs,
                                           extra_words=extra_words, description=description,
                                           narration=narration_text)
        try:
            response = client.messages.create(model=MODEL, max_tokens=2048,
                                                 messages=[{"role": "user", "content": prompt}])
            revised = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
            if not revised:
                break
            remeasure = _measure_tts_duration(revised, voice_id)
            tts_calls_used += 1
            if not remeasure["ok"]:
                break
            narration_text = revised
            actual_secs = remeasure["duration_secs"]
            audio_path = remeasure["audio_path"]
        except Exception as e:
            log.warning(f"[Scraper] Narration length-adjustment round failed, stopping loop: {e}")
            break

    was_trimmed = False
    final_diff = actual_secs - target_duration_secs
    if final_diff < -tolerance_secs and audio_path:
        audio_path = _pad_audio_with_silence(audio_path, abs(final_diff))
        actual_secs = target_duration_secs
    elif final_diff > tolerance_secs and audio_path:
        # Safety net: correction rounds didn't land it — trim with a
        # graceful fade-out rather than leaving an uncontrolled overshoot
        # for the video-assembly step to abruptly cut off mid-sentence.
        audio_path = _fade_out_and_trim(audio_path, target_duration_secs)
        actual_secs = target_duration_secs
        was_trimmed = True
        log.warning(f"[Scraper] Narration still {final_diff:.1f}s over target after "
                    f"{max_correction_rounds} correction round(s) — applied fade-out trim as safety net.")

    return {
        "ok": True,
        "narration_text": narration_text,
        "audio_path": audio_path,
        "final_duration_secs": actual_secs,
        "captions": captions,
        "tts_calls_used": tts_calls_used,
        "was_trimmed": was_trimmed,
        "error": None,
    }


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


def build_standard_video_scenes_config(selection: dict, captions: dict, clip_duration_secs: int = 5) -> list:
    """
    Returns a scenes_config list in PRIORITY_ORDER, one scene per category
    that has a selected photo, ready to hand to the existing job-creation
    pipeline. Each scene: {scene_id placeholder, caption, voiceover: "",
    space_type, pov_movement, duration, local_image_path}.
    """
    scenes = []
    for category in PRIORITY_ORDER:
        photos = selection["selected"].get(category, [])
        if not photos:
            continue
        photo = photos[0]
        scenes.append({
            "caption": captions.get(category, category),
            "voiceover": "",  # continuous narration track applied separately, not per-scene
            "space_type": _CATEGORY_TO_SPACE_TYPE.get(category, "large"),
            "pov_movement": "walk_in_explore",
            "duration": clip_duration_secs,
            "local_image_path": photo.get("local_path"),
            "category": category,
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

    print("\n--- Photo selection (default: 1 per category) ---")
    selection = select_photos(result["photos"])
    for cat, photos in selection["selected"].items():
        print(f"  {cat}: {len(photos)} selected")
    if selection["gaps"]:
        print("\n  GAPS DETECTED — manual upload needed for:")
        for gap in selection["gaps"]:
            print(f"    {gap['category']}: wanted {gap['wanted']}, found {gap['found']}")
    else:
        print("\n  No gaps — all categories satisfied.")

    print("\n--- Downloading selected photos + removing watermarks (default ON for scraped photos) ---")
    test_scratch_dir = BASE_DIR / "jobs" / "_test_scratch" / "scraper_test"
    selection = download_selected_photos(selection, test_scratch_dir)
    for cat, photos in selection["selected"].items():
        for p in photos:
            status = "watermark removed" if p.get("watermark_removed") else f"NOT removed ({p.get('watermark_removal_note', 'unknown reason')})"
            print(f"  {cat}: {p.get('local_path')} — {status}")
    if selection["download_failures"]:
        print("\n  DOWNLOAD FAILURES:")
        for f in selection["download_failures"]:
            print(f"    {f['category']}: {f['error']}")

    print(f"\nDescription: {result['description'][:100]}...")
    print(f"Price: {result['price']}")
    print(f"Address: {result['address']}")

    print("\n--- Generating narration matched to standard 30s video (6 scenes x 5s) ---")
    selected_categories = [cat for cat, photos in selection["selected"].items() if photos]
    narration = generate_narration_matching_duration(
        result["description"], selected_categories, result["address"], result["price"]
    )
    if narration["ok"]:
        print(f"\nFinal narration ({narration['tts_calls_used']} TTS call(s) used, "
              f"final duration: {narration['final_duration_secs']:.1f}s, target: 30s"
              f"{', TRIMMED via fade-out safety net' if narration['was_trimmed'] else ''}):\n")
        print(narration["narration_text"])
        print("\nPer-scene captions:")
        for cat, caption in narration["captions"].items():
            print(f"  {cat}: {caption}")
        if narration["audio_path"]:
            print(f"\nAudio file: {narration['audio_path']} (listen to this to judge quality/pacing)")

        scenes_config = build_standard_video_scenes_config(selection, narration["captions"])
        print(f"\n--- scenes_config ready for job creation ({len(scenes_config)} scenes) ---")
        for s in scenes_config:
            print(f"  {s['category']}: {s['duration']}s, space_type={s['space_type']}, image={s['local_image_path']}")
    else:
        print(f"NARRATION GENERATION FAILED: {narration['error']}")

