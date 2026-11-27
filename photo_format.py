"""photo_format.py -- the ONE place that cuts a photo to the shape of the video (2026-11-12, moved out of api_server.py WITHOUT changing a line of its logic).
Why: the photo SELECTION (listing_scraper.rank_photos_by_quality) judged the whole photo, while the video used the cut one: on listing 105 a portrait
bathroom became a band of bare wall. Both now call this same function, so the photo that is judged is the photo that is used."""


# 2026-11-17 (Relinx feedback: white band at the top of every video): Relinx pads its photos to one uniform format, so the band is PART of the photo
# we receive and passes the 2 % tolerance below (the padded photo is already 16:9). The border is cut here, ONE place, before the crop: the photo
# that is judged (listing_scraper ranking), the photo that is used and the format vote all see the same trimmed picture.
# A border is: touching the edge, white (mean >= BORDER_WHITE_MIN), uniform (std <= BORDER_STD_MAX), at least BORDER_MIN_PX thick, ending in a sharp
# step to the content (BORDER_STEP_MIN), and never thicker than BORDER_MAX_FRAC of that dimension (25 %: a 4:3 photo padded to 16:9 has 12.5 % bars per side; a real white ceiling is not eaten by the other conditions).
BORDER_WHITE_MIN = 244.0
BORDER_STD_MAX = 6.0
BORDER_MIN_PX = 3
BORDER_STEP_MIN = 8.0
BORDER_MAX_FRAC = 0.25


def _edge_trim(lines, cap: int) -> int:
    """How many lines (rows or columns, counted from the edge: lines[0] is the outermost) belong to a white padding border. 0 = none."""
    k = 0
    n = len(lines)
    while k < min(cap, n) and lines[k].mean() >= BORDER_WHITE_MIN and lines[k].std() <= BORDER_STD_MAX:
        k += 1
    if k < BORDER_MIN_PX or k >= n:
        return 0
    if abs(lines[k] - lines[k - 1]).mean() < BORDER_STEP_MIN:
        return 0
    return k


def border_box(img) -> tuple:
    """(left, top, right, bottom) of the photo without its white padding border; the whole image when there is none."""
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=float)
    h, w = gray.shape
    capv, caph = int(h * BORDER_MAX_FRAC), int(w * BORDER_MAX_FRAC)
    top = _edge_trim(gray, capv)
    bottom = _edge_trim(gray[::-1], capv)
    left = _edge_trim(gray.T, caph)
    right = _edge_trim(gray.T[::-1], caph)
    return (left, top, w - right, h - bottom)


def open_upright(image_bytes: bytes):
    """2026-11-27: the ONE place a photo is opened for the video. Returns (image, changed). The image has its EXIF orientation applied (a phone portrait is stored
    sideways plus a tag; before this the tag was ignored and a bathroom reached Luma lying on its side, job 575efc11) and no alpha / palette mode (a PNG with
    transparency could not be written as JPEG: 'cannot write mode RGBA as JPEG', HTTP 500 on upload, 2026-11-27). Transparent pixels become white.
    changed = the pixels differ from the file, so the original bytes must not be reused as they are."""
    from PIL import Image, ImageOps
    import io
    img = Image.open(io.BytesIO(image_bytes))
    changed = False
    if img.getexif().get(274, 1) in (2, 3, 4, 5, 6, 7, 8):
        img = ImageOps.exif_transpose(img)
        changed = True
    if img.mode not in ("RGB", "L"):
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        else:
            img = img.convert("RGB")
        changed = True
    return img, changed


def trimmed_size(image_bytes: bytes) -> tuple:
    """(width, height) of the photo once its white border is cut: what the landscape / portrait vote must look at."""
    img, _ = open_upright(image_bytes)
    l, t, r, b = border_box(img)
    return (r - l, b - t)


def normalize_photo_to_format(image_bytes: bytes, target_format: str) -> bytes:
    """
    Crops a photo to match the job's chosen canonical output format --
    "landscape" (16:9) or "portrait" (9:16) -- so every photo in a job
    ends up exactly the same shape before generation, and video_assembly.py
    can use one fixed canvas per job matching that format (2026-07-17,
    per explicit product decision after a real client portrait-photo
    distortion issue -- forcing every clip through a hardcoded 16:9
    canvas was stretching portrait footage).

    Crop direction depends on which way the source differs from target:
      - Source is taller/narrower than target (needs height cropped,
        e.g. a portrait photo going into a landscape job): TOP-BIASED
        crop, not centered -- confirmed via a real side-by-side test
        against an actual client photo that starting the crop window
        ~15% down from the top keeps more of the informative ceiling/
        window content real estate portrait shots are usually framed
        for, cropping more from the floor instead.
      - Source is wider than target (needs width cropped, e.g. a
        landscape photo going into a portrait job): plain CENTER crop --
        no equivalent left/right framing bias for typical room photos.
    """
    import io
    img, changed = open_upright(image_bytes)
    box = border_box(img)
    trimmed = box != (0, 0) + img.size
    if trimmed:
        img = img.crop(box)
    w, h = img.size
    target_ratio = (16 / 9) if target_format == "landscape" else (9 / 16)
    current_ratio = w / h

    # a trimmed photo is always cut to the exact shape (a 2 % mismatch would be stretched by the assembly); an untouched one keeps the old tolerance
    if abs(current_ratio - target_ratio) / target_ratio < (0.002 if trimmed else 0.02):
        if not trimmed and not changed:
            return image_bytes  # already an effective match, don't bother cropping
        buf = io.BytesIO(); img.save(buf, format='JPEG', quality=95)
        return buf.getvalue()

    if current_ratio < target_ratio:
        new_h = min(int(w / target_ratio), h)
        top = int((h - new_h) * 0.26)  # 2026-07-17: proportional to actual crop amount, not a fixed % of original height
        top = max(0, min(top, h - new_h))
        cropped = img.crop((0, top, w, top + new_h))
    else:
        new_w = min(int(h * target_ratio), w)
        left = (w - new_w) // 2
        cropped = img.crop((left, 0, left + new_w, h))

    buf = io.BytesIO()
    cropped.save(buf, format='JPEG', quality=95)
    return buf.getvalue()

