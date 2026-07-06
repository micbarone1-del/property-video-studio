"""
Quick standalone test: Luma Ray 2 image-to-video on the same problematic
bathroom photo we've been testing depth rendering against, for a direct
comparison on hallucination/warping/movement quality.
"""
import sys
import time
import logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

import fal_client
import requests

LUMA_ENDPOINT = "fal-ai/luma-dream-machine/ray-2/image-to-video"


def test_luma(image_path: str, output_path: str, prompt: str, duration: str = "5s"):
    print(f"Uploading {image_path}...")
    image_url = fal_client.upload_file(image_path)

    print(f"Submitting to Luma Ray 2 (duration={duration})...")
    t0 = time.time()
    result = fal_client.subscribe(
        LUMA_ENDPOINT,
        arguments={
            "image_url": image_url,
            "prompt": prompt,
            "duration": duration,
            "resolution": "1080p",
            "aspect_ratio": "16:9",
            "loop": False,
        }
    )
    elapsed = time.time() - t0
    print(f"Completed in {elapsed:.1f}s")

    video_url = (result.get("video") or {}).get("url")
    if not video_url:
        print(f"NO VIDEO URL — full result: {result}")
        return False

    print(f"Downloading from {video_url}...")
    resp = requests.get(video_url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    print(f"Saved: {output_path}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 test_luma.py <image.jpg> <output.mp4> [prompt] [duration]")
        sys.exit(1)
    prompt = sys.argv[3] if len(sys.argv) > 3 else (
        "slow subtle camera movement, gentle push forward into the room, "
        "no people, camera stays within the visible space, realistic physics"
    )
    duration = sys.argv[4] if len(sys.argv) > 4 else "5s"
    ok = test_luma(sys.argv[1], sys.argv[2], prompt, duration)
    sys.exit(0 if ok else 1)
