"""Encrypted blob store for prescription images and model weights."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Blob
from .security.crypto import KeyRing


class BlobNotFound(Exception):
    pass


class BlobStore:
    def __init__(self, root: Path, keyring: KeyRing):
        self.root = root
        self._kr = keyring
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, blob_id: str) -> Path:
        if len(blob_id) != 32 or not all(c in "0123456789abcdef" for c in blob_id):
            raise BlobNotFound(blob_id)  # never let an id escape the store directory
        return self.root / blob_id[:2] / blob_id

    def put(self, db: Session, data: bytes, kind: str) -> str:
        blob_id = secrets.token_hex(16)
        path = self._path(blob_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        token = self._kr.encrypt_blob(data, f"{kind}:{blob_id}")
        tmp = path.with_suffix(".part")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(token)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        db.add(Blob(id=blob_id, kind=kind, size=len(data)))
        return blob_id

    def get(self, blob_id: str, kind: str) -> bytes:
        path = self._path(blob_id)
        if not path.exists():
            raise BlobNotFound(blob_id)
        return self._kr.decrypt_blob(path.read_bytes(), f"{kind}:{blob_id}")

    def delete(self, db: Session, blob_id: str | None) -> None:
        if not blob_id:
            return
        path = self._path(blob_id)
        if path.exists():
            # Overwrite before unlinking. On SSDs this is best-effort, but the
            # content is ciphertext anyway (crypto-shredding).
            size = path.stat().st_size
            with open(path, "r+b") as fh:
                fh.write(b"\0" * size)
                fh.flush()
                os.fsync(fh.fileno())
            path.unlink()
        blob = db.get(Blob, blob_id)
        if blob is not None:
            db.delete(blob)
