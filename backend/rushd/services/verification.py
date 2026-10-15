"""Pharmacist verification: the moment the system learns."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..ai import memory
from ..ai.metrics import compare
from ..ai.postprocess import RESULT_VERSION, build_item
from ..ai.safety import check
from ..ai.text import core_name
from ..api.errors import ApiError
from ..db import utcnow
from ..models import Doctor, Prescription
from . import drugs as drug_service

VERIFIED_MATCH = 96.0


def _resolve_doctor(db: Session, doctor: dict | None) -> Doctor | None:
    if not doctor:
        return None
    if doctor.get("id"):
        found = db.get(Doctor, int(doctor["id"]))
        if found is None:
            raise ApiError(400, "الطبيب المحدد غير موجود")
        return found
    name = (doctor.get("name") or "").strip()
    if not name:
        return None
    return memory.find_or_create_doctor(
        db, name, doctor.get("specialty") or "", doctor.get("clinic") or "", doctor.get("phone") or ""
    )


def build_verified_items(db: Session, ctx, raw_items: list[dict], add_unknown: bool) -> list[dict]:
    lexicon = ctx.lexicon.get()
    items: list[dict] = []
    created_any = False
    for raw in raw_items:
        brand = (raw.get("brand") or "").strip()
        if not brand:
            continue
        med = dict(raw, read_name=brand)
        if med.get("drug_id") and lexicon.get(med["drug_id"]) is None:
            med["drug_id"] = None
        item = build_item(med, lexicon, doctor_counts={}, auto_match=VERIFIED_MATCH)
        if item["drug_id"] is None and add_unknown:
            drug, created = drug_service.upsert(
                db, {"brand": brand, "forms": [raw["form"]] if raw.get("form") else []}, "learned"
            )
            if drug is not None:
                db.flush()
                created_any = created_any or created
                item["drug_id"] = drug.id
                item["flags"] = [f for f in item["flags"] if f != "not_in_database"] + (["new_drug"] if created else [])
        item["ai_index"] = raw.get("ai_index")
        items.append(item)
    if created_any:
        ctx.drugs_changed()
    return items


def verify(db: Session, ctx, rx: Prescription, body: dict, user, ip: str, *, can_approve_academy: bool) -> dict:
    kr = ctx.keyring
    already = rx.status == "verified"
    ai_result = kr.decrypt_json(rx.ai_result_enc, f"ai:{rx.uid}") or {}
    ai_items = ai_result.get("items", [])

    doctor = _resolve_doctor(db, body.get("doctor"))
    items = build_verified_items(db, ctx, body.get("items") or [], body.get("add_unknown_drugs", True))
    if not items:
        raise ApiError(400, "أضف دواءً واحداً على الأقل أو ارفض الروشتة إن لم تكن صالحة")

    patient = body.get("patient") or {}
    result = {
        "version": RESULT_VERSION,
        "is_prescription": True,
        "doctor": {
            "name": doctor.name if doctor else (body.get("doctor") or {}).get("name"),
            "specialty": doctor.specialty if doctor else None,
            "clinic": doctor.clinic if doctor else None,
            "phone": doctor.phone if doctor else None,
        },
        "patient": {"name": (patient.get("name") or "")[:120] or None, "age": (patient.get("age") or "")[:20] or None},
        "date": ai_result.get("date"),
        "diagnosis": ai_result.get("diagnosis"),
        "notes": (body.get("notes") or "")[:500],
        "items": items,
        "warnings": check(items, ctx.class_map()),
        "verified_by": user.username,
    }
    rx.verified_result_enc = kr.encrypt_json(result, f"verified:{rx.uid}")

    comparison = compare(ai_items, items) if ai_items else None
    if comparison is not None:
        rx.acc_drug = round(comparison.acc_drug, 4)
        rx.acc_fields = round(comparison.acc_fields, 4)
        rx.cer = round(comparison.cer, 4)
        rx.items_changed = comparison.items_changed
    if rx.shadow_result_enc:
        shadow = kr.decrypt_json(rx.shadow_result_enc, f"shadow:{rx.uid}") or {}
        if shadow.get("items") is not None:
            rx.shadow_acc_drug = round(compare(shadow["items"], items).acc_drug, 4)

    if not already:  # learn once per prescription
        doctor_id = doctor.id if doctor else None
        if comparison is not None:
            for ai_i, vi in comparison.pairs:
                ai_item, truth = ai_items[ai_i], items[vi]
                misread = core_name(ai_item.get("read_name")) != core_name(truth["brand"])
                if not comparison.name_correct.get(vi) or (misread and ai_item.get("level") != "high"):
                    memory.record_correction(db, doctor_id, ai_item.get("read_name"), truth["brand"], truth["drug_id"])
        if doctor is not None:
            for item in items:
                if item["drug_id"]:
                    memory.bump_doctor_drug(db, doctor.id, item["drug_id"])
            doctor.verified_count += 1
            doctor.last_seen_at = utcnow()

    if doctor is not None:
        rx.doctor_id = doctor.id
        rx.doctor_confirmed = True
    rx.num_items = len(items)
    rx.status = "verified"
    rx.error = ""  # a failed reading that was typed in manually
    rx.verified_at = utcnow()
    rx.verified_by = user.id
    rx.use_for_training = bool(body.get("use_for_training", True))
    if can_approve_academy:
        rx.academy_approved = bool(body.get("academy_approved", False))
    db.commit()
    ctx.audit.record(
        "prescription_verified" if not already else "prescription_reverified",
        user_id=user.id,
        username=user.username,
        ip=ip,
        target=rx.uid,
        details={"items": len(items), "acc_drug": rx.acc_drug},
    )
    return result
