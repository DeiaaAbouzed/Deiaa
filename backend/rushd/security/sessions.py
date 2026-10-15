"""Server-side sessions.

The browser only ever holds a random token in an HttpOnly, SameSite=Strict
cookie; the database stores its SHA-256, so a leaked database cannot be used
to hijack sessions. Sessions expire after inactivity and after an absolute
lifetime, and can be revoked instantly (logout, password change, admin).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..models import User, UserSession

TOUCH_EVERY = timedelta(seconds=60)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, settings: Settings, user: User, ip: str, user_agent: str) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    session = UserSession(
        token_hash=_hash(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip=ip[:64],
        user_agent=user_agent[:256],
    )
    db.add(session)
    db.flush()
    return token, session


def resolve_session(db: Session, settings: Settings, token: str | None) -> tuple[UserSession, User] | None:
    if not token or len(token) > 128:
        return None
    session = db.execute(select(UserSession).where(UserSession.token_hash == _hash(token))).scalar_one_or_none()
    if session is None or session.revoked:
        return None
    now = utcnow()
    idle_limit = session.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if now >= session.expires_at or now >= idle_limit:
        session.revoked = True
        db.commit()
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    if now - session.last_seen_at > TOUCH_EVERY:
        session.last_seen_at = now
        db.commit()
    return session, user


def revoke_user_sessions(db: Session, user_id: int, except_session_id: int | None = None) -> int:
    stmt = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked.is_(False))
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    result = db.execute(stmt.values(revoked=True))
    return result.rowcount or 0
