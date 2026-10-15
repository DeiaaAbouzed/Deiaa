from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.schema import Form as DoseForm
from ..ai.schema import Route, Timing, Unit
from ..db import utcnow
from ..imaging import ImageRejected
from ..models import Doctor, Prescription, QuizAttempt, User
from ..security.deps import (
    ADMIN,
    MANAGERS,
    STAFF,
    Principal,
    get_ctx,
    get_db,
    require_roles,
)
from ..services.intake import MB, find_duplicate, ingest_image
from ..services.verification import verify
from ..services.worker import PRIORITY_INTERACTIVE
from .errors import ApiError

router = APIRouter(prefix="/api/prescriptions", tags=["prescriptions"])


class VerifyItem(BaseModel):
    brand: str = Field(max_length=120)
    drug_id: int | None = None
    strength: str = Field(default="", max_length=60)
    form: DoseForm | None = None
    quantity: str = Field(default="", max_length=40)
    sig_text: str = Field(default="", max_length=200)
    line_text: str = Field(default="", max_length=300)
    dose_amount: float | None = None
    dose_unit: Unit | None = None
    times_per_day: float | None = None
    interval_hours: float | None = None
    timing: Timing | None = None
    duration_days: float | None = None
    route: Route | None = None
    prn: bool = False
    stat: bool = False
    ai_index: int | None = None


class VerifyDoctor(BaseModel):
    id: int | None = None
    name: str = Field(default="", max_length=160)
    specialty: str = Field(default="", max_length=120)
    clinic: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)


class VerifyPatient(BaseModel):
    name: str = Field(default="", max_length=120)
    age: str = Field(default="", max_length=20)


class VerifyBody(BaseModel):
    items: list[VerifyItem] = Field(max_length=30)
    doctor: VerifyDoctor | None = None
    patient: VerifyPatient | None = None
    notes: str = Field(default="", max_length=500)
    use_for_training: bool = True
    academy_approved: bool = False
    add_unknown_drugs: bool = True


class RejectBody(BaseModel):
    reason: str = Field(default="", max_length=200)


def load_rx(db: Session, uid: str, p: Principal) -> Prescription:
    rx = (
        db.execute(select(Prescription).where(Prescription.uid == uid)).scalar_one_or_none() if len(uid) == 32 else None
    )
    if rx is None:
        raise ApiError(404, "الروشتة غير موجودة")
    if p.role not in MANAGERS and rx.uploaded_by != p.id:
        raise ApiError(404, "الروشتة غير موجودة")  # do not reveal that it exists
    return rx


def summary(rx: Prescription, doctor_name: str | None, uploader: str | None) -> dict:
    return {
        "uid": rx.uid,
        "status": rx.status,
        "source": rx.source,
        "created_at": rx.created_at.isoformat(),
        "verified_at": rx.verified_at.isoformat() if rx.verified_at else None,
        "doctor": {"id": rx.doctor_id, "name": doctor_name} if rx.doctor_id else None,
        "num_items": rx.num_items,
        "ai_confidence": rx.ai_confidence,
        "acc_drug": rx.acc_drug,
        "uploaded_by": uploader,
        "batch_id": rx.batch_id,
        "error": rx.error,
        "engine": rx.engine,
    }


def _check_quota(db: Session, ctx, p: Principal) -> None:
    if not ctx.limiter.hit(f"read:{p.id}", 30, 60):
        raise ApiError(429, "عدد كبير من الطلبات في دقيقة واحدة، انتظر قليلاً", "rate_limited")
    limit = ctx.store.get(db, "reads_per_user_per_day")
    since = utcnow() - timedelta(days=1)
    used = db.execute(
        select(func.count(Prescription.id)).where(Prescription.uploaded_by == p.id, Prescription.created_at >= since)
    ).scalar_one()
    if used >= limit:
        raise ApiError(429, f"تم الوصول للحد اليومي ({limit} روشتة) لهذا المستخدم", "quota")


@router.post("", status_code=202)
def upload(
    image: UploadFile = File(...),
    redactions: str = Form(default="[]", max_length=4000),
    doctor_id: int | None = Form(default=None),
    enhance: bool = Form(default=False),
    p: Principal = Depends(require_roles(*STAFF)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    _check_quota(db, ctx, p)
    data = image.file.read(ctx.settings.max_upload_mb * MB + 1)
    try:
        boxes = json.loads(redactions or "[]")
        if not isinstance(boxes, list):
            raise ValueError
    except ValueError as exc:
        raise ApiError(400, "بيانات الإخفاء غير صالحة") from exc
    if doctor_id is not None and db.get(Doctor, doctor_id) is None:
        raise ApiError(400, "الطبيب المحدد غير موجود")

    duplicate = find_duplicate(db, ctx, data)
    if duplicate is not None and (p.role in MANAGERS or duplicate.uploaded_by == p.id):
        return {"uid": duplicate.uid, "status": duplicate.status, "duplicate": True}

    try:
        rx = ingest_image(
            db,
            ctx,
            data,
            user=p.user,
            source="read",
            priority=PRIORITY_INTERACTIVE,
            doctor_id=doctor_id,
            redactions=boxes,
            enhance=enhance,
        )
    except ImageRejected as exc:
        raise ApiError(400, str(exc), "bad_image") from exc
    db.commit()
    ctx.audit.record("prescription_uploaded", user_id=p.id, username=p.user.username, ip=p.ip, target=rx.uid)
    ctx.worker.submit(rx.id, PRIORITY_INTERACTIVE)
    db.refresh(rx)
    return {"uid": rx.uid, "status": rx.status, "duplicate": False}


@router.get("")
def list_prescriptions(
    status: str | None = Query(default=None, max_length=80),
    mine: bool = False,
    doctor_id: int | None = None,
    batch_id: int | None = None,
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=30, ge=1, le=100),
    p: Principal = Depends(require_roles(*STAFF)),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Prescription, Doctor.name, User.username)
        .join(User, User.id == Prescription.uploaded_by)
        .outerjoin(Doctor, Doctor.id == Prescription.doctor_id)
    )
    if mine or p.role not in MANAGERS:
        stmt = stmt.where(Prescription.uploaded_by == p.id)
    if status:
        stmt = stmt.where(Prescription.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    if doctor_id:
        stmt = stmt.where(Prescription.doctor_id == doctor_id)
    if batch_id:
        stmt = stmt.where(Prescription.batch_id == batch_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Prescription.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "items": [summary(rx, dn, un) for rx, dn, un in rows]}


@router.get("/{uid}")
def get_prescription(
    uid: str, p: Principal = Depends(require_roles(*STAFF)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    rx = load_rx(db, uid, p)
    doctor = db.get(Doctor, rx.doctor_id) if rx.doctor_id else None
    uploader = db.get(User, rx.uploaded_by)
    data = summary(rx, doctor.name if doctor else None, uploader.username if uploader else None)
    kr = ctx.keyring
    data["ai_result"] = kr.decrypt_json(rx.ai_result_enc, f"ai:{rx.uid}")
    data["verified_result"] = kr.decrypt_json(rx.verified_result_enc, f"verified:{rx.uid}")
    data["use_for_training"] = rx.use_for_training
    data["academy_approved"] = rx.academy_approved
    data["passes"] = rx.passes
    data["cost_usd"] = round(rx.cost_usd, 4) if p.role in MANAGERS else None
    data["can_verify"] = rx.status in ("needs_review", "verified", "rejected") and (
        p.role in MANAGERS or (rx.uploaded_by == p.id and rx.status != "verified")
    )
    if rx.uploaded_by != p.id and rx.status in ("needs_review", "verified"):
        ctx.audit.record("prescription_viewed", user_id=p.id, username=p.user.username, ip=p.ip, target=rx.uid)
    return data


@router.get("/{uid}/image")
def get_image(
    uid: str,
    variant: str = Query(default="full", pattern="^(full|thumb)$"),
    p: Principal = Depends(require_roles(*STAFF)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    rx = load_rx(db, uid, p)
    blob, kind = (rx.thumb_blob, "thumb") if variant == "thumb" else (rx.image_blob, "image")
    return Response(ctx.blobs.get(blob, kind), media_type="image/jpeg")


@router.post("/{uid}/verify")
def verify_prescription(
    uid: str,
    body: VerifyBody,
    p: Principal = Depends(require_roles(*STAFF)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    rx = load_rx(db, uid, p)
    if rx.status not in ("needs_review", "verified", "rejected"):
        raise ApiError(409, "لا يمكن اعتماد الروشتة قبل انتهاء القراءة")
    if rx.status == "verified" and p.role not in MANAGERS:
        raise ApiError(403, "تعديل روشتة معتمدة متاح للمدرب أو المدير فقط")
    result = verify(db, ctx, rx, body.model_dump(), p.user, p.ip, can_approve_academy=p.role in MANAGERS)
    return {"ok": True, "status": rx.status, "verified_result": result, "acc_drug": rx.acc_drug}


@router.post("/{uid}/reject")
def reject(
    uid: str,
    body: RejectBody,
    p: Principal = Depends(require_roles(*STAFF)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    rx = load_rx(db, uid, p)
    if rx.status in ("queued", "processing"):
        raise ApiError(409, "انتظر حتى تنتهي القراءة")
    if rx.status == "verified" and p.role not in MANAGERS:
        raise ApiError(403, "ليس لديك صلاحية")
    rx.status = "rejected"
    rx.error = body.reason[:400]
    rx.use_for_training = False
    rx.academy_approved = False
    db.commit()
    ctx.audit.record("prescription_rejected", user_id=p.id, username=p.user.username, ip=p.ip, target=rx.uid)
    return {"ok": True}


@router.post("/{uid}/retry")
def retry(uid: str, p: Principal = Depends(require_roles(*STAFF)), ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    rx = load_rx(db, uid, p)
    if rx.status not in ("failed", "needs_review", "rejected"):
        raise ApiError(409, "لا يمكن إعادة القراءة الآن")
    if rx.status in ("needs_review", "rejected"):
        _check_quota(db, ctx, p)
    rx.status = "queued"
    rx.error = ""
    db.commit()
    ctx.worker.submit(rx.id, PRIORITY_INTERACTIVE)
    db.refresh(rx)
    return {"uid": rx.uid, "status": rx.status}


@router.delete("/{uid}")
def delete(
    uid: str, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    rx = load_rx(db, uid, p)
    if rx.status in ("queued", "processing"):
        raise ApiError(409, "انتظر حتى تنتهي القراءة")
    for attempt in db.execute(select(QuizAttempt).where(QuizAttempt.prescription_id == rx.id)).scalars():
        db.delete(attempt)
    ctx.blobs.delete(db, rx.image_blob)
    ctx.blobs.delete(db, rx.thumb_blob)
    db.delete(rx)
    db.commit()
    ctx.audit.record("prescription_deleted", user_id=p.id, username=p.user.username, ip=p.ip, target=uid)
    return {"ok": True}
