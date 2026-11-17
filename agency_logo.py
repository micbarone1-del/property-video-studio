"""agency_logo.py -- the ONE place that turns a logo image into the agency logo file (2026-11-17, Relinx sends agency_logo_url with the job).
Shared by the manual upload (POST /agencies/{id}/logo) and the partner intake, so the two cannot drift apart.
- store_logo_png(): writes clients/<agency_id>/logo.png and records it with cost_model.set_agency_logo (what the video assembly reads).
- prepare_partner_logo(): a partner logo is often an opaque JPEG with a white background (Relinx: 472x461 JPEG, no alpha). The assembly pastes the logo
  as a brand mark, so a white square would show on the video. The WHITE BACKGROUND connected to the picture edge becomes transparent (flood fill from the
  corners); white inside the logo itself (letters, enclosed shapes) is kept. A logo whose corners are not white is left as it is.
- fetch_logo_bytes(): downloads the URL the partner sent: https only, a public address only (no localhost / private network), no redirects, small size."""
import io
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

MAX_LOGO_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT_S = 10
WHITE_MIN = 235            # a corner counts as white background from this level on (every channel)
FILL_TOLERANCE = 60        # flood-fill tolerance (sum of the channel differences from the corner colour)


class LogoError(Exception):
    """A reason safe to log and to show the operator."""


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    addrs = {i[4][0] for i in infos}
    return bool(addrs) and all(ipaddress.ip_address(a).is_global for a in addrs)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch_logo_bytes(url: str) -> bytes:
    u = urllib.parse.urlparse(str(url or "").strip())
    if u.scheme != "https" or not u.hostname:
        raise LogoError("logo URL is not https")
    if not _public_host(u.hostname):
        raise LogoError("logo host is not a public address")
    req = urllib.request.Request(u.geturl(), headers={"User-Agent": "property-video-studio"})
    try:
        r = urllib.request.build_opener(_NoRedirect).open(req, timeout=FETCH_TIMEOUT_S)
    except urllib.error.HTTPError as e:
        raise LogoError(f"logo download HTTP {e.code}")
    except Exception as e:
        raise LogoError(f"logo download failed ({type(e).__name__})")
    ctype = (r.headers.get("Content-Type") or "").lower()
    if not ctype.startswith("image/"):
        raise LogoError(f"logo is not an image ({ctype or 'no content type'})")
    data = r.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise LogoError("logo file is too large")
    return data


def has_real_alpha(img) -> bool:
    if img.mode not in ("RGBA", "LA") and "transparency" not in img.info:
        return False
    a = img.convert("RGBA").getchannel("A")
    return a.getextrema()[0] < 250


def key_white_background(img):
    """Returns (RGBA image, keyed). keyed False = the corners are not white, nothing was changed."""
    from PIL import ImageDraw
    rgba = img.convert("RGBA")
    w, h = rgba.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    if not all(min(rgba.getpixel(c)[:3]) >= WHITE_MIN for c in corners):
        return rgba, False
    for c in corners:
        if rgba.getpixel(c)[3] != 0:
            ImageDraw.floodfill(rgba, c, (255, 255, 255, 0), thresh=FILL_TOLERANCE)
    return rgba, True


def prepare_partner_logo(content: bytes):
    """(RGBA image, note). Raises LogoError for a file that is not a usable image."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        raise LogoError("logo is not a readable image")
    if min(img.size) < 32:
        raise LogoError("logo is too small")
    if has_real_alpha(img):
        return img.convert("RGBA"), "alpha kept"
    out, keyed = key_white_background(img)
    return out, ("white background made transparent" if keyed else "opaque logo kept as it is (background is not white)")


def store_logo_png(agency_id: str, img, base_dir) -> str:
    """Writes the agency logo file and records its path. ONE implementation for the upload endpoint and the partner intake."""
    import cost_model
    from pathlib import Path
    logos_dir = Path(base_dir) / "clients" / agency_id
    logos_dir.mkdir(parents=True, exist_ok=True)
    logo_path = logos_dir / "logo.png"
    img.convert("RGBA").save(logo_path, format="PNG")
    cost_model.set_agency_logo(agency_id, str(logo_path))
    return str(logo_path)


def update_from_partner_url(agency_id: str, url: str, base_dir) -> dict:
    """The partner intake call. Never raises: {"ok", "note"}; a failure leaves the agency's current logo untouched."""
    try:
        img, note = prepare_partner_logo(fetch_logo_bytes(url))
        store_logo_png(agency_id, img, base_dir)
        return {"ok": True, "note": note}
    except LogoError as e:
        return {"ok": False, "note": str(e)}
    except Exception as e:
        return {"ok": False, "note": f"logo not updated ({type(e).__name__})"}
