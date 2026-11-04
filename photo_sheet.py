"""photo_sheet.py - contact sheet of ALL the photos of a relinx.it listing as the intake saw them, labelled with the intake's own verdict (2026-11-04).

Why: Michele wants to avoid skipping usable photos. e21367fe / e7f516e3 lost their only bedroom, bathrooms, kitchen and living to the 'soft' quality verdict, and many
photos are excluded as 'parti comuni dell'edificio' / 'ingresso o corridoio'. This shows every photo with that verdict so a person can say whether it was right.
No Claude, no spend, nothing is written into a job. Uses the SAME functions as relinx_pilot_check.py (page parsing, white-band rule) so the numbers match the job's photo_audit.

  python3 photo_sheet.py JOB_ID LISTING_URL            JOB_ID = a draft of the test instance (/var/www/pvs_test_jobs); sheets go to jobs/_test_scratch/ (port 8000 serves them)
"""
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST_JOBS = Path(os.environ.get("PVS_TEST_JOBS", "/var/www/pvs_test_jobs"))
SCRATCH = Path(os.environ.get("PVS_VOLUME_SCRATCH") or (HERE / "jobs" / "_test_scratch"))
LINK_BASE = os.environ.get("PVS_LINK_BASE", "http://187.77.196.94:8000/test-scratch")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PER_SHEET, COLS, TW, TH = 12, 4, 420, 300


def index_of(url: str):
    """The photo number of an audit url ('http://127.0.0.1:37697/1201/020.jpg?u=..' -> 20)."""
    m = re.search(r"/(\d{3})\.jpg", url or "")
    return int(m.group(1)) if m else None


def verdicts(job: str) -> dict:
    """{photo index: 'category | USED or excluded reason'} from the job's own photo_audit and selection."""
    meta = json.loads((TEST_JOBS / job / "job_meta.json").read_text())
    sr = meta.get("selection_report") or {}
    used = {index_of(p.get("url")) for ph in (sr.get("selected") or {}).values() for p in ph}
    out = {}
    for a in sr.get("photo_audit") or []:
        i = index_of(a.get("url"))
        if i is None:
            continue
        why = a.get("excluded") or ("USATA" if i in used else "ok, non scelta")
        out[i] = f"{a.get('category') or '?'} | {why}"
    return out


def main(job, url):
    import requests
    from PIL import Image, ImageDraw, ImageFont
    import relinx_pilot_check as rp
    import listing_scraper
    page = requests.get(url, headers=rp.UA, timeout=60).text
    L = rp.parse_listing(page, url)
    imgs = [Image.open(io.BytesIO(requests.get("https://relinx.it" + rel, headers=rp.UA, timeout=60).content)).convert("RGB") for rel in L["photos"]]
    kept, info = rp.choose_clean_photos(imgs, listing_scraper.MIN_USABLE_PHOTOS)
    thumbs = []
    for n_out, (pos, im) in enumerate(kept):
        t = im.copy(); t.thumbnail((TW, TH)); thumbs.append((n_out, t)); 
    del imgs, kept
    v = verdicts(job)
    font = ImageFont.truetype(FONT, 17) if Path(FONT).exists() else ImageFont.load_default()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    links = []
    for k in range(0, len(thumbs), PER_SHEET):
        chunk = thumbs[k:k + PER_SHEET]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new("RGB", (COLS * TW, rows * (TH + 54)), "white")
        d = ImageDraw.Draw(sheet)
        for j, (n_out, t) in enumerate(chunk):
            x, y = (j % COLS) * TW, (j // COLS) * (TH + 54)
            sheet.paste(t, (x, y))
            txt = v.get(n_out, "?")
            col = (180, 0, 0) if "USATA" not in txt and "ok," not in txt else (0, 120, 0)
            d.text((x + 4, y + TH + 2), f"#{n_out}", fill="black", font=font)
            d.text((x + 4, y + TH + 24), txt[:44], fill=col, font=font)
        name = f"photos_{job}_{k // PER_SHEET}.jpg"
        sheet.save(SCRATCH / name, quality=88)
        links.append(f"{LINK_BASE}/{name}")
    print(f"{job}: {len(thumbs)} photos ({info.get('mode')}), {len(links)} sheet(s):")
    for l in links:
        print("  ", l)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
