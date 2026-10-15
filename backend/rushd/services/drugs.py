"""Drug database: seeding, CSV import and lexicon loading."""

from __future__ import annotations

import csv
import io
from importlib import resources

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..ai.lexicon import DrugRecord
from ..ai.safety import ingredients
from ..ai.text import norm
from ..db import utcnow
from ..models import Drug
from .csvsafe import to_csv

CSV_FIELDS = ["brand", "generic", "class", "forms", "strengths", "aliases"]
MAX_IMPORT_ROWS = 50_000


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split("|") if v.strip()]


def to_record(drug: Drug) -> DrugRecord:
    return DrugRecord(
        id=drug.id,
        brand=drug.brand,
        generic=drug.generic,
        drug_class=drug.drug_class,
        forms=tuple(drug.forms or ()),
        strengths=tuple(drug.strengths or ()),
        aliases=tuple(drug.aliases or ()),
        is_generic=drug.is_generic,
    )


def loader(session_factory: sessionmaker):
    def load() -> list[DrugRecord]:
        with session_factory() as db:
            rows = db.execute(select(Drug).where(Drug.is_active.is_(True))).scalars().all()
            return [to_record(d) for d in rows]

    return load


def fingerprint(session_factory: sessionmaker):
    def current() -> tuple:
        with session_factory() as db:
            return tuple(
                db.execute(
                    select(func.count(Drug.id), func.max(Drug.updated_at), func.sum(case((Drug.is_active, 1), else_=0)))
                ).one()
            )

    return current


def upsert(db: Session, row: dict, source: str) -> tuple[Drug | None, bool]:
    """Insert or update by normalised brand name. Returns (drug, created)."""
    brand = (row.get("brand") or "").strip()[:120]
    key = norm(brand)
    if not key:
        return None, False
    drug = db.execute(select(Drug).where(Drug.brand_norm == key)).scalar_one_or_none()
    created = drug is None
    if created:
        drug = Drug(brand=brand, brand_norm=key, source=source)
        db.add(drug)
    drug.generic = (row.get("generic") or drug.generic or "").strip()[:240]
    drug.drug_class = (row.get("class") or row.get("drug_class") or drug.drug_class or "").strip()[:80]
    for field in ("forms", "strengths", "aliases"):
        value = row.get(field)
        if isinstance(value, str):
            value = _split(value)
        if value:
            setattr(drug, field, [str(v)[:80] for v in value][:40])
    drug.is_active = True
    drug.updated_at = utcnow()
    return drug, created


def import_csv(db: Session, text: str, source: str = "import") -> dict:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "brand" not in [f.strip().lower() for f in reader.fieldnames]:
        raise ValueError("ملف CSV يجب أن يحتوي على عمود brand على الأقل")
    created = updated = skipped = 0
    for i, raw in enumerate(reader):
        if i >= MAX_IMPORT_ROWS:
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        drug, was_created = upsert(db, row, source)
        if drug is None:
            skipped += 1
        elif was_created:
            created += 1
        else:
            updated += 1
        db.flush()
    _ensure_generics(db)
    return {"created": created, "updated": updated, "skipped": skipped}


def export_csv(db: Session) -> str:
    rows = (
        [
            d.brand,
            d.generic,
            d.drug_class,
            "|".join(d.forms or []),
            "|".join(d.strengths or []),
            "|".join(d.aliases or []),
        ]
        for d in db.execute(select(Drug).where(Drug.is_active.is_(True)).order_by(Drug.brand)).scalars()
    )
    return to_csv(CSV_FIELDS, rows)


def _ensure_generics(db: Session) -> None:
    """Make every single-ingredient generic matchable on its own (doctors write them too)."""
    seen: dict[str, str] = {}
    for drug in db.execute(select(Drug).where(Drug.is_generic.is_(False))).scalars():
        ing = ingredients(drug.generic)
        if len(ing) == 1 and drug.generic:
            name = next(iter(ing))
            if not {"combination", "herbal", "extract"} & set(name.split()):
                seen.setdefault(name, drug.drug_class)
    for name, drug_class in seen.items():
        key = norm(name)
        if db.execute(select(Drug.id).where(Drug.brand_norm == key)).first():
            continue
        db.add(
            Drug(
                brand=name.title() if name.isascii() else name,
                brand_norm=key,
                generic=name,
                drug_class=drug_class,
                is_generic=True,
                source="generic",
            )
        )
        db.flush()


def seed_if_empty(db: Session) -> int:
    if db.execute(select(Drug.id).limit(1)).first():
        return 0
    text = resources.files("rushd.data").joinpath("drugs_seed.csv").read_text(encoding="utf-8")
    result = import_csv(db, text, source="seed")
    return result["created"]
