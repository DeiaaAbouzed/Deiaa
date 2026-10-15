"""Time-based one-time passwords (Google Authenticator / Microsoft Authenticator)."""

from __future__ import annotations

import io
import time

import pyotp
import qrcode
import qrcode.image.svg

_STEP = 30


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg(uri: str) -> str:
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def verify_code(secret: str, code: str, last_step: int | None) -> int | None:
    """Return the matched time-step, or None.

    Accepts one step of clock drift either side, and refuses any step that is
    not newer than the last accepted one - a code can never be replayed.
    """
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(time.time()) // _STEP
    for step in (now_step - 1, now_step, now_step + 1):
        if last_step is not None and step <= last_step:
            continue
        if pyotp.utils.strings_equal(totp.at(step * _STEP), code):
            return step
    return None
