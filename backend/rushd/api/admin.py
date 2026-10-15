"""Audit log, runtime settings and system information."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..models import AuditLog, ModelVersion
from ..security.deps import ADMIN, STAFF, Principal, get_ctx, get_db, require_roles
from ..services.reader import month_spend
from ..services.settings_store import EFFORTS, ENGINE_MODES
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["admin"])


class SettingsBody(BaseModel):
    changes: dict


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system/info")
def system_info(p: Principal = Depends(require_roles(*STAFF)), ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    cfg = ctx.store.all(db)
    active = db.execute(select(ModelVersion.name).where(ModelVersion.is_active.is_(True))).scalar_one_or_none()
    return {
        "version": __version__,
        "engine_mode": cfg["engine_mode"],
        "cloud_ready": bool(ctx.claude.available and cfg["cloud_enabled"]),
        "local_model": active,
        "queue": ctx.worker.pending() if ctx.worker else 0,
    }


@router.get("/audit")
def audit_log(
    page: int = Query(default=1, ge=1, le=100_000),
    action: str | None = Query(default=None, max_length=64),
    username: str | None = Query(default=None, max_length=64),
    p: Principal = Depends(require_roles(*ADMIN)),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if username:
        stmt = stmt.where(AuditLog.username == username)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * 50).limit(50)).scalars()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "ts": r.ts.isoformat(),
                "username": r.username,
                "action": r.action,
                "target": r.target,
                "ip": r.ip,
                "details": r.details,
            }
            for r in rows
        ],
    }


@router.post("/audit/verify")
def verify_audit(p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    result = ctx.audit.verify(db)
    ctx.audit.record("audit_verified", user_id=p.id, username=p.user.username, ip=p.ip, details={"ok": result.ok})
    return {"ok": result.ok, "checked": result.checked, "broken_at": result.broken_at, "reason": result.reason}


@router.get("/settings")
def get_settings(p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    return {
        "values": ctx.store.all(db),
        "options": {"engine_modes": ENGINE_MODES, "models": ctx.store.models, "efforts": EFFORTS},
        "status": {
            "cloud_key_configured": ctx.claude.available,
            "local_model_active": db.execute(select(ModelVersion.id).where(ModelVersion.is_active.is_(True))).first()
            is not None,
            "key_fingerprint": ctx.keyring.fingerprint,
            "month_spend_usd": round(month_spend(db), 4),
            "cookie_secure": ctx.settings.cookie_secure,
            "require_2fa_for_admins": ctx.settings.require_2fa_for_admins,
        },
    }


@router.put("/settings")
def update_settings(
    body: SettingsBody,
    p: Principal = Depends(require_roles(*ADMIN)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    try:
        changed = ctx.store.update(db, body.changes, p.id)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    db.commit()
    ctx.audit.record("settings_changed", user_id=p.id, username=p.user.username, ip=p.ip, details=changed)
    return {"values": ctx.store.all(db)}
