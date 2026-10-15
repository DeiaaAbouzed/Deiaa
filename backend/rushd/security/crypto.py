"""Encryption at rest and keyed integrity.

A single 256-bit master key (kept *outside* the data directory) is expanded
with HKDF into independent sub-keys:

* blob key   - AES-256-GCM for prescription images and model weights
* field key  - AES-256-GCM for readings / TOTP secrets stored in the database
* mac key    - HMAC-SHA256 for duplicate detection without storing plain hashes
* audit key  - HMAC-SHA256 for the tamper-evident audit chain
* token key  - HMAC-SHA256 for short-lived signed tokens

Every ciphertext is bound to its owner through AES-GCM associated data, so an
attacker with database write access cannot swap one patient's encrypted
reading or image for another's without detection.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_VERSION = b"\x01"
_NONCE_LEN = 12


class CryptoError(Exception):
    pass


def _derive(master: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"rushd/v1", info=info).derive(master)


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class KeyRing:
    def __init__(self, master_key: bytes):
        if len(master_key) != 32:
            raise CryptoError("master key must be exactly 32 bytes")
        self._blob = AESGCM(_derive(master_key, b"blob-encryption"))
        self._field = AESGCM(_derive(master_key, b"field-encryption"))
        self._mac_key = _derive(master_key, b"content-mac")
        self._audit_key = _derive(master_key, b"audit-chain")
        self._token_key = _derive(master_key, b"signed-tokens")
        self.fingerprint = hashlib.sha256(_derive(master_key, b"fingerprint")).hexdigest()[:16]

    # -- AEAD ----------------------------------------------------------------
    @staticmethod
    def _seal(aead: AESGCM, data: bytes, aad: str) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        return _VERSION + nonce + aead.encrypt(nonce, data, aad.encode())

    @staticmethod
    def _open(aead: AESGCM, token: bytes, aad: str) -> bytes:
        if not token or token[:1] != _VERSION or len(token) < 1 + _NONCE_LEN + 16:
            raise CryptoError("unknown ciphertext format")
        nonce = token[1 : 1 + _NONCE_LEN]
        try:
            return aead.decrypt(nonce, token[1 + _NONCE_LEN :], aad.encode())
        except InvalidTag as exc:  # wrong key, tampered data, or swapped record
            raise CryptoError("integrity check failed") from exc

    def encrypt_blob(self, data: bytes, aad: str) -> bytes:
        return self._seal(self._blob, data, aad)

    def decrypt_blob(self, token: bytes, aad: str) -> bytes:
        return self._open(self._blob, token, aad)

    def encrypt_field(self, data: bytes, aad: str) -> bytes:
        return self._seal(self._field, data, aad)

    def decrypt_field(self, token: bytes, aad: str) -> bytes:
        return self._open(self._field, token, aad)

    def encrypt_json(self, obj, aad: str) -> bytes:
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
        return self.encrypt_field(raw, aad)

    def decrypt_json(self, token: bytes | None, aad: str):
        if token is None:
            return None
        return json.loads(self.decrypt_field(token, aad))

    # -- MACs ----------------------------------------------------------------
    def content_mac(self, data: bytes) -> str:
        return hmac.new(self._mac_key, data, hashlib.sha256).hexdigest()

    def audit_mac(self, data: bytes) -> str:
        return hmac.new(self._audit_key, data, hashlib.sha256).hexdigest()

    # -- signed tokens -------------------------------------------------------
    def sign_token(self, payload: dict, ttl_seconds: int) -> str:
        body = dict(payload, exp=int(time.time()) + ttl_seconds, n=secrets.token_hex(4))
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        sig = hmac.new(self._token_key, raw, hashlib.sha256).digest()
        return f"{_b64e(raw)}.{_b64e(sig)}"

    def verify_token(self, token: str) -> dict | None:
        try:
            raw_b64, sig_b64 = token.split(".", 1)
            raw = _b64d(raw_b64)
            expected = hmac.new(self._token_key, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _b64d(sig_b64)):
                return None
            body = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(body, dict) or body.get("exp", 0) < time.time():
            return None
        return body


# -- master key handling -------------------------------------------------------


def generate_master_key_file(path: Path) -> bytes:
    """Create a new master key file readable only by its owner (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(_b64e(key) + "\n")
    return key


def parse_master_key(text: str) -> bytes:
    try:
        key = _b64d(text.strip())
    except ValueError as exc:
        raise CryptoError("master key is not valid base64") from exc
    if len(key) != 32:
        raise CryptoError("master key must decode to 32 bytes")
    return key


def load_master_key(path: Path, inline: str | None = None) -> bytes:
    if inline:
        return parse_master_key(inline)
    if not path.exists():
        raise CryptoError(
            f"master key not found at {path}. Run `python -m rushd init` first (or set RUSHD_MASTER_KEY_FILE)."
        )
    mode = path.stat().st_mode & 0o777
    if os.name == "posix" and mode & 0o077:
        raise CryptoError(f"master key file {path} must not be readable by other users (chmod 600)")
    return parse_master_key(path.read_text())
