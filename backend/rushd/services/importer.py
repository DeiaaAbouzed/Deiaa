"""Bulk import of already-transcribed prescriptions from a ZIP archive.

Layout: images (jpg/png/webp) plus an optional ``labels.jsonl`` or
``labels.csv``. Labelled images become verified training examples
immediately; unlabelled ones are queued for AI pre-reading and review.

The archive is never extracted to disk, and every entry is size-capped to
defeat zip bombs. The web upload and ``python -m rushd import-dataset`` share
``import_archive``; only their size limits differ.
"""

from __future__ import annotations

import csv
import io
import json
import os
import posixpath
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..ai import memory
from ..ai.postprocess import RESULT_VERSION
from ..ai.safety import check
from ..db import utcnow
from ..imaging import ImageRejected
from ..models import Batch, User
from .intake import find_duplicate, ingest_image
from .verification import build_verified_items
from .worker import PRIORITY_BULK

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_ENTRIES = 3000
MAX_TOTAL = 1024 * 1024 * 1024  # uncompressed bytes
MAX_LABEL_BYTES = 20 * 1024 * 1024


class ArchiveRejected(ValueError):
    pass


@dataclass
class LabelledImage:
    name: str
    data: bytes
    doctor: dict = field(default_factory=dict)
    items: list[dict] = field(default_factory=list)


def _read_capped(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    with zf.open(info) as fh:
        data = fh.read(cap + 1)
    if len(data) > cap:
        raise ArchiveRejected(f"الملف {info.filename} أكبر من المسموح")
    return data


def _parse_labels(name: str, raw: bytes) -> dict[str, dict]:
    text = raw.decode("utf-8-sig")
    labels: dict[str, dict] = {}
    if name.endswith(".jsonl"):
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ArchiveRejected(f"سطر غير صالح في labels.jsonl رقم {n}") from exc
            file = posixpath.basename(str(row.get("file", "")))
            if file:
                doctor = row.get("doctor") or {}
                labels[file] = {
                    "doctor": doctor if isinstance(doctor, dict) else {"name": str(doctor)},
                    "items": [i for i in row.get("items", []) if isinstance(i, dict)],
                }
    else:  # csv: one row per medication
        for row in csv.DictReader(io.StringIO(text)):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            file = posixpath.basename(row.get("file", ""))
            if not file or not row.get("brand"):
                continue
            entry = labels.setdefault(file, {"doctor": {"name": row.get("doctor", "")}, "items": []})
            entry["items"].append(
                {k: row.get(k, "") for k in ("brand", "strength", "form", "sig_text", "line_text") if row.get(k)}
            )
    return labels


class Archive:
    """Lazily yields images so memory use stays bounded by one image at a time."""

    def __init__(
        self,
        source: bytes | str | os.PathLike,
        max_image_bytes: int,
        *,
        max_entries: int = MAX_ENTRIES,
        max_total: int = MAX_TOTAL,
    ):
        try:
            self._zf = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source)
        except zipfile.BadZipFile as exc:
            raise ArchiveRejected("الملف ليس أرشيف ZIP صالح") from exc
        self._infos = [i for i in self._zf.infolist() if not i.is_dir()]
        if len(self._infos) > max_entries:
            raise ArchiveRejected(f"الأرشيف يحتوي على أكثر من {max_entries} ملف")
        self._max_image = max_image_bytes
        self._max_total = max_total
        self.labels: dict[str, dict] = {}
        for info in self._infos:
            base = posixpath.basename(info.filename).lower()
            if base in ("labels.jsonl", "labels.csv"):
                self.labels.update(_parse_labels(base, _read_capped(self._zf, info, MAX_LABEL_BYTES)))
        self.problems: list[dict] = []

    def images(self):
        total = 0
        for info in self._infos:
            name = posixpath.basename(info.filename)
            ext = posixpath.splitext(name)[1].lower()
            if name.startswith(".") or "__MACOSX" in info.filename or ext not in IMAGE_EXT:
                continue
            try:
                raw = _read_capped(self._zf, info, self._max_image)
            except ArchiveRejected as exc:
                self.problems.append({"file": name, "error": str(exc)})
                continue
            total += len(raw)
            if total > self._max_total:
                raise ArchiveRejected("حجم الأرشيف بعد فك الضغط كبير جداً")
            label = self.labels.get(name, {})
            yield LabelledImage(name=name, data=raw, doctor=label.get("doctor") or {}, items=label.get("items") or [])


def new_batch(db: Session, name: str, kind: str, user_id: int) -> Batch:
    batch = Batch(name=(name.strip() or f"دفعة {utcnow():%Y-%m-%d %H:%M}")[:160], kind=kind, created_by=user_id)
    db.add(batch)
    db.flush()
    return batch


@dataclass
class ImportOutcome:
    verified: int = 0
    queued: list[int] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)


def import_archive(
    db: Session,
    ctx,
    archive: Archive,
    *,
    user: User,
    batch_id: int,
    progress: Callable[[int], None] | None = None,
) -> ImportOutcome:
    """Labelled images become verified training examples; unlabelled ones are queued for AI pre-reading.

    The caller commits, records the audit event and hands ``queued`` to the worker. ArchiveRejected
    can still be raised midway (total size cap), in which case the caller must roll back.
    """
    class_map = ctx.class_map()
    out = ImportOutcome()
    for n, image in enumerate(archive.images(), start=1):
        if progress is not None:
            progress(n)
        if find_duplicate(db, ctx, image.data) is not None:
            out.problems.append({"file": image.name, "error": "مرفوعة من قبل"})
            continue
        labelled = bool(image.items)
        try:
            rx = ingest_image(
                db,
                ctx,
                image.data,
                user=user,
                source="import",
                priority=PRIORITY_BULK,
                batch_id=batch_id,
                status="verified" if labelled else "queued",
            )
        except ImageRejected as exc:
            out.problems.append({"file": image.name, "error": str(exc)})
            continue
        if not labelled:
            out.queued.append(rx.id)
            continue
        items = build_verified_items(db, ctx, image.items, add_unknown=True)
        doctor = None
        if (image.doctor.get("name") or "").strip():
            doctor = memory.find_or_create_doctor(
                db,
                image.doctor["name"],
                image.doctor.get("specialty", ""),
                image.doctor.get("clinic", ""),
                image.doctor.get("phone", ""),
            )
            for item in items:
                if item["drug_id"]:
                    memory.bump_doctor_drug(db, doctor.id, item["drug_id"])
            doctor.verified_count += 1
            doctor.last_seen_at = utcnow()
        result = {
            "version": RESULT_VERSION,
            "is_prescription": True,
            "doctor": {
                "name": doctor.name if doctor else None,
                "specialty": doctor.specialty if doctor else None,
                "clinic": None,
                "phone": None,
            },
            "patient": {"name": None, "age": None},
            "date": None,
            "diagnosis": None,
            "notes": "",
            "items": items,
            "warnings": check(items, class_map),
            "verified_by": user.username,
        }
        rx.verified_result_enc = ctx.keyring.encrypt_json(result, f"verified:{rx.uid}")
        rx.doctor_id = doctor.id if doctor else None
        rx.doctor_confirmed = doctor is not None
        rx.num_items = len(items)
        rx.verified_at = utcnow()
        rx.verified_by = user.id
        out.verified += 1
        db.flush()
    out.problems.extend(archive.problems)
    return out
