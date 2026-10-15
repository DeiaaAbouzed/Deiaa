from __future__ import annotations

import json
import os
import tempfile
import zipfile

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..db import utcnow
from ..models import ModelVersion, Prescription, TrainingJob
from ..security.deps import ADMIN, MANAGERS, Principal, get_ctx, get_db, require_roles
from ..services import stats
from ..services.accounts import verify_step_up
from ..training.export import EncryptingWriter
from .errors import ApiError

router = APIRouter(prefix="/api/training", tags=["training"])

MIN_TRAINING_SAMPLES = 50


class StepUp(BaseModel):
    password: str = Field(max_length=256)
    totp: str | None = Field(default=None, max_length=12)


class JobBody(StepUp):
    epochs: int = Field(default=3, ge=1, le=20)
    base_model: str | None = Field(default=None, max_length=160)
    learning_rate: float = Field(default=2e-4, gt=0, le=0.01)
    max_samples: int | None = Field(default=None, ge=10, le=100_000)


class ExportBody(StepUp):
    export_password: str = Field(min_length=12, max_length=256)


def job_dict(job: TrainingJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "progress": round(job.progress, 3),
        "message": job.message,
        "params": {k: v for k, v in (job.params or {}).items()},
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "model_version_id": job.model_version_id,
        "log_tail": job.log_tail[-2000:] if job.log_tail else "",
    }


def model_dict(m: ModelVersion) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "base_model": m.base_model,
        "status": m.status,
        "metrics": m.metrics,
        "train_count": m.train_count,
        "eval_count": m.eval_count,
        "is_active": m.is_active,
        "created_at": m.created_at.isoformat(),
        "activated_at": m.activated_at.isoformat() if m.activated_at else None,
    }


@router.get("/overview")
def overview(p: Principal = Depends(require_roles(*MANAGERS)), ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    return stats.overview(db, ctx)


@router.get("/readiness")
def readiness(p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    info = ctx.trainer.readiness()
    info["samples"] = (
        db.query(Prescription)
        .filter(Prescription.status == "verified", Prescription.use_for_training.is_(True))
        .count()
    )
    info["min_samples"] = MIN_TRAINING_SAMPLES
    info["base_model"] = ctx.settings.local_base_model
    info["running_job"] = ctx.trainer.running_job()
    return info


@router.get("/jobs")
def list_jobs(p: Principal = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    return [job_dict(j) for j in db.execute(select(TrainingJob).order_by(TrainingJob.id.desc()).limit(20)).scalars()]


@router.post("/jobs", status_code=201)
def start_job(
    body: JobBody, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    verify_step_up(db, ctx, p.user, body.password, body.totp, p.ip)
    if ctx.trainer.running_job() is not None:
        raise ApiError(409, "يوجد تدريب قيد التشغيل بالفعل")
    samples = (
        db.query(Prescription)
        .filter(Prescription.status == "verified", Prescription.use_for_training.is_(True))
        .count()
    )
    if samples < MIN_TRAINING_SAMPLES:
        raise ApiError(400, f"تحتاج {MIN_TRAINING_SAMPLES} روشتة معتمدة على الأقل للتدريب (المتاح الآن {samples})")
    if not ctx.trainer.readiness().get("ready"):
        raise ApiError(400, "مكتبات التدريب غير مثبتة على الخادم - راجع دليل التدريب (requirements-train.txt)")
    params = {
        "epochs": body.epochs,
        "base_model": body.base_model or ctx.settings.local_base_model,
        "learning_rate": body.learning_rate,
        "max_samples": body.max_samples,
    }
    job = TrainingJob(created_by=p.id, params=params, message="في الانتظار")
    db.add(job)
    db.commit()
    ctx.trainer.start(job.id)
    ctx.audit.record(
        "training_started", user_id=p.id, username=p.user.username, ip=p.ip, target=str(job.id), details=params
    )
    return job_dict(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: int, p: Principal = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    job = db.get(TrainingJob, job_id)
    if job is None:
        raise ApiError(404, "غير موجود")
    return job_dict(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx)):
    ctx.trainer.cancel(job_id)
    ctx.audit.record("training_cancelled", user_id=p.id, username=p.user.username, ip=p.ip, target=str(job_id))
    return {"ok": True}


@router.get("/models")
def list_models(p: Principal = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    return [model_dict(m) for m in db.execute(select(ModelVersion).order_by(ModelVersion.id.desc())).scalars()]


@router.post("/models/{model_id}/activate")
def activate_model(
    model_id: int,
    body: StepUp,
    p: Principal = Depends(require_roles(*ADMIN)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    verify_step_up(db, ctx, p.user, body.password, body.totp, p.ip)
    model = db.get(ModelVersion, model_id)
    if model is None or model.status != "ready":
        raise ApiError(404, "النموذج غير موجود")
    db.execute(update(ModelVersion).values(is_active=False))
    model.is_active = True
    model.activated_at = utcnow()
    db.commit()
    if ctx.local is not None:
        ctx.local.refresh()
    ctx.audit.record("model_activated", user_id=p.id, username=p.user.username, ip=p.ip, target=model.name)
    return model_dict(model)


@router.post("/models/deactivate")
def deactivate_models(
    body: StepUp, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    verify_step_up(db, ctx, p.user, body.password, body.totp, p.ip)
    db.execute(update(ModelVersion).values(is_active=False))
    db.commit()
    if ctx.local is not None:
        ctx.local.refresh()
    ctx.audit.record("model_deactivated", user_id=p.id, username=p.user.username, ip=p.ip)
    return {"ok": True}


@router.post("/export")
def export_dataset(
    body: ExportBody, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    """Password-encrypted dataset for training on an external GPU machine.

    Streamed straight into an encrypted temporary file, so neither memory nor
    disk ever holds the plain archive. Patient details are not exported.
    """
    verify_step_up(db, ctx, p.user, body.password, body.totp, p.ip)
    rows = (
        db.execute(
            select(Prescription)
            .where(Prescription.status == "verified", Prescription.use_for_training.is_(True))
            .order_by(Prescription.id)
        )
        .scalars()
        .all()
    )
    if not rows:
        raise ApiError(400, "لا توجد روشتات معتمدة للتصدير")
    tmp_dir = ctx.settings.data_dir / "tmp"
    tmp_dir.mkdir(mode=0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=tmp_dir, suffix=".rushd")
    try:
        with os.fdopen(fd, "wb") as out:
            writer = EncryptingWriter(out, body.export_password)
            with zipfile.ZipFile(writer, "w", zipfile.ZIP_STORED) as zf:
                lines = []
                for rx in rows:
                    result = ctx.keyring.decrypt_json(rx.verified_result_enc, f"verified:{rx.uid}") or {}
                    zf.writestr(f"images/{rx.uid}.jpg", ctx.blobs.get(rx.image_blob, "image"))
                    items = [
                        {k: item.get(k) for k in ("brand", "strength", "form", "sig_text", "line_text")}
                        for item in result.get("items", [])
                    ]
                    lines.append(
                        json.dumps(
                            {"file": f"{rx.uid}.jpg", "doctor": result.get("doctor") or {}, "items": items},
                            ensure_ascii=False,
                        )
                    )
                zf.writestr("labels.jsonl", "\n".join(lines))
            writer.close()
    except Exception:
        os.unlink(path)
        raise
    ctx.audit.record("dataset_exported", user_id=p.id, username=p.user.username, ip=p.ip, details={"count": len(rows)})
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"rushd-dataset-{utcnow():%Y%m%d}.rushd",
        background=BackgroundTask(os.unlink, path),
    )
