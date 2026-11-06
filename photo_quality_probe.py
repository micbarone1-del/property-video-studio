"""photo_quality_probe.py URL -- READ-ONLY diagnosis of why a relinx.it listing loses photos to the quality filter (2026-11-02, GIAL 1273/1279: 9 photos
"discarded for insufficient image quality"). Same steps as relinx_pilot_check (page -> photos -> white-band rule -> JPEG 95), then the production judge
(listing_scraper.assess_photo_quality) on each kept photo. Prints one line per photo: size on the page, size after the band rule, verdict, each judge, blockiness.
Writes nothing in any job. Cost: a few cents of Claude per photo (max 14 photos). Usage (venv): python3 photo_quality_probe.py URL
"""
import io
import sys

import requests
from PIL import Image

import relinx_pilot_check as rp
import listing_scraper as ls
import photo_metrics as pm

MAX_PHOTOS = 14


def main(url):
    page = requests.get(url, headers=rp.UA, timeout=40).text
    L = rp.parse_listing(page, url)
    print(f"listing {L['id']}: {len(L['photos'])} photos on the page, probing the first {MAX_PHOTOS}")
    imgs = [Image.open(io.BytesIO(requests.get("https://relinx.it" + rel, headers=rp.UA, timeout=60).content)).convert("RGB") for rel in L["photos"][:MAX_PHOTOS]]
    kept, info = rp.choose_clean_photos(imgs, ls.MIN_USABLE_PHOTOS)
    print(f"band rule: {info['mode']}; banded: {len(info['banded'])} of {len(imgs)}")
    poor = 0
    for pos, im in kept:
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=95)
        r = ls.assess_photo_quality(buf.getvalue(), f"probe {L['id']} #{pos}")
        poor += r["verdict"] in ls.PHOTO_QUALITY_POOR
        rq = pm.relative_quality_of_bytes(buf.getvalue())     # 2026-11-06: scale-free measures next to the verdicts (measurement only)
        print(f"  #{pos:02d} page {imgs[pos].size} -> kept {im.size} | verdict {r['verdict']} | judges {r.get('by_model')} | blockiness {r.get('blockiness')} | fine_mid {rq.get('fine_mid')} period {rq.get('period')}(k{rq.get('period_k')})")
    print(f"POOR: {poor} of {len(kept)}")


if __name__ == "__main__":
    main(sys.argv[1])
