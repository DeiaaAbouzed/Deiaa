from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Branch, UserSession
from ..security import totp
from ..security.deps import (
    Principal,
    check_same_origin,
    client_ip,
    current_principal,
    get_ctx,
    get_db,
    needs_2fa_enrolment,
)
from ..security.passwords import hash_password, password_problems, verify_password
from ..security.sessions import create_session, revoke_user_sessions
from ..services.accounts import authenticate, verify_step_up
from .errors import ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    totp: str | None = Field(default=None, max_length=12)


class PasswordBody(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class PasswordOnly(BaseModel):
    password: str = Field(max_length=256)


class CodeBody(BaseModel):
    code: str = Field(max_length=12)


class StepUpBody(BaseModel):
    password: str = Field(max_length=256)
    totp: str | None = Field(default=None, max_length=12)


def me_payload(ctx, db: Session, principal_user, session: UserSession) -> dict:
    user = principal_user
    branch = db.get(Branch, user.branch_id) if user.branch_id else None
    cfg = ctx.store.all(db)
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "branch": branch.name if branch else None,
            "totp_enabled": user.totp_enabled,
        },
        "csrf": session.csrf_token,
        "flags": {
            "must_change_password": user.must_change_password,
            "must_setup_2fa": needs_2fa_enrolment(user, ctx.settings),
        },
        "app": {
            "name": ctx.settings.app_name,
            "pharmacy_name": cfg["pharmacy_name"],
            "label_footer": cfg["label_footer"],
            "academy_enabled": cfg["academy_enabled"],
            "password_min_length": ctx.settings.password_min_length,
        },
    }


def _set_cookie(response: Response, ctx, token: str) -> None:
    s = ctx.settings
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_absolute_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    check_same_origin(request)
    ip = client_ip(request)
    user = authenticate(db, ctx, body.username, body.password, body.totp, ip)
    token, session = create_session(db, ctx.settings, user, ip, request.headers.get("user-agent", ""))
    db.commit()
    _set_cookie(response, ctx, token)
    ctx.audit.record("login_success", user_id=user.id, username=user.username, ip=ip)
    return me_payload(ctx, db, user, session)


@router.get("/me")
def me(p: Principal = Depends(current_principal), ctx=Depends(get_ctx), db: Session = Depends(get_db)):
    return me_payload(ctx, db, p.user, p.session)


@router.post("/logout")
def logout(
    response: Response, p: Principal = Depends(current_principal), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    p.session.revoked = True
    db.commit()
    response.delete_cookie(
        ctx.settings.session_cookie_name, path="/", secure=ctx.settings.cookie_secure, samesite="strict"
    )
    ctx.audit.record("logout", user_id=p.id, username=p.user.username, ip=p.ip)
    return {"ok": True}


@router.post("/password")
def change_password(
    body: PasswordBody, p: Principal = Depends(current_principal), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    user = p.user
    if not ctx.limiter.hit(f"pwchange:{user.id}", 10, 900):
        raise ApiError(429, "محاولات كثيرة، حاول لاحقاً", "rate_limited")
    if not verify_password(user.password_hash, body.current):
        ctx.audit.record("password_change_failed", user_id=user.id, username=user.username, ip=p.ip)
        raise ApiError(403, "كلمة المرور الحالية غير صحيحة", "bad_password")
    problems = password_problems(body.new, user.username, ctx.settings.password_min_length)
    if problems:
        raise ApiError(400, "؛ ".join(problems), "weak_password")
    if verify_password(user.password_hash, body.new):
        raise ApiError(400, "كلمة المرور الجديدة يجب أن تختلف عن الحالية", "same_password")
    user.password_hash = hash_password(body.new)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    revoke_user_sessions(db, user.id, except_session_id=p.session.id)
    db.commit()
    ctx.audit.record("password_changed", user_id=user.id, username=user.username, ip=p.ip)
    return me_payload(ctx, db, user, p.session)


@router.post("/totp/setup")
def totp_setup(
    body: PasswordOnly, p: Principal = Depends(current_principal), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    user = p.user
    if user.totp_enabled:
        raise ApiError(400, "التحقق بخطوتين مفعّل بالفعل", "already_enabled")
    verify_step_up(db, ctx, user, body.password, None, p.ip)
    secret = totp.new_secret()
    user.totp_secret_enc = ctx.keyring.encrypt_field(secret.encode(), f"totp:{user.id}")
    db.commit()
    uri = totp.provisioning_uri(secret, user.username, issuer="Rushd")
    svg = base64.b64encode(totp.qr_svg(uri).encode()).decode()
    return {"secret": secret, "uri": uri, "qr": f"data:image/svg+xml;base64,{svg}"}


@router.post("/totp/enable")
def totp_enable(
    body: CodeBody, p: Principal = Depends(current_principal), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    user = p.user
    if user.totp_enabled or not user.totp_secret_enc:
        raise ApiError(400, "ابدأ إعداد التحقق بخطوتين أولاً", "not_pending")
    if not ctx.limiter.hit(f"totp-enable:{user.id}", 10, 900):
        raise ApiError(429, "محاولات كثيرة، حاول لاحقاً", "rate_limited")
    secret = ctx.keyring.decrypt_field(user.totp_secret_enc, f"totp:{user.id}").decode()
    step = totp.verify_code(secret, body.code, None)
    if step is None:
        raise ApiError(400, "الرمز غير صحيح - تأكد من ضبط الوقت على هاتفك", "mfa_invalid")
    user.totp_enabled = True
    user.totp_last_step = step
    db.commit()
    ctx.audit.record("totp_enabled", user_id=user.id, username=user.username, ip=p.ip)
    return me_payload(ctx, db, user, p.session)


@router.post("/totp/disable")
def totp_disable(
    body: StepUpBody, p: Principal = Depends(current_principal), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    user = p.user
    if user.role == "admin" and ctx.settings.require_2fa_for_admins:
        raise ApiError(400, "لا يمكن إيقاف التحقق بخطوتين لحساب مدير", "required")
    if not user.totp_enabled:
        raise ApiError(400, "التحقق بخطوتين غير مفعّل", "not_enabled")
    verify_step_up(db, ctx, user, body.password, body.totp, p.ip)
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = None
    db.commit()
    ctx.audit.record("totp_disabled", user_id=user.id, username=user.username, ip=p.ip)
    return me_payload(ctx, db, user, p.session)


@router.get("/sessions")
def my_sessions(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    now = utcnow()
    rows = db.execute(
        select(UserSession)
        .where(UserSession.user_id == p.id, UserSession.revoked.is_(False), UserSession.expires_at > now)
        .order_by(UserSession.last_seen_at.desc())
    ).scalars()
    return [
        {
            "id": s.id,
            "created_at": s.created_at.isoformat(),
            "last_seen_at": s.last_seen_at.isoformat(),
            "ip": s.ip,
            "user_agent": s.user_agent,
            "current": s.id == p.session.id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: int, p: Principal = Depends(current_principal), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != p.id:
        raise ApiError(404, "الجلسة غير موجودة")
    session.revoked = True
    db.commit()
    ctx.audit.record("session_revoked", user_id=p.id, username=p.user.username, ip=p.ip, target=str(session_id))
    return {"ok": True}
