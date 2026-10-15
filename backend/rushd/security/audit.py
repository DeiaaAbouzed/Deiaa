"""Tamper-evident audit log.

Each entry stores ``hash = HMAC(audit_key, prev_hash || entry)``. Editing,
deleting or re-ordering any row breaks the chain, and because the chain is
keyed with a sub-key of the master key, someone with database access alone
cannot forge a consistent replacement. The latest head is also mirrored to a
sidecar file so truncating the newest rows is detected too.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db import utcnow
from ..models import AuditLog
from .crypto import KeyRing

log = logging.getLogger("rushd.audit")

GENESIS = "0" * 64


def _payload(entry: AuditLog) -> bytes:
    data = [
        entry.ts.isoformat(),
        entry.user_id,
        entry.username,
        entry.action,
        entry.target,
        entry.ip,
        entry.details or {},
        entry.prev_hash,
    ]
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    broken_at: int | None = None
    reason: str = ""


class AuditLogger:
    def __init__(self, session_factory: sessionmaker, keyring: KeyRing, head_file: Path):
        self._sf = session_factory
        self._kr = keyring
        self._head_file = head_file
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        *,
        user_id: int | None = None,
        username: str = "",
        target: str = "",
        ip: str = "",
        details: dict | None = None,
    ) -> None:
        """Append an entry in its own transaction (committed even if the caller rolls back)."""
        with self._lock, self._sf() as db:
            last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
            entry = AuditLog(
                ts=utcnow().replace(microsecond=0),
                user_id=user_id,
                username=username[:64],
                action=action[:64],
                target=str(target)[:128],
                ip=(ip or "")[:64],
                details=details or {},
                prev_hash=last.hash if last else GENESIS,
            )
            entry.hash = self._kr.audit_mac(_payload(entry))
            db.add(entry)
            db.commit()
            self._write_head(entry.id, entry.hash)

    def verify(self, db: Session) -> VerifyResult:
        prev = GENESIS
        checked = 0
        last_id = None
        for entry in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
            if entry.prev_hash != prev:
                return VerifyResult(False, checked, entry.id, "سجل محذوف أو معاد ترتيبه قبل هذا السطر")
            if self._kr.audit_mac(_payload(entry)) != entry.hash:
                return VerifyResult(False, checked, entry.id, "تم تعديل محتوى هذا السطر")
            prev = entry.hash
            last_id = entry.id
            checked += 1
        head = self._read_head()
        if head is not None and (head[0] != last_id or head[1] != prev):
            return VerifyResult(False, checked, last_id, "تم حذف أحدث السجلات (عدم تطابق رأس السلسلة)")
        return VerifyResult(True, checked)

    def _write_head(self, entry_id: int, entry_hash: str) -> None:
        try:
            tmp = self._head_file.with_suffix(".tmp")
            tag = self._kr.audit_mac(f"head:{entry_id}:{entry_hash}".encode())
            tmp.write_text(json.dumps({"id": entry_id, "hash": entry_hash, "tag": tag}))
            tmp.replace(self._head_file)
        except OSError:  # pragma: no cover - disk full etc.
            log.exception("could not persist audit head")

    def _read_head(self) -> tuple[int, str] | None:
        if not self._head_file.exists():
            return None
        try:
            data = json.loads(self._head_file.read_text())
            tag = self._kr.audit_mac(f"head:{data['id']}:{data['hash']}".encode())
            if tag != data.get("tag"):
                return (-1, "forged-head")
            return int(data["id"]), str(data["hash"])
        except (OSError, ValueError, KeyError):
            return (-1, "unreadable-head")
