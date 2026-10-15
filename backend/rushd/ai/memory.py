"""The learning memory.

Every verified prescription teaches the system three things:

* the doctor's handwriting - verified images become few-shot examples shown
  to the vision model the next time that doctor's prescription is read;
* the doctor's habits - how often each drug is prescribed (a matching prior);
* corrections - "the AI read X, the pharmacist said Y", per doctor and global.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..imaging import resized_jpeg
from ..models import Correction, Doctor, DoctorDrugStat, Drug, Prescription
from .engines import FewShotExample
from .text import core_name, norm

_TITLES = re.compile(
    r"^(?:(?:prof|professor|dr|doctor|consultant|د|دكتور|الدكتور|دكتوره|الدكتوره|ا د|استاذ|الاستاذ|استشاري)\s+)+"
)


def doctor_key(name: str | None) -> str:
    return _TITLES.sub("", norm(name)).strip()


def _digits(text: str | None) -> str:
    return "".join(ch for ch in norm(text) if ch.isdigit())


def match_doctor(
    db: Session, name: str | None, phone: str | None = None, min_score: float = 86
) -> tuple[Doctor, float] | None:
    key = doctor_key(name)
    phone_digits = _digits(phone)
    if not key and len(phone_digits) < 7:
        return None
    best: tuple[Doctor, float] | None = None
    for doctor in db.execute(select(Doctor)).scalars():
        score = fuzz.token_set_ratio(key, doctor.name_norm) if key and doctor.name_norm else 0.0
        if len(phone_digits) >= 7 and phone_digits[-8:] == _digits(doctor.phone)[-8:]:
            score = max(score, 95.0)
        if best is None or score > best[1]:
            best = (doctor, score)
    if best and best[1] >= min_score:
        return best
    return None


def find_or_create_doctor(db: Session, name: str, specialty: str = "", clinic: str = "", phone: str = "") -> Doctor:
    found = match_doctor(db, name, phone, min_score=92)
    if found:
        doctor = found[0]
        doctor.specialty = doctor.specialty or specialty[:120]
        doctor.clinic = doctor.clinic or clinic[:200]
        doctor.phone = doctor.phone or phone[:40]
        return doctor
    doctor = Doctor(
        name=name.strip()[:160],
        name_norm=doctor_key(name)[:160],
        specialty=specialty[:120],
        clinic=clinic[:200],
        phone=phone[:40],
    )
    db.add(doctor)
    db.flush()
    return doctor


def doctor_drug_counts(db: Session, doctor_id: int | None) -> dict[int, int]:
    if not doctor_id:
        return {}
    rows = db.execute(select(DoctorDrugStat.drug_id, DoctorDrugStat.count).where(DoctorDrugStat.doctor_id == doctor_id))
    return {drug_id: count for drug_id, count in rows}


def frequent_drugs(db: Session, doctor_id: int | None, limit: int = 25) -> list[tuple[str, int]]:
    if not doctor_id:
        return []
    rows = db.execute(
        select(Drug.brand, DoctorDrugStat.count)
        .join(Drug, Drug.id == DoctorDrugStat.drug_id)
        .where(DoctorDrugStat.doctor_id == doctor_id)
        .order_by(DoctorDrugStat.count.desc(), Drug.brand)
        .limit(limit)
    )
    return [(brand, count) for brand, count in rows]


def select_fewshot(
    db: Session, blobs, keyring, doctor_id: int | None, *, limit: int, edge: int
) -> list[FewShotExample]:
    """Pick verified examples of this doctor: the hardest ones first, then the most recent."""
    if not doctor_id or limit <= 0:
        return []
    rows = (
        db.execute(
            select(Prescription)
            .where(
                Prescription.doctor_id == doctor_id,
                Prescription.status == "verified",
                Prescription.use_for_training.is_(True),
            )
            .order_by(Prescription.verified_at.desc())
            .limit(30)
        )
        .scalars()
        .all()
    )
    hard = sorted((r for r in rows if r.acc_drug is not None and r.acc_drug < 1.0), key=lambda r: r.acc_drug)
    chosen = (hard[: max(1, limit // 2)] if hard else []) + [r for r in rows if r not in hard]
    examples: list[FewShotExample] = []
    for rx in chosen[:limit]:
        result = keyring.decrypt_json(rx.verified_result_enc, f"verified:{rx.uid}") or {}
        meds = [
            {
                "drug_name": item.get("brand"),
                "strength": item.get("strength"),
                "form": item.get("form"),
                "line_text": item.get("line_text"),
                "sig_text": item.get("sig_text"),
            }
            for item in result.get("items", [])
        ]
        if not meds:
            continue
        image = resized_jpeg(blobs.get(rx.image_blob, "image"), edge)
        examples.append(FewShotExample(image_jpeg=image, medications=meds))
    return examples


def corrections_for(db: Session, doctor_id: int | None) -> dict[str, list[Correction]]:
    scopes = ["g"] + ([f"d{doctor_id}"] if doctor_id else [])
    out: dict[str, list[Correction]] = {}
    for c in db.execute(select(Correction).where(Correction.scope.in_(scopes))).scalars():
        out.setdefault(c.wrong_norm, []).append(c)
    return out


def best_correction(
    corrections: dict[str, list[Correction]], read_name: str | None, doctor_id: int | None
) -> Correction | None:
    """A doctor-specific correction wins after one sighting; a global one needs two."""
    options = corrections.get(core_name(read_name) or norm(read_name), [])
    doctor_scope = f"d{doctor_id}" if doctor_id else None
    mine = [c for c in options if c.scope == doctor_scope]
    if mine:
        return max(mine, key=lambda c: c.count)
    global_ = [c for c in options if c.scope == "g" and c.count >= 2]
    return max(global_, key=lambda c: c.count) if global_ else None


def record_correction(db: Session, doctor_id: int | None, wrong: str | None, right: str, drug_id: int | None) -> None:
    wrong_key = core_name(wrong) or norm(wrong)
    if not wrong_key or not right or wrong_key == (core_name(right) or norm(right)):
        return
    for scope in ["g"] + ([f"d{doctor_id}"] if doctor_id else []):
        row = db.execute(
            select(Correction).where(
                Correction.scope == scope,
                Correction.wrong_norm == wrong_key[:160],
                Correction.right_text == right[:160],
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(Correction(scope=scope, wrong_norm=wrong_key[:160], right_text=right[:160], drug_id=drug_id))
        else:
            row.count += 1
            row.drug_id = drug_id or row.drug_id
            row.updated_at = utcnow()
    db.flush()


def bump_doctor_drug(db: Session, doctor_id: int, drug_id: int) -> None:
    row = db.get(DoctorDrugStat, (doctor_id, drug_id))
    if row is None:
        db.add(DoctorDrugStat(doctor_id=doctor_id, drug_id=drug_id, count=1))
    else:
        row.count += 1
        row.last_at = utcnow()
    db.flush()
