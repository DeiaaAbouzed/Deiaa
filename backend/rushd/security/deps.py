"""FastAPI dependencies: database session, authentication, CSRF and roles."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..api.errors import ApiError
from ..models import User, UserSession
from .sessions import resolve_session

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Reachable while the account still has to change its password or enrol 2FA.
RESTRICTED_ALLOWLIST = {
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/password",
    "/api/auth/totp/setup",
    "/api/auth/totp/enable",
}


def get_ctx(request: Request):
    return request.app.state.ctx


def get_db(ctx=Depends(get_ctx)):
    db = ctx.sf()
    try:
        yield db
    finally:
        db.close()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@dataclass
class Principal:
    user: User
    session: UserSession
    ip: str

    @property
    def id(self) -> int:
        return self.user.id

    @property
    def role(self) -> str:
        return self.user.role


def check_same_origin(request: Request) -> None:
    """Defence in depth on top of SameSite=Strict cookies and the CSRF header."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in ("same-origin", "none"):
        raise ApiError(403, "طلب من مصدر غير موثوق", "cross_site")
    origin = request.headers.get("origin")
    if origin and origin != "null" and urlparse(origin).netloc != request.headers.get("host", ""):
        raise ApiError(403, "طلب من مصدر غير موثوق", "bad_origin")


def needs_2fa_enrolment(user: User, settings) -> bool:
    return bool(settings.require_2fa_for_admins and user.role == "admin" and not user.totp_enabled)


def current_principal(request: Request, ctx=Depends(get_ctx), db: Session = Depends(get_db)) -> Principal:
    token = request.cookies.get(ctx.settings.session_cookie_name)
    resolved = resolve_session(db, ctx.settings, token)
    if resolved is None:
        raise ApiError(401, "انتهت الجلسة، سجّل الدخول مرة أخرى", "unauthenticated")
    session, user = resolved
    if request.method in UNSAFE_METHODS:
        check_same_origin(request)
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent.encode(), session.csrf_token.encode()):
            raise ApiError(403, "رمز الحماية غير صالح - أعد تحميل الصفحة", "csrf")
    if request.url.path not in RESTRICTED_ALLOWLIST:
        if user.must_change_password:
            raise ApiError(403, "يجب تغيير كلمة المرور أولاً", "password_change_required")
        if needs_2fa_enrolment(user, ctx.settings):
            raise ApiError(403, "يجب تفعيل التحقق بخطوتين لحساب المدير أولاً", "totp_setup_required")
    return Principal(user=user, session=session, ip=client_ip(request))


def require_roles(*roles: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise ApiError(403, "ليس لديك صلاحية لهذا الإجراء", "forbidden")
        return principal

    return dependency


STAFF = ("admin", "trainer", "pharmacist")
MANAGERS = ("admin", "trainer")
ADMIN = ("admin",)
EVERYONE = ("admin", "trainer", "pharmacist", "trainee")


def ensure_recent_step_up(ctx, principal: Principal) -> None:
    """Account administration: the password (and 2FA code) must have been re-entered recently."""
    if not ctx.step_up.active(principal.session.id):
        raise ApiError(403, "أكّد هويتك بكلمة المرور للمتابعة", "step_up_required")
