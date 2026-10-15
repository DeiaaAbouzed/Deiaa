"""Password-encrypted, streaming dataset archives (``.rushd`` files).

Format: MAGIC | salt(16) | nonce-prefix(4) | chunks...
Each chunk: length(4) | final-flag(1) | AES-256-GCM(ciphertext+tag).
The key comes from the export password via scrypt. Chunk nonces are a counter,
so chunks cannot be reordered, and the mandatory final chunk means a
truncated file is detected instead of silently yielding partial data.
"""

from __future__ import annotations

import io
import os
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"RUSHDX1\n"
CHUNK = 1 << 20


class ExportError(Exception):
    pass


def _key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


class EncryptingWriter(io.RawIOBase):
    def __init__(self, out: BinaryIO, password: str):
        super().__init__()
        salt = os.urandom(16)
        self._prefix = os.urandom(4)
        self._aead = AESGCM(_key(password, salt))
        self._out = out
        self._buf = bytearray()
        self._counter = 0
        out.write(MAGIC + salt + self._prefix)

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self._buf += data
        while len(self._buf) >= CHUNK:
            self._emit(bytes(self._buf[:CHUNK]), final=False)
            del self._buf[:CHUNK]
        return len(data)

    def _emit(self, data: bytes, final: bool) -> None:
        nonce = self._prefix + self._counter.to_bytes(8, "big")
        self._counter += 1
        sealed = self._aead.encrypt(nonce, data, b"final" if final else b"chunk")
        self._out.write(len(sealed).to_bytes(4, "big") + (b"\x01" if final else b"\x00") + sealed)

    def close(self) -> None:
        if not self.closed:
            self._emit(bytes(self._buf), final=True)
            self._buf.clear()
        super().close()


def decrypt_stream(src: BinaryIO, dst: BinaryIO, password: str) -> None:
    head = src.read(len(MAGIC) + 20)
    if len(head) != len(MAGIC) + 20 or not head.startswith(MAGIC):
        raise ExportError("ليس ملف تصدير صالح")
    salt, prefix = head[len(MAGIC) : len(MAGIC) + 16], head[len(MAGIC) + 16 :]
    aead = AESGCM(_key(password, salt))
    counter = 0
    while True:
        header = src.read(5)
        if len(header) < 5:
            raise ExportError("الملف ناقص (مقطوع)")
        size, final = int.from_bytes(header[:4], "big"), header[4] == 1
        sealed = src.read(size)
        if len(sealed) != size:
            raise ExportError("الملف ناقص (مقطوع)")
        try:
            dst.write(aead.decrypt(prefix + counter.to_bytes(8, "big"), sealed, b"final" if final else b"chunk"))
        except InvalidTag as exc:
            raise ExportError("كلمة المرور خاطئة أو الملف تم العبث به") from exc
        counter += 1
        if final:
            return


def encrypt_archive(data: bytes, password: str) -> bytes:
    """Convenience for small payloads (tests)."""
    out = io.BytesIO()
    writer = EncryptingWriter(out, password)
    writer.write(data)
    writer.close()
    return out.getvalue()
