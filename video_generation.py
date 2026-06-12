"""
video_generation.py  (real-estate edition)
────────────────────────────────────────────
Fixes applied vs. original:
  • generate_video_single() argument order was wrong in mass_generation() → fixed
  • output_path was undefined in mass_generation() → fixed
  • Vision model prompt now uses a strict, property-specific template (no hallucinations)
  • Empty vision result falls back to a safe property template prompt, not a generic one
  • duration snapping loop changed to a cleaner list-membership check
  • All exceptions are caught per-image, never crash the whole pipeline
"""

import os
import logging
import requests
import fal_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
DEFAULT_VIDEO_ENDPOINT  = "fal-ai/ltx-2.3/image-to-video/fast"
DEFAULT_VISION_ENDPOINT = "openrouter/router/vision"
DEFAULT_VISION_MODEL    = "google/gemini-2.5-flash"

# Durations the LTX model actually accepts
VALID_DURATIONS = [6, 8, 10, 12, 14, 16, 18, 20]

# ── Real-estate prompt template ────────────────────────────────────────────────
# The vision model is instructed to stay strictly within this frame.
# This replaces the original free-form prompt which caused hallucinations.

_VISION_SYSTEM_PROMPT = """\
You are a video-prompt writer for a real estate marketing company.
Your ONLY job is to write a short, precise prompt (max 25 words) for an \
image-to-video AI model.

STRICT RULES:
- Describe only what is physically visible in the image.
- Do NOT add people, animals, new furniture, or objects not in the image.
- Do NOT change the lighting style beyond what is already there.
- DO use slow cinematic camera moves: gentle pan, slow push-in, or subtle tilt.
- The output must be a single sentence. No preamble, no explanation.

Example outputs:
  "Slow cinematic push-in on a bright living room with large windows and hardwood floors."
  "Gentle pan across a modern kitchen with marble countertops and pendant lighting."
  "Subtle tilt-up revealing a sun-drenched master bedroom with neutral tones."
"""

_VISION_USER_PREFIX = (
    "Write a video generation prompt for this real estate photo. "
    "Follow the rules exactly."
)


def _snap_duration(d: int) -> int:
    """Snap requested duration to the nearest value the model accepts."""
    if d in VALID_DURATIONS:
        return d
    # Round up to next valid; cap at 20
    for v in VALID_DURATIONS:
        if v >= d:
            return v
    return VALID_DURATIONS[-1]


def _safe_property_fallback(hint: str = "") -> str:
    """Returns a safe, non-hallucinating fallback prompt."""
    base = "Slow cinematic push-in on a real estate interior, natural lighting, no people."
    if hint:
        return f"{base} Style note: {hint}."
    return base


# ── Core single-image function ─────────────────────────────────────────────────

def generate_video_single(
    image_path: str,
    output_path: str,
    duration: int = 8,
    prompt: str = "",
    model_endpoint: str = DEFAULT_VIDEO_ENDPOINT,
    test_mode: bool = False,
) -> bool:
    """
    Generates a single video clip from one image.

    Args:
        image_path:     Local path to the source image.
        output_path:    Where to save the resulting .mp4.
        duration:       Desired duration in seconds (snapped to model limits).
        prompt:         Optional user hint (style, room type, etc.).
        model_endpoint: fal.ai model string.
        test_mode:      If True, skips real API calls and downloads a sample video.

    Returns:
        True on success, False on failure.
    """
    if not os.path.exists(image_path):
        log.error(f"[VideoGen] Image not found: {image_path}")
        return False

    duration = _snap_duration(duration)

    try:
        if test_mode:
            sample_url = "https://v3b.fal.media/files/b/0a8866f6/dmGBclH_CBmaku8J31ZE8_output.mp4"
            log.info("[VideoGen] test_mode=True → downloading sample video.")
            return download_video(sample_url, output_path)

        # ── Step 1: Upload image ───────────────────────────────────────────
        log.info(f"[VideoGen] Uploading: {image_path}")
        image_url = fal_client.upload_file(image_path)

        # ── Step 2: Vision model → video prompt ───────────────────────────
        log.info("[VideoGen] Generating video prompt via vision model...")
        user_content = _VISION_USER_PREFIX
        if prompt:
            user_content += f"\nAdditional style instruction: {prompt}"

        vision_result = fal_client.subscribe(
            DEFAULT_VISION_ENDPOINT,
            arguments={
                "image_urls":   [image_url],
                "prompt":       user_content,
                "system_prompt": _VISION_SYSTEM_PROMPT,
                "model":        DEFAULT_VISION_MODEL,
            }
        )

        generated_prompt = (vision_result.get("output") or "").strip()
        log.info(f"[VideoGen] Generated prompt: \"{generated_prompt}\"")

        if not generated_prompt or len(generated_prompt) < 10:
            log.warning("[VideoGen] Vision model returned empty/short prompt → using safe fallback.")
            generated_prompt = _safe_property_fallback(prompt)

        # Basic sanity check: reject prompts that mention people
        bad_tokens = ["person", "people", "man ", "woman", "couple", "family", "walking", "sitting"]
        if any(t in generated_prompt.lower() for t in bad_tokens):
            log.warning("[VideoGen] Prompt mentions people → replacing with safe fallback.")
            generated_prompt = _safe_property_fallback(prompt)

        # ── Step 3: Video generation ───────────────────────────────────────
        log.info(f"[VideoGen] Generating video ({duration}s) via {model_endpoint}...")
        video_handler = fal_client.submit(
            model_endpoint,
            arguments={
                "image_url":    image_url,
                "prompt":       generated_prompt,
                "duration":     duration,
                "resolution":   "1080p",
                "aspect_ratio": "16:9",      # landscape for property listings
            }
        )
        result = video_handler.get()

        # ── Step 4: Download ───────────────────────────────────────────────
        video_url = (result.get("video") or {}).get("url")
        if not video_url:
            log.error(f"[VideoGen] No video URL in result: {result}")
            return False

        log.info("[VideoGen] Video generated — downloading...")
        return download_video(video_url, output_path)

    except Exception as e:
        log.error(f"[VideoGen] Error processing {image_path}: {e}", exc_info=True)
        return False


# ── Batch convenience wrapper ──────────────────────────────────────────────────

def mass_generation(
    image_dict: dict,
    output_dir: str,
    duration: int = 8,
    model_endpoint: str = DEFAULT_VIDEO_ENDPOINT,
    test_mode: bool = False,
) -> dict:
    """
    Batch-generate videos from a dict of {image_path: hint_or_None}.

    Args:
        image_dict:     { "path/to/image.jpg": "optional style hint" }
        output_dir:     Directory to save generated .mp4 files.
        duration:       Duration per clip in seconds.
        model_endpoint: fal.ai model string.
        test_mode:      Skip real API calls.

    Returns:
        { image_path: output_mp4_path_or_None }
    """
    if not os.environ.get("FAL_KEY"):
        log.critical("[VideoGen] FAL_KEY not set. Aborting batch generation.")
        return {}

    os.makedirs(output_dir, exist_ok=True)
    results = {}

    for image_path, hint in image_dict.items():
        base = os.path.splitext(os.path.basename(image_path))[0]
        out  = os.path.join(output_dir, f"{base}_video.mp4")
        ok   = generate_video_single(
            image_path=image_path,
            output_path=out,
            duration=duration,
            prompt=hint or "",
            model_endpoint=model_endpoint,
            test_mode=test_mode,
        )
        results[image_path] = out if ok else None

    return results


# ── Download helper ────────────────────────────────────────────────────────────

def download_video(url: str, output_path: str) -> bool:
    """Downloads a video from a URL and saves it to output_path."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info(f"[VideoGen] Saved to: {output_path}")
        return True
    except Exception as e:
        log.error(f"[VideoGen] Download failed: {e}")
        return False


# ── CLI quick test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python video_generation.py <image.jpg> <output.mp4> [hint]")
        sys.exit(1)
    hint = sys.argv[3] if len(sys.argv) > 3 else ""
    ok = generate_video_single(sys.argv[1], sys.argv[2], prompt=hint)
    sys.exit(0 if ok else 1)
