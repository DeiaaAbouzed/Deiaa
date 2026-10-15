"""Turn a raw engine reading into the result the pharmacist reviews.

Each medication is matched to the drug database, cross-checked against the
doctor's history and past corrections, given an Arabic patient instruction,
and scored; then the whole prescription goes through the safety checks.
"""

from __future__ import annotations

from .lexicon import Candidate, DrugRecord, Lexicon
from .memory import best_correction
from .safety import check
from .schema import PrescriptionReading
from .sig import arabic_instructions, merge_sig
from .text import norm_strength

AUTO_MATCH = 82.0  # composite match score needed to snap a reading onto a known drug
RESULT_VERSION = 1


def level(confidence: float) -> str:
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _strength_ok(drug: DrugRecord, strength: str | None) -> bool | None:
    if not strength or not drug.strengths:
        return None
    wanted = norm_strength(strength)
    allowed = {norm_strength(s) for s in drug.strengths}
    if wanted in allowed:
        return True
    # "1g" written for a "1g/5ml"-style entry, or a bare number like "625"
    return any(a.startswith(wanted) or wanted.startswith(a) for a in allowed if a and wanted)


def _sig_dict(med: dict) -> dict:
    return {
        k: med.get(k)
        for k in (
            "dose_amount",
            "dose_unit",
            "times_per_day",
            "interval_hours",
            "timing",
            "duration_days",
            "route",
            "prn",
            "stat",
        )
    }


def build_item(
    med: dict,
    lexicon: Lexicon,
    *,
    doctor_counts: dict[int, int],
    corrections: dict | None = None,
    doctor_id: int | None = None,
    ai_confidence: float | None = None,
    auto_match: float = AUTO_MATCH,
) -> dict:
    """Enrich one medication (from the AI or the pharmacist's editor).

    For pharmacist-entered names ``auto_match`` is set very high: the
    pharmacist is the ground truth, so a name is only snapped onto an
    existing drug when it is essentially the same spelling.
    """
    read_name = (med.get("read_name") or med.get("drug_name") or med.get("brand") or "").strip()
    flags: list[str] = []
    candidates: dict[int, Candidate] = {}
    for i, name in enumerate([read_name, *(med.get("alternatives") or [])[:3]]):
        for cand in lexicon.match(name, doctor_counts=doctor_counts):
            cand.score -= 6 * (i > 0)  # an alternative reading is weaker evidence
            if cand.drug.id not in candidates or cand.score > candidates[cand.drug.id].score:
                candidates[cand.drug.id] = cand
    ranked = sorted(candidates.values(), key=lambda c: -c.score)

    chosen: DrugRecord | None = None
    match_score = ranked[0].score if ranked else 0.0
    forced = lexicon.get(med.get("drug_id"))
    correction = best_correction(corrections or {}, read_name, doctor_id) if corrections is not None else None
    if forced is not None:
        chosen, match_score = forced, 100.0
    elif correction is not None:
        chosen = lexicon.get(correction.drug_id)
        flags.append("learned_correction")
        match_score = 95.0
    elif ranked and ranked[0].score >= auto_match:
        chosen = ranked[0].drug
        if len(ranked) > 1 and ranked[0].score - ranked[1].score < 3 and ranked[1].drug.generic != chosen.generic:
            flags.append("ambiguous_name")

    brand = chosen.brand if chosen else (correction.right_text if correction else read_name)
    if chosen is None:
        flags.append("not_in_database")

    form = med.get("form")
    if not form and chosen and len(chosen.forms) == 1:
        form = chosen.forms[0]
    strength_ok = _strength_ok(chosen, med.get("strength")) if chosen else None
    if strength_ok is False:
        flags.append("strength_unusual")
    if chosen and form and chosen.forms and form not in chosen.forms and form != "other":
        flags.append("form_unusual")

    sig = merge_sig(_sig_dict(med), med.get("sig_text"), form)

    base = ai_confidence if ai_confidence is not None else 1.0
    if chosen is None:
        confidence = base * 0.7
    else:
        confidence = 0.6 * base + 0.4 * (match_score / 100)
    if "learned_correction" in flags:
        confidence = max(confidence, 0.85)
    if strength_ok is True:
        confidence += 0.05
    elif strength_ok is False:
        confidence -= 0.1
    if "ambiguous_name" in flags:
        confidence -= 0.1
    confidence = round(max(0.0, min(1.0, confidence)), 3)

    return {
        "line_text": med.get("line_text") or "",
        "read_name": read_name,
        "drug_id": chosen.id if chosen else None,
        "brand": brand,
        "generic": chosen.generic if chosen else "",
        "drug_class": chosen.drug_class if chosen else "",
        "strength": med.get("strength") or "",
        "form": form,
        "quantity": med.get("quantity") or "",
        "sig_text": med.get("sig_text") or "",
        "sig": sig.as_dict(),
        "instructions_ar": arabic_instructions(sig),
        "confidence": confidence,
        "level": level(confidence),
        "ai_confidence": ai_confidence,
        "match_score": round(match_score, 1),
        "candidates": [c.as_dict() for c in ranked[:5]],
        "flags": flags,
        "illegible": med.get("illegible") or "",
        "ai_index": med.get("ai_index"),
    }


def build_result(
    reading: PrescriptionReading,
    lexicon: Lexicon,
    class_map: dict[str, str],
    *,
    doctor_counts: dict[int, int],
    corrections: dict,
    doctor_id: int | None,
) -> dict:
    items = []
    for index, med in enumerate(reading.medications):
        raw = med.model_dump()
        raw["read_name"] = med.drug_name
        raw["ai_index"] = index
        items.append(
            build_item(
                raw,
                lexicon,
                doctor_counts=doctor_counts,
                corrections=corrections,
                doctor_id=doctor_id,
                ai_confidence=_clamp(med.confidence),
            )
        )
    overall = min([_clamp(reading.overall_confidence)] + [i["confidence"] for i in items])
    return {
        "version": RESULT_VERSION,
        "is_prescription": reading.is_prescription,
        "doctor": reading.doctor.model_dump(),
        "patient": reading.patient.model_dump(),
        "date": reading.date,
        "diagnosis": reading.diagnosis,
        "notes": reading.notes or "",
        "overall_confidence": round(overall, 3),
        "items": items,
        "warnings": check(items, class_map),
    }


def _clamp(value: float | None) -> float:
    if value is None:
        return 0.5
    return max(0.0, min(1.0, float(value)))
