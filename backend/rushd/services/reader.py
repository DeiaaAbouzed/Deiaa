"""Reading pipeline: stored image -> engine(s) -> post-processing -> encrypted result."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai import memory
from ..ai.engines import EngineError, EngineOutput, ReadContext
from ..ai.postprocess import build_result
from ..db import utcnow
from ..imaging import resized_jpeg
from ..models import Doctor, Prescription

log = logging.getLogger("rushd.reader")

MAX_ATTEMPTS = 3


@dataclass
class Outcome:
    output: EngineOutput
    doctor_id: int | None
    passes: int
    cost_usd: float
    tokens_in: int
    tokens_out: int
    shadow: EngineOutput | None = None


def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_spend(db: Session) -> float:
    total = db.execute(
        select(func.coalesce(func.sum(Prescription.cost_usd), 0.0)).where(Prescription.created_at >= month_start())
    ).scalar_one()
    return float(total or 0.0)


class Reader:
    def __init__(self, ctx):
        self.ctx = ctx
        self.attempts: dict[int, int] = {}

    # -- public ----------------------------------------------------------------
    def process(self, rx_id: int) -> bool:
        """Read one queued prescription. Returns True when it should be retried later."""
        ctx = self.ctx
        with ctx.sf() as db:
            rx = db.get(Prescription, rx_id)
            if rx is None or rx.status not in ("queued", "processing"):
                return False
            rx.status = "processing"
            db.commit()
            try:
                image = ctx.blobs.get(rx.image_blob, "image")
                cfg = ctx.store.all(db)
                outcome = self._run(db, rx, image, cfg)
                self._store(db, rx, outcome)
                self.attempts.pop(rx_id, None)
                db.commit()
                return False
            except EngineError as exc:
                db.rollback()
                rx = db.get(Prescription, rx_id)
                attempts = self.attempts.get(rx_id, 0) + 1
                self.attempts[rx_id] = attempts
                retry = exc.retryable and attempts < MAX_ATTEMPTS
                rx.status = "queued" if retry else "failed"
                rx.error = str(exc)[:400]
                rx.processed_at = utcnow()
                db.commit()
                log.warning("reading %s failed (attempt %d): %s", rx.uid, attempts, exc)
                return retry
            except Exception:
                db.rollback()
                log.exception("unexpected failure while reading prescription %s", rx_id)
                rx = db.get(Prescription, rx_id)
                rx.status = "failed"
                rx.error = "حدث خطأ غير متوقع أثناء القراءة"
                db.commit()
                return False

    # -- engines ------------------------------------------------------------------
    def _run(self, db: Session, rx: Prescription, image: bytes, cfg: dict) -> Outcome:
        ctx = self.ctx
        mode = cfg["engine_mode"]
        local = ctx.local if ctx.local is not None and getattr(ctx.local, "available", False) else None
        cloud_ready = bool(cfg["cloud_enabled"]) and ctx.claude.available
        doctor_id = rx.doctor_id if rx.doctor_confirmed else None

        if mode == "local" and local is None:
            raise EngineError("وضع القراءة محلي لكن لا يوجد نموذج محلي مُفعّل - درّب نموذجاً وفعّله من مركز التدريب")
        if mode in ("local", "local_first") and local is not None:
            out = local.read(image, self._context(db, doctor_id, fewshot=False))
            confident = out.reading.overall_confidence >= cfg["local_confidence_threshold"]
            if mode == "local" or confident or not cloud_ready or self._budget_exhausted(db, cfg):
                return Outcome(out, doctor_id, 1, 0.0, out.tokens_in, out.tokens_out)

        if not cloud_ready:
            if local is not None:
                out = local.read(image, self._context(db, doctor_id, fewshot=False))
                return Outcome(out, doctor_id, 1, 0.0, out.tokens_in, out.tokens_out)
            if not ctx.claude.available:
                raise EngineError("لم يتم إعداد مفتاح الذكاء الاصطناعي السحابي - راجع دليل التشغيل")
            raise EngineError("القراءة السحابية متوقفة من الإعدادات ولا يوجد نموذج محلي مُفعّل")
        if self._budget_exhausted(db, cfg):
            raise EngineError("تم بلوغ حد الميزانية الشهرية للقراءة السحابية - يمكن للمدير رفعه من الإعدادات")

        outcome = self._cloud(db, rx, image, cfg, doctor_id)
        if mode == "shadow" and local is not None:
            try:
                outcome.shadow = local.read(image, self._context(db, outcome.doctor_id, fewshot=False))
            except EngineError as exc:  # the shadow model must never block real work
                log.info("shadow read failed: %s", exc)
        return outcome

    def _cloud(self, db: Session, rx: Prescription, image: bytes, cfg: dict, doctor_id: int | None) -> Outcome:
        ctx = self.ctx
        s = ctx.settings
        ai_image = resized_jpeg(image, s.ai_max_edge_px, quality=90)
        kwargs = {"model": cfg["ai_model"], "effort": cfg["ai_effort"], "fallbacks": s.ai_fallbacks}

        rc = self._context(db, doctor_id, fewshot=True)
        out = ctx.claude.read(ai_image, rc, **kwargs)
        passes, cost, t_in, t_out = 1, out.cost_usd, out.tokens_in, out.tokens_out

        matched = doctor_id
        if matched is None:
            found = memory.match_doctor(db, out.reading.doctor.name, out.reading.doctor.phone)
            matched = found[0].id if found else None

        # Second look: unsure lines + a doctor we have learned from -> re-read with examples.
        if not rc.fewshot and matched and cfg["second_pass"]:
            unsure = [m for m in out.reading.medications if m.confidence < cfg["second_pass_threshold"]]
            if unsure:
                lines = [f'"{m.line_text}" (first read as {m.drug_name})' for m in unsure]
                rc2 = self._context(db, matched, fewshot=True, uncertain=lines)
                if rc2.fewshot:
                    try:
                        out2 = ctx.claude.read(ai_image, rc2, **kwargs)
                        passes, out = 2, out2
                        cost, t_in, t_out = cost + out2.cost_usd, t_in + out2.tokens_in, t_out + out2.tokens_out
                    except EngineError as exc:
                        log.info("second pass failed, keeping first reading: %s", exc)
        return Outcome(out, matched, passes, cost, t_in, t_out)

    def _context(
        self, db: Session, doctor_id: int | None, *, fewshot: bool, uncertain: list[str] | None = None
    ) -> ReadContext:
        if not doctor_id:
            return ReadContext(uncertain_lines=uncertain or [])
        s = self.ctx.settings
        doctor = db.get(Doctor, doctor_id)
        label = ""
        if doctor is not None:
            label = doctor.name + (f" - {doctor.specialty}" if doctor.specialty else "")
        examples = (
            memory.select_fewshot(
                db, self.ctx.blobs, self.ctx.keyring, doctor_id, limit=s.fewshot_max, edge=s.ai_fewshot_edge_px
            )
            if fewshot
            else []
        )
        return ReadContext(
            doctor_label=label,
            frequent_drugs=memory.frequent_drugs(db, doctor_id),
            fewshot=examples,
            uncertain_lines=uncertain or [],
        )

    def _budget_exhausted(self, db: Session, cfg: dict) -> bool:
        budget = float(cfg.get("monthly_budget_usd") or 0)
        return budget > 0 and month_spend(db) >= budget

    # -- result -------------------------------------------------------------------
    def postprocess(self, db: Session, output: EngineOutput, doctor_id: int | None) -> dict:
        lexicon = self.ctx.lexicon.get()
        result = build_result(
            output.reading,
            lexicon,
            self.ctx.class_map(),
            doctor_counts=memory.doctor_drug_counts(db, doctor_id),
            corrections=memory.corrections_for(db, doctor_id),
            doctor_id=doctor_id,
        )
        result["engine"] = output.engine
        result["model"] = output.served_by or output.model
        return result

    def _store(self, db: Session, rx: Prescription, outcome: Outcome) -> None:
        kr = self.ctx.keyring
        result = self.postprocess(db, outcome.output, outcome.doctor_id)
        result["passes"] = outcome.passes
        doctor = db.get(Doctor, outcome.doctor_id) if outcome.doctor_id else None
        result["doctor_match"] = {"id": doctor.id, "name": doctor.name} if doctor else None
        rx.ai_result_enc = kr.encrypt_json(result, f"ai:{rx.uid}")
        if outcome.shadow is not None:
            shadow = self.postprocess(db, outcome.shadow, outcome.doctor_id)
            rx.shadow_result_enc = kr.encrypt_json(shadow, f"shadow:{rx.uid}")
        if doctor and not rx.doctor_confirmed:
            rx.doctor_id = doctor.id
        rx.engine = outcome.output.engine
        rx.engine_model = (outcome.output.served_by or outcome.output.model)[:120]
        rx.passes = outcome.passes
        rx.ai_confidence = result["overall_confidence"]
        rx.num_items = len(result["items"])
        rx.tokens_in += outcome.tokens_in
        rx.tokens_out += outcome.tokens_out
        rx.cost_usd += outcome.cost_usd
        rx.error = ""
        rx.status = "needs_review"
        rx.processed_at = utcnow()
