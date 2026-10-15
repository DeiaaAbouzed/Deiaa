"""Bulk import of already-transcribed prescriptions from a ZIP archive.

Layout: images (jpg/png/webp) plus an optional ``labels.jsonl`` or
``labels.csv``. Labelled images become verified training examples
immediately; unlabelled ones are queued for AI pre-reading and review.

The archive is never extracted to disk, and every entry is size-capped to
defeat zip bombs.
"""

from __future__ import annotations

import csv
import io
import json
import posixpath
import zipfile
from dataclasses import dataclass, field

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

    def __init__(self, data: bytes, max_image_bytes: int):
        try:
            self._zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ArchiveRejected("الملف ليس أرشيف ZIP صالح") from exc
        self._infos = [i for i in self._zf.infolist() if not i.is_dir()]
        if len(self._infos) > MAX_ENTRIES:
            raise ArchiveRejected(f"الأرشيف يحتوي على أكثر من {MAX_ENTRIES} ملف")
        self._max_image = max_image_bytes
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
            if total > MAX_TOTAL:
                raise ArchiveRejected("حجم الأرشيف بعد فك الضغط كبير جداً")
            label = self.labels.get(name, {})
            yield LabelledImage(name=name, data=raw, doctor=label.get("doctor") or {}, items=label.get("items") or [])
