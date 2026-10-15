"""Database schema.

Patient-identifying content (images, AI readings, verified readings) is never
stored in plain text: images live in the encrypted blob store and readings are
stored as AES-GCM ciphertext (``*_enc`` columns). Plain columns only hold
operational data (statuses, scores, drug and doctor names).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, utcnow

ROLES = ("admin", "trainer", "pharmacist", "trainee")


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="pharmacist")
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(256), default="")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Blob(Base):
    """Bookkeeping for encrypted files on disk (see storage.BlobStore)."""

    __tablename__ = "blobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    name_norm: Mapped[str] = mapped_column(String(160), index=True)
    specialty: Mapped[str] = mapped_column(String(120), default="")
    clinic: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    verified_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Drug(Base):
    """A product family (brand) or a plain generic name."""

    __tablename__ = "drugs"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(120))
    brand_norm: Mapped[str] = mapped_column(String(120), index=True)
    generic: Mapped[str] = mapped_column(String(240), default="")
    drug_class: Mapped[str] = mapped_column(String(80), default="")
    forms: Mapped[list] = mapped_column(JSON, default=list)
    strengths: Mapped[list] = mapped_column(JSON, default=list)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    is_generic: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("brand_norm", name="uq_drug_brand_norm"),)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20), default="prelabel")  # prelabel | import
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    total: Mapped[int] = mapped_column(Integer, default=0)


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # queued -> processing -> needs_review -> verified | rejected ; failed on errors
    status: Mapped[str] = mapped_column(String(20), index=True, default="queued")
    source: Mapped[str] = mapped_column(String(16), default="read")  # read | bulk | import
    priority: Mapped[int] = mapped_column(Integer, default=10)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True, index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"), nullable=True, index=True)
    doctor_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    image_blob: Mapped[str] = mapped_column(String(32))
    thumb_blob: Mapped[str] = mapped_column(String(32))
    image_mac: Mapped[str] = mapped_column(String(64), index=True)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)

    ai_result_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    verified_result_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    shadow_result_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    engine: Mapped[str] = mapped_column(String(40), default="")
    engine_model: Mapped[str] = mapped_column(String(120), default="")
    passes: Mapped[int] = mapped_column(Integer, default=0)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_items: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(String(400), default="")

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    use_for_training: Mapped[bool] = mapped_column(Boolean, default=True)
    academy_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    # Accuracy of the AI reading against the pharmacist-verified truth.
    acc_drug: Mapped[float | None] = mapped_column(Float, nullable=True)
    acc_fields: Mapped[float | None] = mapped_column(Float, nullable=True)
    cer: Mapped[float | None] = mapped_column(Float, nullable=True)
    items_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shadow_acc_drug: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_rx_status_priority", "status", "priority", "id"),)


class Correction(Base):
    """What the AI read vs. what the pharmacist corrected it to.

    ``scope`` is ``g`` (global) or ``d<doctor_id>``; the per-doctor scope is
    how the system learns an individual doctor's handwriting quirks.
    """

    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(24), index=True)
    wrong_norm: Mapped[str] = mapped_column(String(160), index=True)
    right_text: Mapped[str] = mapped_column(String(160))
    drug_id: Mapped[int | None] = mapped_column(ForeignKey("drugs.id"), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("scope", "wrong_norm", "right_text", name="uq_correction"),)


class DoctorDrugStat(Base):
    """How often a doctor prescribes a drug - a strong prior when reading."""

    __tablename__ = "doctor_drug_stats"

    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True)
    drug_id: Mapped[int] = mapped_column(ForeignKey("drugs.id", ondelete="CASCADE"), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    last_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    base_model: Mapped[str] = mapped_column(String(160))
    adapter_blob: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ready")  # ready | archived
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    train_count: Mapped[int] = mapped_column(Integer, default=0)
    eval_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed|cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(400), default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    log_tail: Mapped[str] = mapped_column(Text, default="")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    """Append-only, HMAC hash-chained security log."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(128), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
