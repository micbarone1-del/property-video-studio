"""
watermark_removal.py
──────────────────────
AI-driven watermark/logo removal from input photos, using fal.ai's
object-removal endpoint. Detection and inpainting happen in a single
API call — no manual masking, no fixed-region assumptions (watermark
position/size varies too much between agencies for that to be reliable).

Design (agreed):
  - AI-driven detection, not fixed-corner heuristics
  - Explicit per-photo toggle — user enables it when a watermark is
    actually present, not automatic on every photo
  - If removal fails or the result looks unreliable, flag it as a QC
    issue rather than silently using a possibly-botched image
"""

import os
import logging
from pathlib import Path

log = logging.getLogger(__name__)

OBJECT_REMOVAL_ENDPOINT = "fal-ai/image-editing/object-removal"

# Prompts tried in order — watermarks vary (text overlay, logo graphic,
# semi-transparent stamp). Trying a couple of phrasings improves hit rate
# without needing the user to describe their specific watermark.
_REMOVAL_PROMPTS = [
    "watermark",
    "logo overlay text",
]


def remove_watermark(image_path: str, output_path: str) -> dict:
    """
    Attempts to remove a watermark/logo from the image using AI object
    removal. Returns a dict with success status and a confidence flag
    the caller can use to decide whether to surface a QC warning.

    This makes exactly ONE real attempt (not multiple paid retries) —
    if it fails, the caller should flag it for QC review rather than
    silently proceeding with a possibly-still-watermarked image.
    """
    try:
        import fal_client
        image_url = fal_client.upload_file(image_path)

        log.info(f"[Watermark] Attempting removal on {image_path}")
        result = fal_client.subscribe(
            OBJECT_REMOVAL_ENDPOINT,
            arguments={
                "image_url": image_url,
                "prompt": _REMOVAL_PROMPTS[0],
            }
        )

        images = result.get("images", [])
        if not images:
            log.warning(f"[Watermark] No output image returned for {image_path}")
            return {"ok": False, "reason": "no_output", "needs_qc_review": True}

        image_url_out = images[0].get("url")
        if not image_url_out:
            return {"ok": False, "reason": "no_url", "needs_qc_review": True}

        import requests
        resp = requests.get(image_url_out, timeout=60)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)

        log.info(f"[Watermark] Removed successfully → {output_path}")
        return {"ok": True, "output_path": output_path, "needs_qc_review": False}

    except Exception as e:
        log.error(f"[Watermark] Removal failed for {image_path}: {e}")
        return {"ok": False, "reason": str(e), "needs_qc_review": True}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python3 watermark_removal.py <input.jpg> <output.jpg>")
        sys.exit(1)
    result = remove_watermark(sys.argv[1], sys.argv[2])
    print(result)
    sys.exit(0 if result["ok"] else 1)
