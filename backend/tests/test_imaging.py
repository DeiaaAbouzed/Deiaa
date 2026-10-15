import io

import pytest
from PIL import Image

from rushd.imaging import ImageRejected, sanitize

from .conftest import prescription_image

LIMITS = dict(max_bytes=15 * 1024 * 1024, max_pixels=50_000_000, max_edge=3000)


def test_reencodes_and_strips_metadata():
    img = Image.open(io.BytesIO(prescription_image()))
    exif = Image.Exif()
    exif[0x8825] = {2: (30.0, 2.0, 0.0)}  # GPS info
    exif[0x010F] = "PhoneMaker"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    assert b"PhoneMaker" in buf.getvalue()
    clean = sanitize(buf.getvalue(), **LIMITS)
    out = Image.open(io.BytesIO(clean.jpeg))
    assert out.format == "JPEG"
    assert not out.getexif()
    assert b"PhoneMaker" not in clean.jpeg


def test_rejects_non_images():
    with pytest.raises(ImageRejected):
        sanitize(b"%PDF-1.7 not an image", **LIMITS)
    with pytest.raises(ImageRejected):
        sanitize(b"<svg onload=alert(1)></svg>", **LIMITS)
    with pytest.raises(ImageRejected):
        sanitize(b"", **LIMITS)


def test_rejects_unsupported_format():
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), "white").save(buf, format="GIF")
    with pytest.raises(ImageRejected):
        sanitize(buf.getvalue(), **LIMITS)


def test_rejects_truncated_file():
    data = prescription_image()
    with pytest.raises(ImageRejected):
        sanitize(data[: len(data) // 2], **LIMITS)


def test_rejects_too_small_and_too_large():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    with pytest.raises(ImageRejected):
        sanitize(buf.getvalue(), **LIMITS)
    with pytest.raises(ImageRejected):
        sanitize(prescription_image(), max_bytes=1000, max_pixels=50_000_000, max_edge=3000)
    with pytest.raises(ImageRejected):
        sanitize(prescription_image(size=(3000, 3000), fmt="PNG"), max_bytes=10**8, max_pixels=1_000_000, max_edge=3000)


def test_downscales_and_converts_png_with_alpha():
    img = Image.new("RGBA", (4000, 1000), (255, 255, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    clean = sanitize(buf.getvalue(), **LIMITS)
    assert max(clean.width, clean.height) == 3000


def test_redaction_blacks_out_region():
    clean = sanitize(prescription_image(), redactions=[{"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.1}], **LIMITS)
    img = Image.open(io.BytesIO(clean.jpeg)).convert("L")
    assert img.getpixel((10, 10)) < 30  # covered
    assert img.getpixel((img.width - 10, img.height - 10)) > 200  # untouched


def test_redaction_ignores_garbage():
    clean = sanitize(prescription_image(), redactions=[{"x": "a"}, {"x": 2, "y": 2, "w": 1, "h": 1}, "nope"], **LIMITS)
    assert clean.width > 0
