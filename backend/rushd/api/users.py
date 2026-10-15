from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Branch, User
from ..security.deps import ADMIN, EVERYONE, Principal, get_ctx, get_db, require_roles
from ..security.passwords import generate_temporary_password, hash_password
from ..security.sessions import revoke_user_sessions
from ..services.accounts import find_user, verify_step_up
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["users"])

_USERNAME = re.compile(r"^[a-z0-9._-]{3,32}$")


class UserCreate(BaseModel):
    username: str = Field(max_length=32)
    full_name: str = Field(default="", max_length=120)
    role: str = Field(pattern="^(admin|trainer|pharmacist|trainee)$")
    branch_id: int | None = None
    password: str | None = Field(default=None, max_length=256, description="admin step-up when creating an admin")
    totp: str | None = Field(default=None, max_length=12)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, pattern="^(admin|trainer|pharmacist|trainee)$")
    branch_id: int | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=256)
    totp: str | None = Field(default=None, max_length=12)


class StepUp(BaseModel):
    password: str = Field(max_length=256)
    totp: str | None = Field(default=None, max_length=12)


class BranchBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)


def user_dict(u: User, branches: dict[int, str]) -> dict:
    now = utcnow()
    return {
        "id": u.id,
        "username": u.username,
        "full_name": u.full_name,
        "role": u.role,
        "branch_id": u.branch_id,
        "branch": branches.get(u.branch_id) if u.branch_id else None,
        "is_active": u.is_active,
        "totp_enabled": u.totp_enabled,
        "must_change_password": u.must_change_password,
        "locked": bool(u.locked_until and u.locked_until > now),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat(),
    }


def _branches(db: Session) -> dict[int, str]:
    return {b.id: b.name for b in db.execute(select(Branch)).scalars()}


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "المستخدم غير موجود")
    return user


@router.get("/users")
def list_users(p: Principal = Depends(require_roles(*ADMIN)), db: Session = Depends(get_db)):
    branches = _branches(db)
    return [user_dict(u, branches) for u in db.execute(select(User).order_by(User.username)).scalars()]


@router.post("/users", status_code=201)
def create_user(
    body: UserCreate, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    username = body.username.strip().lower()
    if not _USERNAME.match(username):
        raise ApiError(400, "اسم المستخدم: 3-32 حرف إنجليزي صغير أو أرقام أو . _ -")
    if find_user(db, username):
        raise ApiError(409, "اسم المستخدم مستخدم بالفعل")
    if body.role == "admin":
        verify_step_up(db, ctx, p.user, body.password or "", body.totp, p.ip)
    if body.branch_id is not None and db.get(Branch, body.branch_id) is None:
        raise ApiError(400, "الفرع غير موجود")
    temporary = generate_temporary_password()
    user = User(
        username=username,
        full_name=body.full_name.strip(),
        role=body.role,
        branch_id=body.branch_id,
        password_hash=hash_password(temporary),
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    ctx.audit.record(
        "user_created", user_id=p.id, username=p.user.username, ip=p.ip, target=username, details={"role": body.role}
    )
    return {"user": user_dict(user, _branches(db)), "temporary_password": temporary}


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    p: Principal = Depends(require_roles(*ADMIN)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    changes = body.model_dump(exclude_unset=True, exclude={"password", "totp"})
    if user.id == p.id and (changes.get("role", "admin") != "admin" or changes.get("is_active") is False):
        raise ApiError(400, "لا يمكنك إزالة صلاحية المدير أو تعطيل حسابك بنفسك")
    if changes.get("role") == "admin" and user.role != "admin":
        verify_step_up(db, ctx, p.user, body.password or "", body.totp, p.ip)
    if "branch_id" in changes and changes["branch_id"] is not None and db.get(Branch, changes["branch_id"]) is None:
        raise ApiError(400, "الفرع غير موجود")
    for key, value in changes.items():
        setattr(user, key, value.strip() if isinstance(value, str) else value)
    if changes.get("is_active") is False or "role" in changes:
        revoke_user_sessions(db, user.id)
    db.commit()
    ctx.audit.record(
        "user_updated", user_id=p.id, username=p.user.username, ip=p.ip, target=user.username, details=changes
    )
    return user_dict(user, _branches(db))


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    user = _get_user(db, user_id)
    temporary = generate_temporary_password()
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    revoke_user_sessions(db, user.id)
    db.commit()
    ctx.audit.record("password_reset", user_id=p.id, username=p.user.username, ip=p.ip, target=user.username)
    return {"temporary_password": temporary}


@router.post("/users/{user_id}/unlock")
def unlock(
    user_id: int, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    user = _get_user(db, user_id)
    user.locked_until = None
    user.failed_logins = 0
    db.commit()
    ctx.audit.record("user_unlocked", user_id=p.id, username=p.user.username, ip=p.ip, target=user.username)
    return {"ok": True}


@router.post("/users/{user_id}/reset-2fa")
def reset_2fa(
    user_id: int,
    body: StepUp,
    p: Principal = Depends(require_roles(*ADMIN)),
    ctx=Depends(get_ctx),
    db: Session = Depends(get_db),
):
    verify_step_up(db, ctx, p.user, body.password, body.totp, p.ip)
    user = _get_user(db, user_id)
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = None
    revoke_user_sessions(db, user.id)
    db.commit()
    ctx.audit.record("totp_reset", user_id=p.id, username=p.user.username, ip=p.ip, target=user.username)
    return {"ok": True}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(
    user_id: int, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    user = _get_user(db, user_id)
    count = revoke_user_sessions(db, user.id, except_session_id=p.session.id if user.id == p.id else None)
    db.commit()
    ctx.audit.record(
        "sessions_revoked",
        user_id=p.id,
        username=p.user.username,
        ip=p.ip,
        target=user.username,
        details={"count": count},
    )
    return {"revoked": count}


@router.get("/branches")
def list_branches(p: Principal = Depends(require_roles(*EVERYONE)), db: Session = Depends(get_db)):
    return [{"id": b.id, "name": b.name} for b in db.execute(select(Branch).order_by(Branch.name)).scalars()]


@router.post("/branches", status_code=201)
def create_branch(
    body: BranchBody, p: Principal = Depends(require_roles(*ADMIN)), ctx=Depends(get_ctx), db: Session = Depends(get_db)
):
    name = body.name.strip()
    if db.execute(select(Branch.id).where(Branch.name == name)).first():
        raise ApiError(409, "الفرع موجود بالفعل")
    branch = Branch(name=name)
    db.add(branch)
    db.commit()
    ctx.audit.record("branch_created", user_id=p.id, username=p.user.username, ip=p.ip, target=name)
    return {"id": branch.id, "name": branch.name}
