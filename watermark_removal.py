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

FORMAT PRESERVATION (added July 9 2026): this endpoint is a whole-image
diffusion edit, not a masked inpaint — it regenerates the entire image and
does NOT reliably preserve the input's exact resolution/aspect ratio.
Confirmed via live testing: a 1440x900 input came back as 1328x800 (a
different aspect ratio, not just a scaled-down version) when no aspect_ratio
hint was given. Two-part fix:
  1. Request the closest-matching preset via the model's own `aspect_ratio`
     parameter (reduces how much the model has to deviate from the input
     shape in the first place).
  2. Resize the result back to the EXACT original dimensions as a guarantee
     — the model only supports 9 fixed aspect-ratio presets, not arbitrary
     dimensions, so even with the right preset requested, the output won't
     usually match a real photo's exact pixel dimensions without this step.
"""

import os
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

OBJECT_REMOVAL_ENDPOINT = "fal-ai/image-editing/object-removal"

# Prompts tried in order — watermarks vary (text overlay, logo graphic,
# semi-transparent stamp). Trying a couple of phrasings improves hit rate
# without needing the user to describe their specific watermark.
_REMOVAL_PROMPTS = [
    "watermark",
    "logo overlay text",
]

# Preset aspect ratios this specific fal.ai endpoint accepts — passing the
# closest match keeps the model's output shape as close as possible to the
# real input before the exact-dimension resize step below.
_ASPECT_RATIO_PRESETS = {
    "21:9": 21 / 9, "16:9": 16 / 9, "4:3": 4 / 3, "3:2": 3 / 2, "1:1": 1.0,
    "2:3": 2 / 3, "3:4": 3 / 4, "9:16": 9 / 16, "9:21": 9 / 21,
}


def _closest_aspect_ratio_preset(width: int, height: int) -> str:
    ratio = width / height
    return min(_ASPECT_RATIO_PRESETS, key=lambda k: abs(_ASPECT_RATIO_PRESETS[k] - ratio))


def remove_watermark(image_path: str, output_path: str) -> dict:
    """
    Attempts to remove a watermark/logo from the image using AI object
    removal. Returns a dict with success status and a confidence flag
    the caller can use to decide whether to surface a QC warning.

    This makes exactly ONE real attempt (not multiple paid retries) —
    if it fails, the caller should flag it for QC review rather than
    silently proceeding with a possibly-still-watermarked image.

    The output is guaranteed to match the input's exact pixel dimensions
    (see module docstring) — this was NOT true before July 9 2026.
    """
    try:
        with Image.open(image_path) as original:
            orig_width, orig_height = original.size

        aspect_ratio_hint = _closest_aspect_ratio_preset(orig_width, orig_height)

        import fal_client
        image_url = fal_client.upload_file(image_path)

        log.info(f"[Watermark] Attempting removal on {image_path} "
                 f"(original {orig_width}x{orig_height}, requesting aspect_ratio={aspect_ratio_hint})")
        result = fal_client.subscribe(
            OBJECT_REMOVAL_ENDPOINT,
            arguments={
                "image_url": image_url,
                "prompt": _REMOVAL_PROMPTS[0],
                "aspect_ratio": aspect_ratio_hint,
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

        tmp_path = output_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(resp.content)

        # Guarantee exact original dimensions regardless of what the model
        # actually returned — this is what makes format-preservation
        # reliable rather than "usually close if the aspect_ratio hint
        # happened to help."
        with Image.open(tmp_path) as result_img:
            returned_size = result_img.size
            if returned_size != (orig_width, orig_height):
                log.info(f"[Watermark] Resizing result from {returned_size} "
                         f"back to original {orig_width}x{orig_height}")
                result_img = result_img.convert("RGB").resize(
                    (orig_width, orig_height), Image.LANCZOS
                )
            result_img.save(output_path, "JPEG", quality=95)
        os.remove(tmp_path)

        log.info(f"[Watermark] Removed successfully → {output_path} ({orig_width}x{orig_height})")
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
