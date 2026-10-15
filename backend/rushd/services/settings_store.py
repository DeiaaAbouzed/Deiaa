"""Administrator-editable runtime settings, stored in the database."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from ..config import MODEL_PRICES, Settings
from ..db import utcnow
from ..models import Setting

ENGINE_MODES = ("cloud", "local", "local_first", "shadow")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _choice(options) -> Callable[[Any], Any]:
    def check(value):
        if value not in options:
            raise ValueError(f"القيمة يجب أن تكون واحدة من: {', '.join(options)}")
        return value

    return check


def _number(lo: float, hi: float, cast=float) -> Callable[[Any], Any]:
    def check(value):
        try:
            value = cast(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("قيمة رقمية غير صالحة") from exc
        if not lo <= value <= hi:
            raise ValueError(f"القيمة يجب أن تكون بين {lo} و {hi}")
        return value

    return check


def _bool(value):
    if isinstance(value, bool):
        return value
    raise ValueError("القيمة يجب أن تكون نعم/لا")


def _text(max_len: int) -> Callable[[Any], Any]:
    def check(value):
        if not isinstance(value, str) or len(value) > max_len:
            raise ValueError(f"نص بحد أقصى {max_len} حرف")
        return value.strip()

    return check


class SettingsStore:
    def __init__(self, settings: Settings):
        self.defaults: dict[str, Any] = {
            "engine_mode": "cloud",
            "cloud_enabled": True,
            "ai_model": settings.ai_model,
            "ai_effort": settings.ai_effort,
            "second_pass": True,
            "second_pass_threshold": 0.75,
            "local_confidence_threshold": 0.85,
            "monthly_budget_usd": 0.0,
            "reads_per_user_per_day": 300,
            "pharmacy_name": "",
            "label_footer": "مع تمنياتنا بالشفاء العاجل",
            "academy_enabled": True,
        }
        models = tuple(MODEL_PRICES) + ((settings.ai_model,) if settings.ai_model not in MODEL_PRICES else ())
        self.validators: dict[str, Callable[[Any], Any]] = {
            "engine_mode": _choice(ENGINE_MODES),
            "cloud_enabled": _bool,
            "ai_model": _choice(models),
            "ai_effort": _choice(EFFORTS),
            "second_pass": _bool,
            "second_pass_threshold": _number(0.0, 1.0),
            "local_confidence_threshold": _number(0.0, 1.0),
            "monthly_budget_usd": _number(0.0, 1_000_000.0),
            "reads_per_user_per_day": _number(1, 100_000, int),
            "pharmacy_name": _text(120),
            "label_footer": _text(160),
            "academy_enabled": _bool,
        }
        self.models = models

    def all(self, db: Session) -> dict[str, Any]:
        values = dict(self.defaults)
        for row in db.query(Setting).all():
            if row.key in values:
                values[row.key] = row.value.get("v")
        return values

    def get(self, db: Session, key: str) -> Any:
        row = db.get(Setting, key)
        return row.value.get("v") if row is not None else self.defaults[key]

    def update(self, db: Session, changes: dict[str, Any], user_id: int | None) -> dict[str, Any]:
        """Validate everything first, then write; raises ValueError (Arabic message)."""
        clean: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in self.validators:
                raise ValueError(f"إعداد غير معروف: {key}")
            try:
                clean[key] = self.validators[key](value)
            except ValueError as exc:
                raise ValueError(f"{key}: {exc}") from exc
        for key, value in clean.items():
            row = db.get(Setting, key)
            if row is None:
                db.add(Setting(key=key, value={"v": value}, updated_by=user_id))
            else:
                row.value = {"v": value}
                row.updated_at = utcnow()
                row.updated_by = user_id
        db.flush()
        return clean
