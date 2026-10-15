from __future__ import annotations

import random
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Doctor, Prescription, QuizAttempt, User
from ..security.deps import (
    EVERYONE,
    MANAGERS,
    Principal,
    get_ctx,
    get_db,
    require_roles,
)
from ..services.academy import DIFFICULTY, progress_report, score
from ..services.csvsafe import to_csv
from .errors import ApiError

router = APIRouter(prefix="/api/academy", tags=["academy"])


class StartBody(BaseModel):
    difficulty: str = Field(default="any", pattern="^(any|easy|medium|hard)$")


class Answer(BaseModel):
    brand: str = Field(default="", max_length=120)
    strength: str = Field(default="", max_length=60)
    times_per_day: float | None = None


class SubmitBody(BaseModel):
    answers: list[Answer] = Field(max_length=30)


def _enabled(ctx, db: Session) -> None:
    if not ctx.store.get(db, "academy_enabled"):
        raise ApiError(403, "أكاديمية التدريب متوقفة حالياً")


def _attempt(db: Session, attempt_id: int, p: Principal) -> QuizAttempt:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != p.id:
        raise ApiError(404, "المحاولة غير موجودة")
    return attempt


@router.post("/start")
def start(
    body: StartBody,
    p: Principal = Depends(require_roles(*EVERYONE)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    _enabled(ctx, db)
    base = select(Prescription.id).where(Prescription.status == "verified", Prescription.academy_approved.is_(True))
    recent = select(QuizAttempt.prescription_id).where(
        QuizAttempt.user_id == p.id, QuizAttempt.started_at >= utcnow() - timedelta(days=30)
    )
    pools = []
    if body.difficulty in DIFFICULTY:
        pools.append(base.where(DIFFICULTY[body.difficulty]()).where(Prescription.id.not_in(recent)))
    pools += [base.where(Prescription.id.not_in(recent)), base]
    candidates: list[int] = []
    for stmt in pools:
        candidates = list(db.execute(stmt.limit(500)).scalars())
        if candidates:
            break
    if not candidates:
        raise ApiError(404, "لا توجد روشتات معتمدة للتدريب بعد - اطلب من المدرب اعتماد روشتات للأكاديمية")
    rx = db.get(Prescription, random.SystemRandom().choice(candidates))
    attempt = QuizAttempt(user_id=p.id, prescription_id=rx.id)
    db.add(attempt)
    db.commit()
    doctor = db.get(Doctor, rx.doctor_id) if rx.doctor_id else None
    return {
        "attempt_id": attempt.id,
        "items_count": rx.num_items,
        "specialty": doctor.specialty if doctor else None,
        "difficulty": "hard"
        if (rx.ai_confidence or 1) < 0.7
        else "medium"
        if (rx.ai_confidence or 1) < 0.9
        else "easy",
    }


@router.get("/attempts/{attempt_id}/image")
def attempt_image(
    attempt_id: int,
    p: Principal = Depends(require_roles(*EVERYONE)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    attempt = _attempt(db, attempt_id, p)
    rx = db.get(Prescription, attempt.prescription_id)
    if rx is None or not rx.academy_approved:
        raise ApiError(404, "غير متاح")
    return Response(ctx.blobs.get(rx.image_blob, "image"), media_type="image/jpeg")


@router.post("/attempts/{attempt_id}/submit")
def submit(
    attempt_id: int,
    body: SubmitBody,
    p: Principal = Depends(require_roles(*EVERYONE)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    attempt = _attempt(db, attempt_id, p)
    if attempt.submitted_at is not None:
        raise ApiError(409, "تم تسليم هذه المحاولة من قبل")
    rx = db.get(Prescription, attempt.prescription_id)
    truth = ctx.keyring.decrypt_json(rx.verified_result_enc, f"verified:{rx.uid}") or {}
    result = score(truth.get("items", []), [a.model_dump() for a in body.answers], ctx.lexicon.get())
    attempt.submitted_at = utcnow()
    attempt.score = result["score"]
    attempt.max_score = result["max_score"]
    attempt.details = {
        "percent": result["percent"],
        "seconds": int((attempt.submitted_at - attempt.started_at).total_seconds()),
    }
    db.commit()
    result["seconds"] = attempt.details["seconds"]
    return result


@router.get("/leaderboard")
def leaderboard(p: Principal = Depends(require_roles(*EVERYONE)), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=30)
    rows = db.execute(
        select(
            User.id,
            User.full_name,
            User.username,
            func.count(QuizAttempt.id),
            func.sum(QuizAttempt.score),
            func.sum(QuizAttempt.max_score),
        )
        .join(QuizAttempt, QuizAttempt.user_id == User.id)
        .where(QuizAttempt.submitted_at >= since)
        .group_by(User.id)
        .order_by(func.sum(QuizAttempt.score).desc())
        .limit(20)
    ).all()
    return [
        {
            "name": r.full_name or r.username,
            "attempts": r[3],
            "points": round(r[4] or 0, 1),
            "percent": round(100 * (r[4] or 0) / r[5], 1) if r[5] else 0.0,
            "me": r.id == p.id,
        }
        for r in rows
    ]


@router.get("/me")
def my_progress(p: Principal = Depends(require_roles(*EVERYONE)), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            select(QuizAttempt)
            .where(QuizAttempt.user_id == p.id, QuizAttempt.submitted_at.is_not(None))
            .order_by(QuizAttempt.id.desc())
            .limit(30)
        )
        .scalars()
        .all()
    )
    total = sum(a.score or 0 for a in rows)
    maximum = sum(a.max_score or 0 for a in rows)
    return {
        "attempts": len(rows),
        "percent": round(100 * total / maximum, 1) if maximum else None,
        "history": [
            {
                "id": a.id,
                "date": a.submitted_at.isoformat(),
                "percent": (a.details or {}).get("percent"),
                "seconds": (a.details or {}).get("seconds"),
            }
            for a in rows
        ],
    }


@router.get("/pool")
def pool(p: Principal = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    base = select(func.count(Prescription.id)).where(
        Prescription.status == "verified", Prescription.academy_approved.is_(True)
    )
    return {
        "total": db.execute(base).scalar_one(),
        **{level: db.execute(base.where(cond())).scalar_one() for level, cond in DIFFICULTY.items()},
    }


ROLE_NAMES = {"admin": "مدير", "trainer": "مدرب", "pharmacist": "صيدلي", "trainee": "متدرب"}
REPORT_HEADER = [
    "الاسم",
    "اسم الدخول",
    "الدور",
    "الفرع",
    "المحاولات",
    "متوسط الدرجة %",
    "التحسن (نقطة)",
    "محاولات الخطوط الصعبة",
    "درجة الخطوط الصعبة %",
    "دقائق التدريب",
    "آخر نشاط",
]


@router.get("/report")
def report(
    days: int = Query(default=30, ge=7, le=365),
    branch_id: int | None = None,
    p: Principal = Depends(require_roles(*MANAGERS)),
    db: Session = Depends(get_db),
):
    return progress_report(db, days, branch_id)


@router.get("/report.csv")
def report_csv(
    days: int = Query(default=30, ge=7, le=365),
    branch_id: int | None = None,
    p: Principal = Depends(require_roles(*MANAGERS)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    data = progress_report(db, days, branch_id)
    rows = (
        [
            r["name"],
            r["username"],
            ROLE_NAMES.get(r["role"], r["role"]),
            r["branch"],
            r["attempts"],
            r["percent"],
            r["improvement"],
            r["hard_attempts"],
            r["hard_percent"],
            r["minutes"],
            r["last_activity"][:10] if r["last_activity"] else None,
        ]
        for r in data["rows"]
    )
    ctx.audit.record(
        "academy_report_exported",
        user_id=p.id,
        username=p.user.username,
        ip=p.ip,
        details={"days": days, "branch_id": branch_id, "people": len(data["rows"])},
    )
    return Response(
        to_csv(REPORT_HEADER, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="academy-report-{utcnow():%Y%m%d}.csv"'},
    )
