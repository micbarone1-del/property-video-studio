"""
image_enhance.py
────────────────
Two-stage image enhancement pipeline for real estate photos:

  Stage 1 – Lighting & colour correction (local, via Pillow)
    • Auto white-balance (grey-world)
    • Shadow lift (gamma on shadows only)
    • Contrast / clarity via CLAHE-style local contrast
    • Gentle saturation boost

  Stage 2 – AI Upscaling (remote, via fal.ai)
    • Uses fal-ai/aura-sr (4× upscale, realistic textures)
    • Falls back gracefully if FAL_KEY is missing or call fails

Usage:
    from image_enhance import enhance_image

    enhanced_path = enhance_image("input.jpg", "output_enhanced.jpg")
    # Returns path to enhanced image, or original path if enhancement fails
"""

import os
import io
import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# ── Optional imports (Pillow is required; fal_client is optional) ──────────────
try:
    from PIL import Image, ImageEnhance, ImageFilter
    import numpy as np
    _PIL_OK = True
except ImportError:
    log.warning("Pillow / numpy not installed. Lighting correction will be skipped.")
    _PIL_OK = False

try:
    import fal_client
    _FAL_OK = True
except ImportError:
    log.warning("fal_client not installed. AI upscaling will be skipped.")
    _FAL_OK = False


# ── Constants ──────────────────────────────────────────────────────────────────
UPSCALE_ENDPOINT = "fal-ai/aura-sr"          # 4× upscaler
UPSCALE_SCALE   = 4
MAX_DIM_BEFORE_UPSCALE = 2048                 # Don't upscale images already this large
MIN_DIM_FOR_UPSCALE    = 512                  # Skip upscale if smaller than this (too small)


# ── Stage 1: Local lighting / colour correction ────────────────────────────────

def _grey_world_white_balance(img_array: "np.ndarray") -> "np.ndarray":
    """
    Grey-world white balance assumption.
    Scales each channel so the mean of all three channels is equal.
    Removes colour casts from mixed lighting (very common in property photos).
    """
    result = img_array.astype(np.float32)
    means = result.mean(axis=(0, 1))           # per-channel mean
    global_mean = means.mean()
    scale = global_mean / (means + 1e-6)
    scale = np.clip(scale, 0.5, 2.0)          # don't over-correct
    result *= scale
    return np.clip(result, 0, 255).astype(np.uint8)


def _shadow_lift(img_array: "np.ndarray", gamma: float = 1.25, shadow_limit: int = 100) -> "np.ndarray":
    """
    Applies a gamma curve only to pixels darker than shadow_limit (0-255).
    Lifts dark areas without washing out the midtones or highlights.
    Real estate photos often have underexposed corners and window-lit rooms.
    """
    lut = np.arange(256, dtype=np.float32)
    mask = lut < shadow_limit
    lut[mask] = shadow_limit * (lut[mask] / shadow_limit) ** (1.0 / gamma)
    lut = np.clip(lut, 0, 255).astype(np.uint8)

    result = img_array.copy()
    for c in range(min(3, result.shape[2])):
        result[:, :, c] = lut[result[:, :, c]]
    return result


def _local_contrast_boost(img: "Image.Image", radius: int = 20, amount: float = 0.4) -> "Image.Image":
    """
    Unsharp-mask style local contrast boost (clarity).
    Sharpens fine texture (wall texture, wood grain, tiles) without haloing.
    """
    blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
    blurred_arr = np.array(blurred, dtype=np.float32)
    img_arr     = np.array(img,     dtype=np.float32)
    result = img_arr + amount * (img_arr - blurred_arr)
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def _boost_saturation(img: "Image.Image", factor: float = 1.20) -> "Image.Image":
    """
    Gentle saturation boost. Factor 1.0 = no change, 1.2 = +20% colour vividness.
    Keeps the image looking natural while making colours pop on screen.
    """
    enhancer = ImageEnhance.Color(img)
    return enhancer.enhance(factor)


def correct_lighting(input_path: str, output_path: str) -> str:
    """
    Runs all local correction passes on an image and saves the result.
    Returns output_path on success, input_path on failure.
    """
    if not _PIL_OK:
        log.warning("Pillow unavailable — skipping lighting correction.")
        return input_path

    try:
        img = Image.open(input_path).convert("RGB")
        arr = np.array(img)

        # 1. White balance
        arr = _grey_world_white_balance(arr)

        # 2. Shadow lift
        arr = _shadow_lift(arr, gamma=1.30, shadow_limit=90)

        img = Image.fromarray(arr)

        # 3. Local contrast (clarity)
        img = _local_contrast_boost(img, radius=25, amount=0.35)

        # 4. Saturation
        img = _boost_saturation(img, factor=1.15)

        img.save(output_path, quality=95)
        log.info(f"[Enhance] Lighting corrected → {output_path}")
        return output_path

    except Exception as e:
        log.error(f"[Enhance] Lighting correction failed: {e}")
        return input_path


# ── Stage 2: AI Upscaling via fal.ai ──────────────────────────────────────────

def _should_upscale(input_path: str) -> bool:
    """Decide whether upscaling makes sense for this image."""
    if not _PIL_OK:
        return False
    try:
        with Image.open(input_path) as img:
            w, h = img.size
        max_dim = max(w, h)
        if max_dim >= MAX_DIM_BEFORE_UPSCALE:
            log.info(f"[Enhance] Image already large ({w}×{h}) — skipping AI upscale.")
            return False
        if max_dim < MIN_DIM_FOR_UPSCALE:
            log.info(f"[Enhance] Image too small for upscale ({w}×{h}) — skipping.")
            return False
        return True
    except Exception:
        return False


def upscale_image(input_path: str, output_path: str) -> str:
    """
    Calls fal-ai/aura-sr to upscale the image 4×.
    Returns output_path on success, input_path on failure.
    """
    if not _FAL_OK:
        log.warning("[Enhance] fal_client unavailable — skipping AI upscale.")
        return input_path

    if not os.environ.get("FAL_KEY"):
        log.warning("[Enhance] FAL_KEY not set — skipping AI upscale.")
        return input_path

    if not _should_upscale(input_path):
        return input_path

    try:
        log.info(f"[Enhance] Uploading image to fal.ai for upscaling...")
        image_url = fal_client.upload_file(input_path)

        log.info(f"[Enhance] Running {UPSCALE_ENDPOINT}...")
        result = fal_client.subscribe(
            UPSCALE_ENDPOINT,
            arguments={
                "image_url":        image_url,
                "upscaling_factor": UPSCALE_SCALE,
                "overlapping_tiles": True,
                "checkpoint":       "v2",   # v1 or v2 — v2 is best for real photos
            }
        )

        upscaled_url = result.get("image", {}).get("url")
        if not upscaled_url:
            log.error(f"[Enhance] Upscale returned no URL. Result: {result}")
            return input_path

        # Download the upscaled image
        import requests
        resp = requests.get(upscaled_url, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)

        log.info(f"[Enhance] Upscaled image saved → {output_path}")
        return output_path

    except Exception as e:
        log.error(f"[Enhance] AI upscaling failed: {e}")
        return input_path


# ── Main public entry point ────────────────────────────────────────────────────

def enhance_image(
    input_path: str,
    output_path: str,
    do_lighting: bool = True,
    do_upscale: bool = True,
) -> str:
    """
    Full enhancement pipeline:
      1. Lighting / colour correction (local, fast)
      2. AI upscaling via fal.ai (remote, ~10-20s per image)

    Args:
        input_path:  Path to the source image.
        output_path: Desired path for the enhanced image.
        do_lighting: Run lighting correction (default True).
        do_upscale:  Run AI upscaling (default True).

    Returns:
        Path to the best available result (may be input_path if both stages fail).
    """
    if not os.path.exists(input_path):
        log.error(f"[Enhance] Input not found: {input_path}")
        return input_path

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    current = input_path

    # Stage 1 — Lighting
    if do_lighting:
        lit_path = output_path.replace(".jpg", "_lit.jpg").replace(".png", "_lit.png")
        current = correct_lighting(current, lit_path)

    # Stage 2 — Upscale
    if do_upscale:
        current = upscale_image(current, output_path)
    elif current != output_path:
        # No upscale requested but we may have a lit_path — copy it to final output
        import shutil
        shutil.copy2(current, output_path)
        current = output_path

    return current


# ── CLI helper for quick testing ───────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python image_enhance.py <input.jpg> <output.jpg>")
        sys.exit(1)
    result = enhance_image(sys.argv[1], sys.argv[2])
    print(f"Enhanced image saved to: {result}")
