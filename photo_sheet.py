"""photo_sheet.py - contact sheet of ALL the photos of a relinx.it listing as the intake saw them, labelled with the intake's own verdict (2026-11-04).

Why: Michele wants to avoid skipping usable photos. e21367fe / e7f516e3 lost their only bedroom, bathrooms, kitchen and living to the 'soft' quality verdict, and many
photos are excluded as 'parti comuni dell'edificio' / 'ingresso o corridoio'. This shows every photo with that verdict so a person can say whether it was right.
No Claude, no spend, nothing is written into a job. Uses the SAME functions as relinx_pilot_check.py (page parsing, white-band rule) so the numbers match the job's photo_audit.

  python3 photo_sheet.py JOB_ID LISTING_URL [--only 5,10,12]   --only 5,10 or --only rejected (= the photos the quality filter threw out); URL optional (read from the draft): instead of thumbnails, ONE large image per listed photo (1400 px wide) plus a 1:1 crop of its centre at the
                                                          real pixels (the view the quality judge also gets), to judge sharpness on a tablet. JOB_ID = a draft of the test instance (/var/www/pvs_test_jobs); sheets go to jobs/_test_scratch/ (port 8000 serves them)
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


def listing_url(job: str) -> str:
    """The relinx.it listing page of a draft, read from its job_meta.json (first https://relinx.it/... string found)."""
    import re
    txt = (TEST_JOBS / job / "job_meta.json").read_text()
    m = re.search(r'https://relinx\.it/[^"\\ ]*?/immobili/[^"\\ ]+', txt) or re.search(r'https://relinx\.it/[^"\\ ]+', txt)
    if not m:
        raise SystemExit(f"no relinx.it url in {job}/job_meta.json: pass it as second argument")
    return m.group(0)


def rejected_indices(job: str) -> dict:
    """{photo index: quality verdict} of the photos the quality filter threw out (selection_report.quality_rejected)."""
    sr = json.loads((TEST_JOBS / job / "job_meta.json").read_text()).get("selection_report") or {}
    return {index_of(q.get("url")): q.get("verdict") for q in sr.get("quality_rejected") or [] if index_of(q.get("url")) is not None}


def big_views(job, kept, only):
    """Large image + 1:1 centre crop for each wanted photo index; returns the links."""
    from PIL import Image
    SCRATCH.mkdir(parents=True, exist_ok=True)
    links = []
    for n_out, (pos, im) in enumerate(kept):
        if n_out not in only:
            continue
        w, h = im.size
        big = im.copy(); big.thumbnail((1400, 1400))
        name = f"photos_{job}_{n_out}_big.jpg"; big.save(SCRATCH / name, quality=90)
        cw, ch = min(w, 1100), min(h, 700)
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        cname = f"photos_{job}_{n_out}_crop.jpg"; im.crop((x0, y0, x0 + cw, y0 + ch)).save(SCRATCH / cname, quality=92)
        fname = f"photos_{job}_{n_out}_full.jpg"; im.save(SCRATCH / fname, quality=95)
        links.append((n_out, f"{w}x{h}", f"{LINK_BASE}/{name}", f"{LINK_BASE}/{cname}", f"{LINK_BASE}/{fname}"))
    return links


def main(job, url, only=None):
    import requests
    from PIL import Image, ImageDraw, ImageFont
    import relinx_pilot_check as rp
    import listing_scraper
    page = requests.get(url, headers=rp.UA, timeout=60).text
    L = rp.parse_listing(page, url)
    imgs = [Image.open(io.BytesIO(requests.get("https://relinx.it" + rel, headers=rp.UA, timeout=60).content)).convert("RGB") for rel in L["photos"]]
    kept, info = rp.choose_clean_photos(imgs, listing_scraper.MIN_USABLE_PHOTOS)
    if only:
        v = verdicts(job); rej = rejected_indices(job)
        for n_out, size, big, crop, full in big_views(job, kept, only):
            print(f"#{n_out} ({size} px, label: {v.get(n_out, '?')}, quality verdict: {rej.get(n_out, '-')})\n   whole: {big}\n   1:1 crop: {crop}\n   FULL resolution: {full}")
        return 0
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
    a = sys.argv[1:]
    if "--only" in a:
        i = a.index("--only"); spec = a[i + 1]; del a[i:i + 2]
    else:
        spec = None
    if not a or len(a) > 2:
        print(__doc__); sys.exit(1)
    job = a[0]
    url = a[1] if len(a) == 2 else listing_url(job)
    only = (set(rejected_indices(job)) if spec == "rejected" else {int(x) for x in spec.split(",")}) if spec else None
    sys.exit(main(job, url, only))
