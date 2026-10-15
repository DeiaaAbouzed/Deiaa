"""Move a trained model between Rushd servers.

Typical use: train on a rented GPU machine, then bring the model home to the
pharmacy's server. The transfer file is a password-encrypted ``.rushd``
archive (the same format as dataset exports) holding ``model.json`` (name and
evaluation metrics) and ``adapter.zip`` (the LoRA bundle: safetensors weights
plus JSON config - never pickle, never code).

Imports are validated without importing torch, re-encrypted under this
server's master key, and never activated automatically.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ModelVersion
from .common import BUNDLE_FORMAT
from .export import EncryptingWriter, decrypt_stream

MAX_FILE = 1024**3
MAX_INFO = 64 * 1024
BUNDLE_PARTS = {"meta.json", "adapter_config.json", "adapter.safetensors"}
REPO_ID = re.compile(r"[A-Za-z0-9][\w.-]{0,95}/[A-Za-z0-9][\w.-]{0,95}")  # Hugging Face "org/name"
REVISION = re.compile(r"[\w.-]{1,64}")
RATE_METRICS = ("acc_drug", "acc_fields", "cer", "parse_rate", "cloud_acc_drug", "train_loss")


class TransferError(Exception):
    pass


def find_model(db: Session, ref: str) -> ModelVersion:
    model = db.get(ModelVersion, int(ref)) if ref.isdigit() else None
    if model is None:
        model = db.execute(select(ModelVersion).where(ModelVersion.name == ref)).scalar_one_or_none()
    if model is None or model.status != "ready" or not model.adapter_blob:
        raise TransferError(f"النموذج {ref} غير موجود")
    return model


def export_model(db: Session, ctx, ref: str, out_path: Path, password: str) -> ModelVersion:
    model = find_model(db, ref)
    bundle = ctx.blobs.get(model.adapter_blob, "model")
    info = {
        "name": model.name,
        "base_model": model.base_model,
        "metrics": model.metrics or {},
        "train_count": model.train_count,
        "eval_count": model.eval_count,
        "created_at": model.created_at.isoformat(),
    }
    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            writer = EncryptingWriter(fh, password)
            with zipfile.ZipFile(writer, "w", zipfile.ZIP_STORED) as zf:
                zf.writestr("model.json", json.dumps(info, ensure_ascii=False))
                zf.writestr("adapter.zip", bundle)
            writer.close()
    except BaseException:
        out_path.unlink(missing_ok=True)
        raise
    return model


def _read(zf: zipfile.ZipFile, name: str, cap: int) -> bytes:
    if zf.getinfo(name).file_size > cap:
        raise TransferError(f"الجزء {name} أكبر من المسموح")
    return zf.read(name)


def _check_safetensors(data: bytes) -> None:
    """Structural check of the weights file; the loader itself never runs code either."""
    size = int.from_bytes(data[:8], "little") if len(data) >= 8 else -1
    if not 0 < size <= len(data) - 8:
        raise TransferError("ملف الأوزان تالف")
    try:
        header = json.loads(data[8 : 8 + size])
    except ValueError as exc:
        raise TransferError("ملف الأوزان تالف") from exc
    payload = len(data) - 8 - size
    tensors = [v for k, v in header.items() if k != "__metadata__"] if isinstance(header, dict) else []
    for entry in tensors:
        offsets = entry.get("data_offsets") if isinstance(entry, dict) else None
        if not (
            isinstance(offsets, list)
            and len(offsets) == 2
            and all(isinstance(o, int) for o in offsets)
            and 0 <= offsets[0] <= offsets[1] <= payload
        ):
            raise TransferError("ملف الأوزان تالف")
    if not tensors:
        raise TransferError("ملف الأوزان فارغ")


def inspect_bundle(bundle: bytes, allowed_bases: set[str]) -> dict:
    """Validate an adapter bundle without torch; returns its metadata."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(bundle))
        if set(zf.namelist()) != BUNDLE_PARTS:
            raise TransferError("محتويات ملف النموذج غير متوقعة")
        meta = json.loads(_read(zf, "meta.json", MAX_INFO))
        config = json.loads(_read(zf, "adapter_config.json", MAX_INFO))
        weights = _read(zf, "adapter.safetensors", MAX_FILE)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise TransferError("ملف النموذج تالف") from exc
    if not isinstance(meta, dict) or meta.get("format") != BUNDLE_FORMAT:
        raise TransferError("صيغة النموذج غير مدعومة")
    base = meta.get("base_model")
    if not isinstance(base, str) or not (REPO_ID.fullmatch(base) or base in allowed_bases):
        raise TransferError("اسم النموذج الأساسي غير صالح")
    revision = meta.get("revision")
    if revision is not None and not (isinstance(revision, str) and REVISION.fullmatch(revision)):
        raise TransferError("إصدار النموذج الأساسي غير صالح")
    if not isinstance(config, dict) or config.get("peft_type") != "LORA":
        raise TransferError("نوع النموذج غير مدعوم")
    _check_safetensors(weights)
    return meta


def _clean_metrics(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for key in RATE_METRICS:
        value = raw.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool) and value == value:  # drop NaN
            out[key] = round(float(value), 4)
    for key in ("eval_count", "epochs"):
        if isinstance(raw.get(key), int) and not isinstance(raw.get(key), bool):
            out[key] = max(0, raw[key])
    return out


def _count(value) -> int:
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0


def import_model(db: Session, ctx, path: Path, password: str) -> ModelVersion:
    if path.stat().st_size > MAX_FILE:
        raise TransferError("الملف أكبر من المسموح")
    plain = io.BytesIO()
    with open(path, "rb") as src:
        decrypt_stream(src, plain, password)  # wrong password or tampering -> ExportError
    try:
        with zipfile.ZipFile(plain) as zf:
            info = json.loads(_read(zf, "model.json", MAX_INFO))
            bundle = _read(zf, "adapter.zip", MAX_FILE)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise TransferError("ملف النموذج غير صالح") from exc
    info = info if isinstance(info, dict) else {}
    meta = inspect_bundle(bundle, {ctx.settings.local_base_model})
    metrics = _clean_metrics(info.get("metrics"))
    metrics["imported_from"] = str(info.get("name") or "")[:80]
    number = (db.execute(select(func.count(ModelVersion.id))).scalar_one() or 0) + 1
    version = ModelVersion(
        name=f"rushd-local-v{number}-imported",
        base_model=meta["base_model"],
        adapter_blob=ctx.blobs.put(db, bundle, "model"),
        metrics=metrics,
        train_count=_count(info.get("train_count")),
        eval_count=_count(info.get("eval_count")),
    )
    db.add(version)
    db.commit()
    return version
