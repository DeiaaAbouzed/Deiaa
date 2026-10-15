"""Turning uploaded files into stored, encrypted prescriptions."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..imaging import resized_jpeg, sanitize
from ..models import Prescription, User

MB = 1024 * 1024


def find_duplicate(db: Session, ctx, data: bytes) -> Prescription | None:
    mac = ctx.keyring.content_mac(data)
    return db.execute(
        select(Prescription).where(Prescription.image_mac == mac, Prescription.status != "failed").limit(1)
    ).scalar_one_or_none()


def ingest_image(
    db: Session,
    ctx,
    data: bytes,
    *,
    user: User,
    source: str,
    priority: int,
    doctor_id: int | None = None,
    redactions: list[dict] | None = None,
    enhance: bool = False,
    batch_id: int | None = None,
    status: str = "queued",
) -> Prescription:
    """Sanitise and store an image; raises imaging.ImageRejected with an Arabic message."""
    s = ctx.settings
    clean = sanitize(
        data,
        max_bytes=s.max_upload_mb * MB,
        max_pixels=s.max_image_pixels,
        max_edge=s.stored_image_max_edge,
        redactions=redactions,
        enhance=enhance,
    )
    written: list[str] = []
    try:
        image_blob = ctx.blobs.put(db, clean.jpeg, "image")
        written.append(image_blob)
        thumb_blob = ctx.blobs.put(db, resized_jpeg(clean.jpeg, 480, quality=80), "thumb")
        written.append(thumb_blob)
        rx = Prescription(
            uid=secrets.token_hex(16),
            status=status,
            source=source,
            priority=priority,
            branch_id=user.branch_id,
            uploaded_by=user.id,
            batch_id=batch_id,
            doctor_id=doctor_id,
            doctor_confirmed=doctor_id is not None,
            image_blob=image_blob,
            thumb_blob=thumb_blob,
            image_mac=ctx.keyring.content_mac(data),
            width=clean.width,
            height=clean.height,
        )
        db.add(rx)
        db.flush()
        return rx
    except Exception:
        for blob_id in written:
            ctx.blobs.delete(db, blob_id)
        raise
