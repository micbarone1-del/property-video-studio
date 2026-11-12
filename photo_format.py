"""photo_format.py -- the ONE place that cuts a photo to the shape of the video (2026-11-12, moved out of api_server.py WITHOUT changing a line of its logic).
Why: the photo SELECTION (listing_scraper.rank_photos_by_quality) judged the whole photo, while the video used the cut one: on listing 105 a portrait
bathroom became a band of bare wall. Both now call this same function, so the photo that is judged is the photo that is used."""


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
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    target_ratio = (16 / 9) if target_format == "landscape" else (9 / 16)
    current_ratio = w / h

    if abs(current_ratio - target_ratio) / target_ratio < 0.02:
        return image_bytes  # already an effective match, don't bother cropping

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

