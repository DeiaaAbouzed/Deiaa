from __future__ import annotations

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id with the RFC 9106 "low memory" profile (64 MiB, t=3, p=4).
_hasher = PasswordHasher()

# Verifying against this when the user does not exist keeps response timing
# identical, so usernames cannot be discovered by measuring login latency.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))

_COMMON = {
    "password",
    "password1",
    "password123",
    "123456789",
    "1234567890",
    "12345678910",
    "qwerty123",
    "qwertyuiop",
    "admin12345",
    "administrator",
    "iloveyou12",
    "pharmacy123",
    "pharmacist",
    "welcome123",
    "egypt12345",
    "letmein123",
    "abc1234567",
    "1q2w3e4r5t",
    "000000000",
    "1111111111",
    "a123456789",
    "p@ssw0rd123",
    "passw0rd12",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def password_problems(password: str, username: str = "", min_length: int = 10) -> list[str]:
    """Return a list of Arabic messages describing why a password is weak."""
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"كلمة المرور يجب ألا تقل عن {min_length} أحرف")
    if len(password) > 256:
        problems.append("كلمة المرور طويلة جداً")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        problems.append("استخدم مزيجاً من 3 أنواع على الأقل: حروف صغيرة، حروف كبيرة، أرقام، رموز")
    lowered = password.lower()
    if lowered in _COMMON:
        problems.append("كلمة المرور شائعة جداً وسهلة التخمين")
    if username and username.lower() in lowered:
        problems.append("كلمة المرور يجب ألا تحتوي على اسم المستخدم")
    return problems


def generate_temporary_password(length: int = 14) -> str:
    """A strong random password that satisfies the policy above."""
    alphabet = string.ascii_letters + string.digits + "!@#$%*-_"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if not password_problems(candidate, min_length=length):
            return candidate
