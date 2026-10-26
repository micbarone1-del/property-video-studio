"""End frame for Luma (2026-10-26): a crop of the start photo, resized back to the photo's size. See camera_plan.END_FRAME_CROP."""
import io

import camera_plan


def make_end_frame_bytes(image_bytes: bytes, movement: str):
    """JPEG bytes of the end frame (same pixel size as the start image), or None (no rule for this movement, or any problem)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        box = camera_plan.end_frame_box(movement, img.width, img.height)
        if not box:
            return None
        out = img.crop(box).resize(img.size, Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception:
        return None
