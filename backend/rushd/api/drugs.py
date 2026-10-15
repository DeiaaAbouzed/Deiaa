from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..ai import memory
from ..ai.text import norm
from ..db import utcnow
from ..models import Drug
from ..security.deps import MANAGERS, STAFF, Principal, get_ctx, get_db, require_roles
from ..services import drugs as drug_service
from .errors import ApiError

router = APIRouter(prefix="/api/drugs", tags=["drugs"])


class DrugBody(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    generic: str = Field(default="", max_length=240)
    drug_class: str = Field(default="", max_length=80)
    forms: list[str] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=40)


def as_dict(d: Drug) -> dict:
    return {
        "id": d.id,
        "brand": d.brand,
        "generic": d.generic,
        "drug_class": d.drug_class,
        "forms": d.forms or [],
        "strengths": d.strengths or [],
        "aliases": d.aliases or [],
        "is_generic": d.is_generic,
        "source": d.source,
        "is_active": d.is_active,
    }


@router.get("")
def list_drugs(
    q: str = Query(default="", max_length=80),
    source: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=50, ge=1, le=200),
    p: Principal = Depends(require_roles(*STAFF)),
    db: Session = Depends(get_db),
):
    stmt = select(Drug).where(Drug.is_active.is_(True))
    if q.strip():
        generic = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(
            or_(
                Drug.brand_norm.like(f"%{norm(q)}%"),
                func.lower(Drug.generic).like(f"%{generic}%", escape="\\"),
                cast(Drug.aliases, String).like(f"%{generic}%", escape="\\"),
            )
        )
    if source:
        stmt = stmt.where(Drug.source == source)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Drug.brand).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {"total": total, "items": [as_dict(d) for d in rows]}


@router.get("/suggest")
def suggest(
    q: str = Query(min_length=1, max_length=80),
    doctor_id: int | None = None,
    p: Principal = Depends(require_roles(*STAFF)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    lexicon = ctx.lexicon.get()
    counts = memory.doctor_drug_counts(db, doctor_id)
    return [
        c.as_dict() | {"strengths": list(c.drug.strengths), "forms": list(c.drug.forms)}
        for c in lexicon.match(q, limit=8, doctor_counts=counts)
    ]


@router.post("", status_code=201)
def create_drug(
    body: DrugBody,
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    if db.execute(select(Drug.id).where(Drug.brand_norm == norm(body.brand), Drug.is_active.is_(True))).first():
        raise ApiError(409, "هذا الدواء موجود بالفعل")
    drug, _ = drug_service.upsert(db, body.model_dump() | {"class": body.drug_class}, "user")
    if drug is None:
        raise ApiError(400, "اسم الدواء غير صالح")
    db.commit()
    ctx.drugs_changed()
    ctx.audit.record("drug_created", user_id=p.id, username=p.user.username, ip=p.ip, target=drug.brand)
    return as_dict(drug)


@router.put("/{drug_id}")
def update_drug(
    drug_id: int,
    body: DrugBody,
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    drug = db.get(Drug, drug_id)
    if drug is None:
        raise ApiError(404, "الدواء غير موجود")
    new_norm = norm(body.brand)
    clash = db.execute(select(Drug.id).where(Drug.brand_norm == new_norm, Drug.id != drug_id)).first()
    if clash:
        raise ApiError(409, "يوجد دواء آخر بنفس الاسم")
    drug.brand, drug.brand_norm = body.brand.strip(), new_norm
    drug.generic, drug.drug_class = body.generic.strip(), body.drug_class.strip()
    drug.forms, drug.strengths, drug.aliases = body.forms, body.strengths, body.aliases
    drug.updated_at = utcnow()
    if drug.source == "learned":
        drug.source = "user"  # a reviewed learned drug becomes a regular entry
    db.commit()
    ctx.drugs_changed()
    ctx.audit.record("drug_updated", user_id=p.id, username=p.user.username, ip=p.ip, target=drug.brand)
    return as_dict(drug)


@router.delete("/{drug_id}")
def deactivate_drug(
    drug_id: int, p: Principal = Depends(require_roles(*MANAGERS)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    drug = db.get(Drug, drug_id)
    if drug is None:
        raise ApiError(404, "الدواء غير موجود")
    drug.is_active = False
    db.commit()
    ctx.drugs_changed()
    ctx.audit.record("drug_deactivated", user_id=p.id, username=p.user.username, ip=p.ip, target=drug.brand)
    return {"ok": True}


@router.post("/import")
def import_drugs(
    file: UploadFile = File(...),
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    raw = file.file.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise ApiError(413, "ملف كبير جداً")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(400, "يجب حفظ الملف بترميز UTF-8") from exc
    try:
        result = drug_service.import_csv(db, text, source="import")
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    db.commit()
    ctx.drugs_changed()
    ctx.audit.record("drugs_imported", user_id=p.id, username=p.user.username, ip=p.ip, details=result)
    return result


@router.get("/export")
def export_drugs(p: Principal = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    csv_text = drug_service.export_csv(db)
    return Response(
        "﻿" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rushd-drugs.csv"'},
    )
