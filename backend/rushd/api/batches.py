"""Bulk feeding: many prescriptions at once, pre-read by the AI, then reviewed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..imaging import ImageRejected
from ..models import Batch, Prescription, User
from ..security.deps import MANAGERS, STAFF, Principal, get_ctx, get_db, require_roles
from ..services import importer
from ..services.importer import Archive, ArchiveRejected, new_batch
from ..services.intake import MB, find_duplicate, ingest_image
from ..services.worker import PRIORITY_BULK
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["batches"])


@router.post("/batches", status_code=202)
def upload_batch(
    files: list[UploadFile] = File(...),
    name: str = Form(default="", max_length=160),
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    if len(files) > ctx.settings.max_batch_files:
        raise ApiError(400, f"الحد الأقصى {ctx.settings.max_batch_files} صورة في الدفعة الواحدة")
    batch = new_batch(db, name, "prelabel", p.id)
    accepted: list[int] = []
    rejected: list[dict] = []
    for upload in files:
        data = upload.file.read(ctx.settings.max_upload_mb * MB + 1)
        label = (upload.filename or "")[:120]
        if find_duplicate(db, ctx, data) is not None:
            rejected.append({"file": label, "error": "مرفوعة من قبل"})
            continue
        try:
            rx = ingest_image(db, ctx, data, user=p.user, source="bulk", priority=PRIORITY_BULK, batch_id=batch.id)
        except ImageRejected as exc:
            rejected.append({"file": label, "error": str(exc)})
            continue
        accepted.append(rx.id)
    batch.total = len(accepted)
    db.commit()
    ctx.audit.record(
        "batch_uploaded",
        user_id=p.id,
        username=p.user.username,
        ip=p.ip,
        target=str(batch.id),
        details={"accepted": len(accepted), "rejected": len(rejected)},
    )
    for rx_id in accepted:
        ctx.worker.submit(rx_id, PRIORITY_BULK)
    return {"batch_id": batch.id, "accepted": len(accepted), "rejected": rejected}


@router.post("/batches/import", status_code=201)
def import_archive(
    archive: UploadFile = File(...),
    name: str = Form(default="", max_length=160),
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    data = archive.file.read(ctx.settings.max_bulk_body_mb * MB + 1)
    try:
        zipped = Archive(data, ctx.settings.max_upload_mb * MB)
        batch = new_batch(db, name or (archive.filename or ""), "import", p.id)
        outcome = importer.import_archive(db, ctx, zipped, user=p.user, batch_id=batch.id)
    except ArchiveRejected as exc:
        db.rollback()
        raise ApiError(400, str(exc)) from exc
    batch.total = outcome.verified + len(outcome.queued)
    db.commit()
    ctx.audit.record(
        "archive_imported",
        user_id=p.id,
        username=p.user.username,
        ip=p.ip,
        target=str(batch.id),
        details={"verified": outcome.verified, "queued": len(outcome.queued), "problems": len(outcome.problems)},
    )
    for rx_id in outcome.queued:
        ctx.worker.submit(rx_id, PRIORITY_BULK)
    return {
        "batch_id": batch.id,
        "verified": outcome.verified,
        "queued": len(outcome.queued),
        "problems": outcome.problems[:200],
    }


@router.get("/batches")
def list_batches(p: Principal = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    counts = {}
    status_cols = ("queued", "processing", "needs_review", "verified", "rejected", "failed")
    stmt = (
        select(
            Prescription.batch_id,
            *[func.sum(case((Prescription.status == s, 1), else_=0)).label(s) for s in status_cols],
        )
        .where(Prescription.batch_id.is_not(None))
        .group_by(Prescription.batch_id)
    )
    for row in db.execute(stmt):
        counts[row.batch_id] = {s: int(getattr(row, s) or 0) for s in status_cols}
    rows = db.execute(
        select(Batch, User.username).join(User, User.id == Batch.created_by).order_by(Batch.id.desc()).limit(100)
    )
    return [
        {
            "id": b.id,
            "name": b.name,
            "kind": b.kind,
            "created_at": b.created_at.isoformat(),
            "created_by": username,
            "total": b.total,
            "counts": counts.get(b.id, {s: 0 for s in status_cols}),
        }
        for b, username in rows
    ]


@router.get("/review/next")
def next_for_review(
    batch_id: int | None = None,
    after: str | None = Query(default=None, max_length=32),
    p: Principal = Depends(require_roles(*STAFF)),
    db: Session = Depends(get_db),
):
    stmt = select(Prescription.uid, Prescription.id).where(Prescription.status == "needs_review")
    if p.role not in MANAGERS:
        stmt = stmt.where(Prescription.uploaded_by == p.id)
    if batch_id:
        stmt = stmt.where(Prescription.batch_id == batch_id)
    if after:
        current = db.execute(select(Prescription.id).where(Prescription.uid == after)).scalar_one_or_none()
        if current:
            stmt = stmt.where(Prescription.id > current)
    row = db.execute(stmt.order_by(Prescription.id).limit(1)).first()
    remaining = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    return {"uid": row.uid if row else None, "remaining": remaining}
