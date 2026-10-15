from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..ai import memory
from ..models import Correction, Doctor, DoctorDrugStat, Drug, Prescription
from ..security.deps import MANAGERS, STAFF, Principal, get_ctx, get_db, require_roles
from .errors import ApiError

router = APIRouter(prefix="/api/doctors", tags=["doctors"])


class DoctorBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    specialty: str = Field(default="", max_length=120)
    clinic: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=1000)


class MergeBody(BaseModel):
    into_id: int


def _accuracy(db: Session, doctor_ids: list[int]) -> dict[int, float]:
    if not doctor_ids:
        return {}
    rows = db.execute(
        select(Prescription.doctor_id, func.avg(Prescription.acc_drug))
        .where(Prescription.doctor_id.in_(doctor_ids), Prescription.acc_drug.is_not(None))
        .group_by(Prescription.doctor_id)
    )
    return {doctor_id: round(avg, 3) for doctor_id, avg in rows if avg is not None}


def as_dict(d: Doctor, accuracy: float | None = None) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "specialty": d.specialty,
        "clinic": d.clinic,
        "phone": d.phone,
        "notes": d.notes,
        "verified_count": d.verified_count,
        "accuracy": accuracy,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
    }


@router.get("")
def list_doctors(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=50, ge=1, le=500),
    p: Principal = Depends(require_roles(*STAFF)),
    db: Session = Depends(get_db),
):
    stmt = select(Doctor)
    key = memory.doctor_key(q)
    if key:
        stmt = stmt.where(Doctor.name_norm.like(f"%{key}%"))
    rows = db.execute(stmt.order_by(Doctor.verified_count.desc(), Doctor.name).limit(limit)).scalars().all()
    acc = _accuracy(db, [d.id for d in rows])
    return [as_dict(d, acc.get(d.id)) for d in rows]


@router.get("/{doctor_id}")
def get_doctor(doctor_id: int, p: Principal = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise ApiError(404, "الطبيب غير موجود")
    top = db.execute(
        select(Drug.brand, DoctorDrugStat.count)
        .join(Drug, Drug.id == DoctorDrugStat.drug_id)
        .where(DoctorDrugStat.doctor_id == doctor_id)
        .order_by(DoctorDrugStat.count.desc())
        .limit(15)
    ).all()
    learned = db.execute(select(func.count(Correction.id)).where(Correction.scope == f"d{doctor_id}")).scalar_one()
    data = as_dict(doctor, _accuracy(db, [doctor_id]).get(doctor_id))
    data["top_drugs"] = [{"brand": b, "count": c} for b, c in top]
    data["learned_corrections"] = learned
    return data


@router.post("", status_code=201)
def create_doctor(
    body: DoctorBody, p: Principal = Depends(require_roles(*STAFF)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    doctor = memory.find_or_create_doctor(db, body.name, body.specialty, body.clinic, body.phone)
    db.commit()
    ctx.audit.record("doctor_saved", user_id=p.id, username=p.user.username, ip=p.ip, target=str(doctor.id))
    return as_dict(doctor)


@router.put("/{doctor_id}")
def update_doctor(
    doctor_id: int,
    body: DoctorBody,
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise ApiError(404, "الطبيب غير موجود")
    doctor.name, doctor.name_norm = body.name.strip(), memory.doctor_key(body.name)
    doctor.specialty, doctor.clinic, doctor.phone, doctor.notes = body.specialty, body.clinic, body.phone, body.notes
    db.commit()
    ctx.audit.record("doctor_updated", user_id=p.id, username=p.user.username, ip=p.ip, target=str(doctor.id))
    return as_dict(doctor)


@router.post("/{doctor_id}/merge")
def merge_doctor(
    doctor_id: int,
    body: MergeBody,
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    """Fold a duplicate doctor profile into another one, keeping everything learned."""
    source, target = db.get(Doctor, doctor_id), db.get(Doctor, body.into_id)
    if source is None or target is None or source.id == target.id:
        raise ApiError(400, "اختيار غير صالح للدمج")
    db.execute(update(Prescription).where(Prescription.doctor_id == source.id).values(doctor_id=target.id))
    for stat in db.execute(select(DoctorDrugStat).where(DoctorDrugStat.doctor_id == source.id)).scalars().all():
        existing = db.get(DoctorDrugStat, (target.id, stat.drug_id))
        if existing:
            existing.count += stat.count
        else:
            db.add(DoctorDrugStat(doctor_id=target.id, drug_id=stat.drug_id, count=stat.count, last_at=stat.last_at))
        db.delete(stat)
    for corr in db.execute(select(Correction).where(Correction.scope == f"d{source.id}")).scalars().all():
        existing = db.execute(
            select(Correction).where(
                Correction.scope == f"d{target.id}",
                Correction.wrong_norm == corr.wrong_norm,
                Correction.right_text == corr.right_text,
            )
        ).scalar_one_or_none()
        if existing:
            existing.count += corr.count
            db.delete(corr)
        else:
            corr.scope = f"d{target.id}"
    target.verified_count += source.verified_count
    target.specialty = target.specialty or source.specialty
    target.clinic = target.clinic or source.clinic
    target.phone = target.phone or source.phone
    db.flush()
    db.delete(source)
    db.commit()
    ctx.audit.record(
        "doctor_merged", user_id=p.id, username=p.user.username, ip=p.ip, target=f"{doctor_id}->{body.into_id}"
    )
    return as_dict(target)
