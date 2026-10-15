"""Login, lockout, 2FA and step-up verification."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..api.errors import ApiError
from ..db import utcnow
from ..models import User
from ..security import totp
from ..security.passwords import hash_password, needs_rehash, verify_password

GENERIC_FAILURE = "اسم المستخدم أو كلمة المرور غير صحيحة"


def find_user(db: Session, username: str) -> User | None:
    name = (username or "").strip().lower()
    if not name or len(name) > 64:
        return None
    return db.execute(select(User).where(func.lower(User.username) == name)).scalar_one_or_none()


def _register_failure(db: Session, ctx, user: User | None, ip: str, username: str, reason: str) -> None:
    if user is not None:
        user.failed_logins += 1
        if user.failed_logins >= ctx.settings.login_max_failures:
            user.locked_until = utcnow() + timedelta(minutes=ctx.settings.lockout_minutes)
            user.failed_logins = 0
            ctx.audit.record("account_locked", user_id=user.id, username=user.username, ip=ip)
        db.commit()
    ctx.audit.record(
        "login_failed", user_id=user.id if user else None, username=username[:64], ip=ip, details={"reason": reason}
    )


def _check_totp(db: Session, ctx, user: User, code: str | None, ip: str, username: str) -> None:
    if not user.totp_enabled:
        return
    if not code:
        raise ApiError(401, "أدخل رمز التحقق من تطبيق المصادقة", "mfa_required")
    secret = ctx.keyring.decrypt_field(user.totp_secret_enc, f"totp:{user.id}").decode()
    step = totp.verify_code(secret, code, user.totp_last_step)
    if step is None:
        _register_failure(db, ctx, user, ip, username, "bad_totp")
        raise ApiError(401, "رمز التحقق غير صحيح أو مستخدم من قبل", "mfa_invalid")
    user.totp_last_step = step


def authenticate(db: Session, ctx, username: str, password: str, code: str | None, ip: str) -> User:
    limiter_key = f"login-ip:{ip}"
    if not ctx.limiter.hit(limiter_key, ctx.settings.login_ip_limit_per_15min, 900):
        retry = ctx.limiter.retry_after(limiter_key, 900)
        raise ApiError(429, "محاولات كثيرة، حاول لاحقاً", "rate_limited", headers={"Retry-After": str(retry)})

    user = find_user(db, username)
    now = utcnow()
    if user is not None and user.locked_until and user.locked_until > now:
        minutes = int((user.locked_until - now).total_seconds() // 60) + 1
        verify_password(None, password)  # same work as a normal attempt
        raise ApiError(423, f"الحساب مقفل مؤقتاً بسبب محاولات خاطئة - حاول بعد {minutes} دقيقة", "locked")

    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        _register_failure(db, ctx, user if (user and user.is_active) else None, ip, username, "bad_password")
        raise ApiError(401, GENERIC_FAILURE, "bad_credentials")

    _check_totp(db, ctx, user, code, ip, username)

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def verify_step_up(db: Session, ctx, user: User, password: str, code: str | None, ip: str) -> None:
    """Re-confirm identity before sensitive actions (exports, user admin, settings)."""
    key = f"stepup:{user.id}"
    if not ctx.limiter.hit(key, 10, 900):
        raise ApiError(429, "محاولات كثيرة، حاول لاحقاً", "rate_limited")
    if not verify_password(user.password_hash, password or ""):
        _register_failure(db, ctx, user, ip, user.username, "bad_step_up")
        raise ApiError(403, "كلمة المرور غير صحيحة", "step_up_failed")
    _check_totp(db, ctx, user, code, ip, user.username)
    db.commit()
