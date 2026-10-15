"""Numbers for the training-center dashboard."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Correction, Doctor, Drug, ModelVersion, Prescription
from .reader import month_spend, month_start


def _avg_acc(db: Session, start, end) -> tuple[float | None, int]:
    row = db.execute(
        select(func.avg(Prescription.acc_drug), func.count(Prescription.id)).where(
            Prescription.acc_drug.is_not(None), Prescription.verified_at >= start, Prescription.verified_at < end
        )
    ).one()
    return (round(row[0], 4) if row[0] is not None else None), int(row[1])


def overview(db: Session, ctx) -> dict:
    now = utcnow()
    statuses = ("queued", "processing", "needs_review", "verified", "rejected", "failed")
    row = db.execute(
        select(*[func.sum(case((Prescription.status == s, 1), else_=0)) for s in statuses], func.count(Prescription.id))
    ).one()
    counts = {s: int(v or 0) for s, v in zip(statuses, row[:-1])}
    counts["total"] = int(row[-1] or 0)
    counts["training_ready"] = db.execute(
        select(func.count(Prescription.id)).where(
            Prescription.status == "verified", Prescription.use_for_training.is_(True)
        )
    ).scalar_one()
    counts["verified_7d"] = db.execute(
        select(func.count(Prescription.id)).where(Prescription.verified_at >= now - timedelta(days=7))
    ).scalar_one()

    acc_30, n_30 = _avg_acc(db, now - timedelta(days=30), now)
    acc_prev, n_prev = _avg_acc(db, now - timedelta(days=60), now - timedelta(days=30))

    # Weekly learning curve for the last 12 weeks (oldest first).
    curve = []
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(11, -1, -1):
        start = week_start - timedelta(weeks=i)
        acc, n = _avg_acc(db, start, start + timedelta(weeks=1))
        curve.append({"week": start.date().isoformat(), "accuracy": acc, "count": n})

    doctors = db.execute(
        select(Doctor.id, Doctor.name, Doctor.specialty, Doctor.verified_count, func.avg(Prescription.acc_drug))
        .outerjoin(Prescription, (Prescription.doctor_id == Doctor.id) & Prescription.acc_drug.is_not(None))
        .where(Doctor.verified_count > 0)
        .group_by(Doctor.id)
        .order_by(Doctor.verified_count.desc())
        .limit(10)
    ).all()

    reads_month = db.execute(
        select(func.count(Prescription.id)).where(Prescription.created_at >= month_start(), Prescription.cost_usd > 0)
    ).scalar_one()
    spend = month_spend(db)
    cfg = ctx.store.all(db)
    active = db.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True))).scalar_one_or_none()
    shadow = db.execute(
        select(func.avg(Prescription.shadow_acc_drug), func.count(Prescription.id)).where(
            Prescription.shadow_acc_drug.is_not(None)
        )
    ).one()
    return {
        "counts": counts,
        "accuracy": {"last_30d": acc_30, "n_30d": n_30, "previous_30d": acc_prev, "n_prev": n_prev},
        "curve": curve,
        "doctors": [
            {
                "id": r.id,
                "name": r.name,
                "specialty": r.specialty,
                "verified": r.verified_count,
                "accuracy": round(r[4], 3) if r[4] is not None else None,
            }
            for r in doctors
        ],
        "learning": {
            "doctors_known": db.execute(select(func.count(Doctor.id)).where(Doctor.verified_count > 0)).scalar_one(),
            "corrections": db.execute(select(func.count(Correction.id))).scalar_one(),
            "drugs": db.execute(select(func.count(Drug.id)).where(Drug.is_active.is_(True))).scalar_one(),
            "drugs_learned": db.execute(
                select(func.count(Drug.id)).where(Drug.source == "learned", Drug.is_active.is_(True))
            ).scalar_one(),
        },
        "cost": {
            "month_usd": round(spend, 4),
            "reads_month": reads_month,
            "avg_per_read": round(spend / reads_month, 4) if reads_month else None,
            "budget_usd": cfg["monthly_budget_usd"],
        },
        "engine": {
            "mode": cfg["engine_mode"],
            "model": cfg["ai_model"],
            "effort": cfg["ai_effort"],
            "cloud_ready": ctx.claude.available and cfg["cloud_enabled"],
            "local_model": {"id": active.id, "name": active.name, "metrics": active.metrics} if active else None,
            "shadow_accuracy": round(shadow[0], 3) if shadow[0] is not None else None,
            "shadow_n": int(shadow[1] or 0),
        },
    }
