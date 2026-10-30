"""
immobiliare_it_claude.py

Extracts photos (with labels + categories), description, price, and address
from an immobiliare.it listing page — using the Claude API's web_fetch server
tool instead of a direct HTTP request from this server.

WHY: direct requests.get() from this VPS gets a 403 Forbidden — confirmed
via live testing (July 9 2026) to be IP-based blocking specific to
datacenter/hosting IPs, not a header/User-Agent problem (a full realistic
browser header set made no difference; the exact same URL loaded normally
from a real residential browser). The Claude API's web_fetch tool runs
server-side on Anthropic's infrastructure, not this VPS, and is confirmed
working on this exact URL (used directly in the development conversation
that produced this file).

This also replaces the separate BeautifulSoup-based parsing in
immobiliare_it.py — instead of fetching raw HTML and guessing at DOM
selectors for description/price (which was never verified against real
markup), Claude reads the fetched page semantically and returns the fields
directly, which should be more robust against future markup/redesign
changes too.

NEW REQUIREMENTS before this can run:
  - `anthropic` Python package — add to requirements.txt
  - `ANTHROPIC_API_KEY` — add to .env (a NEW key, separate from FAL_KEY /
    ELEVENLABS_API_KEY / OPENROUTER_API_KEY already there)

NOT YET VERIFIED — needs a real test run on the server (this sandbox has no
network access and no API key to test with):
  - The exact web_fetch tool type/version string below (`web_fetch_20250910`)
    — check this against the current Claude API docs
    (platform.claude.com/docs) before running; if the API rejects it with an
    "unknown tool type" error, that's the fix needed, not a deeper problem.
  - Real-world extraction quality/reliability on this and other listings.
  - Actual token cost in practice, vs. the ~$0.02/listing estimate.
"""

import os
import re
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"  # cheapest current model; upgrade to
                                       # claude-sonnet-5 if extraction quality
                                       # proves unreliable on tricky listings

CATEGORIES = ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor", "uncategorized"]

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
- "label_it" is the photo's own caption/label as shown on the page (in Italian).
- Map each photo's label to exactly one category: exterior (building facade, outdoor view of the property itself), living (living room, dining room, study, hallway, stairs), kitchen, bedrooms, bathrooms (including laundry/utility rooms), outdoor (garden, terrace, courtyard, parking area, land/terrain). If a label doesn't clearly fit any of these, use "uncategorized".
- "description" is the full property description text from the listing (not the shortened meta/preview version).
- "price" and "address" as shown on the page.
"""


def extract_listing(url: str) -> dict:
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
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            tools=[{
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": 1,
            }],
            extra_headers={"anthropic-beta": "web-fetch-2025-09-10"},  # REQUIRED — web_fetch is beta-gated
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(url=url)}],
        )

        text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        raw = "".join(text_parts).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()

        if not raw:
            block_types = [getattr(b, "type", "?") for b in response.content]
            return {"ok": False, "photos": [], "description": "", "price": None,
                    "address": None,
                    "error": f"No text content in response. stop_reason={response.stop_reason}, "
                             f"content block types={block_types}"}

        # Extract JSON wherever it appears in the text — Claude sometimes adds
        # a friendly preface sentence before the actual JSON/code fence, so
        # don't assume the response starts with it.
        json_str = raw
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence_match:
            json_str = fence_match.group(1)
        else:
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if brace_match:
                json_str = brace_match.group(0)

        data = json.loads(json_str)


        # sanity-check categories — anything unexpected gets bucketed as
        # uncategorized rather than silently trusting an unexpected value
        for p in data.get("photos", []):
            if p.get("category") not in CATEGORIES:
                p["category"] = "uncategorized"

        data["ok"] = True
        data["error"] = None
        return data

    except json.JSONDecodeError as e:
        return {"ok": False, "photos": [], "description": "", "price": None,
                "address": None, "error": f"JSON parse failed: {e}. Extracted text was: {json_str[:500]}"}
    except Exception as e:
        return {"ok": False, "photos": [], "description": "", "price": None,
                "address": None, "error": str(e)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 immobiliare_it_claude.py <listing_url>")
        sys.exit(1)
    result = extract_listing(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n--- Summary: {len(result.get('photos', []))} photos found ---")
    by_cat = {}
    for p in result.get("photos", []):
        by_cat.setdefault(p["category"], 0)
        by_cat[p["category"]] += 1
    for cat, count in by_cat.items():
        print(f"  {cat}: {count}")
