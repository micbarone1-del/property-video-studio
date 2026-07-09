"""
scrapers/immobiliare_it.py

Extracts photos (with room/space labels) and listing description from an
immobiliare.it listing page.

STATUS: first draft, built from manual inspection of one real listing
(https://www.immobiliare.it/annunci/127249685/, July 9 2026) — NOT yet
tested against live output. Run this file's __main__ block against a real
URL on the server (which has real internet access; the dev sandbox that
wrote this does not) before trusting it in the pipeline.

CONFIRMED (seen directly in the real page's rendered content):
  - Gallery photos are labeled with Italian room names via each <img>'s alt
    text — e.g. "Facciata", "Salone", "Cucina", "Camera da letto", "Bagno",
    "Giardino", "Terrazzo". This lines up exactly with the project's decision
    to prefer the site's own labels over AI classification.
  - Photo URLs live on a dedicated CDN host+path: pwm.im-cdn.it/image/{id}/...
  - Floor plans live on a DIFFERENT host+path: pic.im-cdn.it/plan/...
  - The listing agent's own headshot lives on yet another path:
    pic.im-cdn.it/imagenoresize/...
  Both of the above are excluded by only accepting the pwm.im-cdn.it/image/
  pattern — this is a clean, reliable filter, not a fragile heuristic.

NOT YET CONFIRMED (best-effort first pass, needs real testing):
  - The exact DOM structure around the "Descrizione" section — the code
    below walks to the next sibling element, which may or may not be
    correct against the real HTML tree.
  - Price and address extraction — regex-based first guess.
  - Highest-resolution image URL variant. Gallery photos default to a
    "-c" (compressed) size; there is likely a higher-resolution variant
    on the same CDN, but the exact URL pattern for it hasn't been confirmed.
    Using low-res source photos would hurt AI video generation quality, so
    this needs resolving before production use — check what URL variants
    exist by trying common patterns (e.g. removing "-c", or a "xl"/"orig"
    suffix) against a real image ID once this runs.

NEW DEPENDENCY: this needs `beautifulsoup4`, which is not currently in
requirements.txt — add `beautifulsoup4` before deploying this.
"""

import re
import requests
from bs4 import BeautifulSoup

# ── Italian room-label -> project category vocabulary ───────────────────────
# Maps immobiliare.it's actual observed alt-text labels to the category
# order already agreed for this project: exterior -> living -> kitchen ->
# bedrooms -> bathrooms -> outdoor. Any label NOT in this dict falls through
# to "uncategorized", which should route to the existing Florence-2 vision
# classification (vision_analysis.py) as the agreed AI fallback.
LABEL_TO_CATEGORY = {
    # exterior
    "facciata": "exterior",
    "vista": "exterior",
    "zona": "exterior",
    # outdoor
    "giardino": "outdoor",
    "terreno": "outdoor",
    "terrazzo": "outdoor",
    "cortile interno": "outdoor",
    "posto macchina": "outdoor",
    # living areas
    "salone": "living",
    "sala da pranzo": "living",
    "studio": "living",
    "scala": "living",
    # kitchen
    "cucina": "kitchen",
    # bedrooms
    "camera da letto": "bedrooms",
    "cameretta": "bedrooms",
    # bathrooms / utility — "lavanderia" (laundry) doesn't have a perfect
    # bucket in the current 6-category vocabulary; bucketed here as the
    # closest fit, flagged for a human decision on whether that's right
    "bagno": "bathrooms",
    "lavanderia": "bathrooms",
}

# Only real property photos — excludes floor plans and the agent's headshot,
# which live on different CDN paths (see module docstring).
PHOTO_URL_PATTERN = re.compile(r"https://pwm\.im-cdn\.it/image/\d+/[\w\-]+\.jpg")


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
        session = requests.Session()
        session.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,*/*;q=0.8"),
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Upgrade-Insecure-Requests": "1",
        })
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return {"ok": False, "photos": [], "description": "", "price": None,
                "address": None, "error": f"fetch failed: {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    # ── Photos ────────────────────────────────────────────────────────────
    photos = []
    seen_urls = set()
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if not PHOTO_URL_PATTERN.match(src):
            continue
        if src in seen_urls:
            continue
        seen_urls.add(src)
        label_it = (img.get("alt") or "").strip()
        category = LABEL_TO_CATEGORY.get(label_it.lower(), "uncategorized")
        photos.append({"url": src, "label_it": label_it, "category": category})

    # ── Description — UNVERIFIED, best-effort first pass ─────────────────
    description = ""
    desc_heading = soup.find(string=re.compile(r"^\s*Descrizione\s*$"))
    if desc_heading:
        container = desc_heading.find_parent()
        if container:
            next_block = container.find_next_sibling()
            if next_block:
                description = next_block.get_text(separator=" ", strip=True)
    if not description:
        # Fallback: the page's own meta description, always present, though
        # shorter/truncated compared to the full on-page text
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            description = meta.get("content", "").strip()

    # ── Price / address — UNVERIFIED, best-effort first pass ──────────────
    price = None
    price_el = soup.find(string=re.compile(r"€\s*[\d.]+"))
    if price_el:
        price = price_el.strip()

    address = None
    h1 = soup.find("h1")
    if h1:
        address = h1.get_text(strip=True)

    return {
        "ok": True,
        "photos": photos,
        "description": description,
        "price": price,
        "address": address,
        "error": None,
    }


if __name__ == "__main__":
    import sys
    import json as _json
    if len(sys.argv) < 2:
        print("Usage: python3 immobiliare_it.py <listing_url>")
        sys.exit(1)
    result = extract_listing(sys.argv[1])
    print(_json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n--- Summary: {len(result['photos'])} photos found ---")
    by_cat = {}
    for p in result["photos"]:
        by_cat.setdefault(p["category"], 0)
        by_cat[p["category"]] += 1
    for cat, count in by_cat.items():
        print(f"  {cat}: {count}")
