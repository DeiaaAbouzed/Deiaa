"""Inference with the pharmacy's own fine-tuned model - fully offline."""

from __future__ import annotations

import importlib.util
import logging
import threading
from typing import get_args

from sqlalchemy import select

from ..ai.engines import EngineError, EngineOutput, ReadContext
from ..ai.schema import DoctorInfo, Form, Medication, PrescriptionReading
from ..imaging import open_jpeg
from ..models import ModelVersion
from . import common

log = logging.getLogger("rushd.local")

_FORMS = set(get_args(Form))


def ml_stack_installed() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers", "peft"))


def reading_from_output(text: str, pieces: list[str], probs: list[float]) -> PrescriptionReading:
    parsed = common.extract_json(text)
    if parsed is None:
        raise EngineError("النموذج المحلي لم يُرجع قراءة صالحة", retryable=False)
    confidences = common.name_confidences(pieces, probs, text)
    meds = []
    for i, raw in enumerate(parsed.get("medications") or []):
        if not isinstance(raw, dict) or not str(raw.get("drug_name") or "").strip():
            continue
        form = raw.get("form") if raw.get("form") in _FORMS else None
        meds.append(
            Medication(
                line_text="",
                drug_name=str(raw["drug_name"])[:120],
                strength=(str(raw["strength"])[:60] if raw.get("strength") else None),
                form=form,
                sig_text=(str(raw["sig_text"])[:200] if raw.get("sig_text") else None),
                confidence=round(confidences[i] if i < len(confidences) else 0.5, 3),
            )
        )
    doctor = parsed.get("doctor")
    overall = min([m.confidence for m in meds], default=0.3)
    return PrescriptionReading(
        is_prescription=True,
        doctor=DoctorInfo(name=str(doctor)[:160] if doctor else None),
        medications=meds,
        overall_confidence=overall,
    )


class LocalEngine:
    name = "local"

    def __init__(self, ctx):
        self.ctx = ctx
        self._lock = threading.Lock()
        self._loaded_version: int | None = None
        self._model = None
        self._processor = None
        self._label = ""
        self._active_id: int | None = None
        self._installed = ml_stack_installed()
        self.refresh()

    def refresh(self) -> None:
        """Re-read which model version is active (after training or activation)."""
        with self.ctx.sf() as db:
            active = db.execute(select(ModelVersion.id).where(ModelVersion.is_active.is_(True))).scalar_one_or_none()
        with self._lock:
            self._active_id = active
            if active != self._loaded_version:
                self._model = self._processor = None
                self._loaded_version = None

    @property
    def available(self) -> bool:
        return self._installed and self._active_id is not None

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._loaded_version == self._active_id:
            return
        with self.ctx.sf() as db:
            version = db.get(ModelVersion, self._active_id)
            if version is None or not version.adapter_blob:
                raise EngineError("لا يوجد نموذج محلي مُفعّل")
            bundle = self.ctx.blobs.get(version.adapter_blob, "model")  # decrypted in memory only
            name = version.name
        meta, config, weights = common.unpack_adapter(bundle)
        device = common.pick_device(self.ctx.settings.local_device)
        log.info("loading local model %s on %s", name, device)
        processor, base = common.load_base(meta["base_model"], device, meta.get("revision"))
        model = common.attach_adapter(base, config, weights).merge_and_unload()
        model.eval()
        self._model, self._processor = model, processor
        self._loaded_version = self._active_id
        self._label = name

    def read(self, image_jpeg: bytes, ctx: ReadContext) -> EngineOutput:
        if not self.available:
            raise EngineError("لا يوجد نموذج محلي مُفعّل")
        with self._lock:
            try:
                self._ensure_loaded()
                text, pieces, probs = common.generate(self._model, self._processor, open_jpeg(image_jpeg))
            except EngineError:
                raise
            except Exception as exc:  # torch / hub errors must not leak details to users
                log.exception("local model failed")
                raise EngineError("تعذر تشغيل النموذج المحلي") from exc
            reading = reading_from_output(text, pieces, probs)
            return EngineOutput(reading=reading, engine=self.name, model=self._label, tokens_out=len(pieces))
