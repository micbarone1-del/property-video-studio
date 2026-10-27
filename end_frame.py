"""First + last frame for Luma (2026-10-27): two equal-size crops of the same photo, each resized back to the photo's size.
See camera_plan.FRAME_PAIR. (The 2026-10-26 single end-frame crop looked like a zoom and was replaced.)"""
import io

import camera_plan


def make_frame_pair_bytes(image_bytes: bytes, movement: str):
    """(first_jpeg_bytes, last_jpeg_bytes), both the same pixel size as the photo, or None (no rule for this movement, or any problem)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        boxes = camera_plan.frame_pair_boxes(movement, img.width, img.height)
        if not boxes:
            return None
        out = []
        for box in boxes:
            buf = io.BytesIO()
            img.crop(box).resize(img.size, Image.LANCZOS).save(buf, format="JPEG", quality=92)
            out.append(buf.getvalue())
        return out[0], out[1]
    except Exception:
        return None
