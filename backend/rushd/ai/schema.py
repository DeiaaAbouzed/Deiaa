"""The structured reading every engine (cloud or local) must produce."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Form = Literal[
    "tablet",
    "chewable_tablet",
    "effervescent",
    "capsule",
    "syrup",
    "suspension",
    "drops",
    "sachet",
    "lozenge",
    "ampoule",
    "vial",
    "infusion",
    "prefilled_syringe",
    "pen",
    "suppository",
    "vaginal_tablet",
    "cream",
    "ointment",
    "gel",
    "lotion",
    "shampoo",
    "oral_gel",
    "eye_drops",
    "eye_ointment",
    "ear_drops",
    "nasal_spray",
    "nasal_drops",
    "inhaler",
    "nebulizer",
    "mouthwash",
    "solution",
    "other",
]
Timing = Literal["before_meal", "after_meal", "with_meal", "empty_stomach", "bedtime", "morning", "evening"]
Route = Literal[
    "oral", "eye", "ear", "nose", "topical", "inhalation", "im", "iv", "sc", "rectal", "vaginal", "sublingual"
]
Unit = Literal[
    "tablet",
    "capsule",
    "ml",
    "drop",
    "puff",
    "sachet",
    "suppository",
    "ampoule",
    "vial",
    "teaspoon",
    "tablespoon",
    "application",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DoctorInfo(_Strict):
    name: str | None = Field(None, description="Doctor's name as printed/written, original language")
    specialty: str | None = None
    clinic: str | None = Field(None, description="Clinic or hospital name / address line")
    phone: str | None = None


class PatientInfo(_Strict):
    name: str | None = Field(None, description="Patient name if written, else null")
    age: str | None = None


class Medication(_Strict):
    line_text: str = Field(description="The whole medication line transcribed exactly as written")
    drug_name: str = Field(description="Best reading of the drug (brand or generic) name, correctly spelled")
    alternatives: list[str] = Field(
        default_factory=list, description="Other plausible readings of the drug name, most likely first"
    )
    strength: str | None = Field(None, description="e.g. '1 g', '625 mg', '250 mg/5 ml'")
    form: Form | None = None
    quantity: str | None = Field(None, description="Number of packs/boxes if written")
    sig_text: str | None = Field(None, description="Dosing instruction exactly as written, e.g. '1×3 p.c. 5 days'")
    dose_amount: float | None = Field(None, description="Units per dose, e.g. 1, 0.5, 5 (ml)")
    dose_unit: Unit | None = None
    times_per_day: float | None = None
    interval_hours: float | None = None
    timing: Timing | None = None
    duration_days: float | None = None
    route: Route | None = None
    prn: bool = Field(False, description="Take only when needed")
    stat: bool = Field(False, description="Single immediate dose")
    confidence: float = Field(description="0-1: how sure you are about the drug name reading")
    illegible: str | None = Field(None, description="Which parts of this line could not be read")


class PrescriptionReading(_Strict):
    is_prescription: bool = Field(description="False if the image is not a medical prescription")
    doctor: DoctorInfo = Field(default_factory=DoctorInfo)
    patient: PatientInfo = Field(default_factory=PatientInfo)
    date: str | None = None
    diagnosis: str | None = None
    medications: list[Medication] = Field(default_factory=list)
    notes: str | None = Field(None, description="Short Arabic note to the pharmacist about anything unclear")
    overall_confidence: float = Field(description="0-1 confidence for the whole reading")
