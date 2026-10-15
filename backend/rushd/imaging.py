"""Safe image intake.

Uploaded files are untrusted. Every image is fully decoded under strict
limits and re-encoded from raw pixels, which drops EXIF (GPS, device
serials), embedded payloads and polyglot tricks before anything is stored.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageRejected(ValueError):
    """Raised with an Arabic, user-facing message."""


@dataclass
class CleanImage:
    jpeg: bytes
    width: int
    height: int


def _decode(data: bytes, max_bytes: int, max_pixels: int) -> Image.Image:
    if not data:
        raise ImageRejected("الملف فارغ")
    if len(data) > max_bytes:
        raise ImageRejected(f"حجم الصورة أكبر من {max_bytes // (1024 * 1024)} ميجابايت")
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        # Image.open only parses the header, so the pixel-count check below runs
        # before any large allocation happens.
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ALLOWED_FORMATS:
            raise ImageRejected("صيغة غير مدعومة - استخدم JPG أو PNG أو WEBP")
        if probe.width * probe.height > max_pixels:
            raise ImageRejected("أبعاد الصورة كبيرة بشكل غير طبيعي")
        probe.verify()  # structural check of the whole file
        img = Image.open(io.BytesIO(data))
        img.load()
    except ImageRejected:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageRejected("أبعاد الصورة كبيرة بشكل غير طبيعي") from exc
    except UnidentifiedImageError as exc:
        raise ImageRejected("الملف ليس صورة صالحة") from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise ImageRejected("الصورة تالفة أو غير مكتملة") from exc
    if min(img.size) < 200:
        raise ImageRejected("دقة الصورة منخفضة جداً - صوّر الروشتة بوضوح أكبر")
    return img


def sanitize(
    data: bytes,
    *,
    max_bytes: int,
    max_pixels: int,
    max_edge: int,
    redactions: list[dict] | None = None,
    enhance: bool = False,
) -> CleanImage:
    img = _decode(data, max_bytes, max_pixels)
    img = ImageOps.exif_transpose(img)  # honour camera orientation, then forget EXIF
    try:
        if img.mode in ("RGBA", "LA", "PA", "P"):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", img.size, "white")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        img = img.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ImageRejected("نظام ألوان الصورة غير مدعوم") from exc
    if redactions:
        img = apply_redactions(img, redactions)
    if enhance:
        img = enhance_contrast(img)
    img = fit(img, max_edge)
    return CleanImage(jpeg=to_jpeg(img, quality=90), width=img.width, height=img.height)


def apply_redactions(img: Image.Image, boxes: list[dict]) -> Image.Image:
    """Black out regions given as fractions of the image (x, y, w, h in 0..1)."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for box in boxes[:20]:
        try:
            x, y, w, h = (float(box[k]) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        x0 = max(0.0, min(1.0, x)) * img.width
        y0 = max(0.0, min(1.0, y)) * img.height
        x1 = max(0.0, min(1.0, x + w)) * img.width
        y1 = max(0.0, min(1.0, y + h)) * img.height
        if x1 > x0 and y1 > y0:
            draw.rectangle([x0, y0, x1, y1], fill="black")
    return out


def enhance_contrast(img: Image.Image) -> Image.Image:
    """Lift faded ink: stretch contrast, then a light unsharp mask."""
    img = ImageOps.autocontrast(img, cutoff=1)
    return img.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))


def fit(img: Image.Image, max_edge: int) -> Image.Image:
    if max(img.size) <= max_edge:
        return img
    scale = max_edge / max(img.size)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)


def to_jpeg(img: Image.Image, quality: int = 88) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def open_jpeg(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


def resized_jpeg(data: bytes, max_edge: int, quality: int = 88) -> bytes:
    """Downscale a stored (already sanitised) JPEG, e.g. for the AI or thumbnails."""
    img = open_jpeg(data)
    if max(img.size) <= max_edge:
        return data
    return to_jpeg(fit(img, max_edge), quality=quality)
