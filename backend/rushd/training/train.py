"""Fine-tune the pharmacy's own reading model on verified prescriptions.

Runs as a separate process started from the training center:

    python -m rushd.training.train --job-id 7

Images are decrypted one at a time in memory; the resulting LoRA adapter is
encrypted with the master key before it touches the disk.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import random
import time
from dataclasses import dataclass

from sqlalchemy import func, select

from ..ai.engines import EngineError
from ..ai.metrics import compare
from ..ai.postprocess import build_item
from ..config import Settings
from ..context import AppContext, build_context
from ..db import utcnow
from ..imaging import open_jpeg
from ..models import ModelVersion, Prescription, TrainingJob
from . import common
from .local_engine import reading_from_output

log = logging.getLogger("rushd.train")

GRAD_ACCUM = 4


class Cancelled(Exception):
    pass


@dataclass
class Sample:
    uid: str
    image_blob: str
    target: str
    items: list[dict]
    cloud_acc: float | None


def _is_eval(uid: str) -> bool:
    return int(hashlib.sha256(uid.encode()).hexdigest(), 16) % 10 == 0


class Trainer:
    def __init__(self, ctx: AppContext, job_id: int):
        self.ctx = ctx
        self.job_id = job_id
        with ctx.sf() as db:
            job = db.get(TrainingJob, job_id)
            if job is None:
                raise SystemExit(f"training job {job_id} not found")
            self.params = dict(job.params or {})

    # -- bookkeeping -----------------------------------------------------------
    def update(self, *, progress: float | None = None, message: str | None = None, **fields) -> None:
        with self.ctx.sf() as db:
            job = db.get(TrainingJob, self.job_id)
            if job.status == "cancelling":
                raise Cancelled()
            if progress is not None:
                job.progress = max(0.0, min(1.0, progress))
            if message is not None:
                job.message = message[:400]
            for key, value in fields.items():
                setattr(job, key, value)
            db.commit()

    def load_samples(self) -> list[Sample]:
        kr = self.ctx.keyring
        out: list[Sample] = []
        with self.ctx.sf() as db:
            stmt = (
                select(Prescription)
                .where(Prescription.status == "verified", Prescription.use_for_training.is_(True))
                .order_by(Prescription.verified_at.desc())
            )
            if self.params.get("max_samples"):
                stmt = stmt.limit(int(self.params["max_samples"]))
            for rx in db.execute(stmt).scalars():
                result = kr.decrypt_json(rx.verified_result_enc, f"verified:{rx.uid}") or {}
                if result.get("items"):
                    out.append(Sample(rx.uid, rx.image_blob, common.target_text(result), result["items"], rx.acc_drug))
        return out

    # -- training ----------------------------------------------------------------
    def run(self) -> None:
        self.update(status="running", started_at=utcnow(), progress=0.01, message="تجهيز بيانات التدريب")
        samples = self.load_samples()
        evals = [s for s in samples if _is_eval(s.uid)] or samples[-max(1, len(samples) // 10) :]
        eval_ids = {s.uid for s in evals}
        train = [s for s in samples if s.uid not in eval_ids] or samples
        if len(train) < 2:
            raise ValueError("بيانات التدريب غير كافية")

        import torch
        from peft import get_peft_model

        settings = self.ctx.settings
        base_model = self.params.get("base_model") or settings.local_base_model
        revision = self.params.get("revision")
        device = common.pick_device(settings.local_device)
        self.update(progress=0.03, message=f"تحميل النموذج الأساسي على {device.type}")
        processor, model = common.load_base(base_model, device, revision)
        model = get_peft_model(model, common.lora_config(model))
        if device.type == "cuda":
            model.gradient_checkpointing_enable()
            model.enable_input_require_grads()
        model.train()

        epochs = int(self.params.get("epochs", 3))
        total_steps = epochs * len(train)
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad], lr=float(self.params.get("learning_rate", 2e-4))
        )
        warmup = max(1, total_steps // (GRAD_ACCUM * 30))
        updates = max(1, math.ceil(total_steps / GRAD_ACCUM))
        scheduler = torch.optim.lr_scheduler.LambdaLR(
            optimizer,
            lambda u: min(1.0, (u + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(1.0, u / updates))),
        )

        rng = random.Random(1234)
        step = 0
        losses: list[float] = []
        started = time.monotonic()
        for epoch in range(epochs):
            order = train[:]
            rng.shuffle(order)
            for sample in order:
                loss = self._loss(model, processor, sample, device)
                (loss / GRAD_ACCUM).backward()
                losses.append(float(loss.detach()))
                step += 1
                if step % GRAD_ACCUM == 0 or step == total_steps:
                    torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
                if step % 5 == 0 or step == total_steps:
                    per_step = (time.monotonic() - started) / step
                    remaining = int(per_step * (total_steps - step) / 60) + 1
                    recent = sum(losses[-20:]) / len(losses[-20:])
                    self.update(
                        progress=0.05 + 0.8 * step / total_steps,
                        message=f"الحقبة {epoch + 1}/{epochs} - خطوة {step}/{total_steps} - الخطأ {recent:.3f} - متبقي ~{remaining} دقيقة",
                    )

        metrics = self.evaluate(model, processor, evals)
        metrics["train_loss"] = round(sum(losses[-50:]) / len(losses[-50:]), 4)
        metrics["epochs"] = epochs
        metrics["device"] = device.type
        self.update(progress=0.97, message="حفظ النموذج مشفراً")
        bundle = common.pack_adapter(model, base_model, {"revision": revision, "trained_on": len(train)})
        with self.ctx.sf() as db:
            number = (db.execute(select(func.count(ModelVersion.id))).scalar_one() or 0) + 1
            blob = self.ctx.blobs.put(db, bundle, "model")
            version = ModelVersion(
                name=f"rushd-local-v{number}",
                base_model=base_model,
                adapter_blob=blob,
                metrics=metrics,
                train_count=len(train),
                eval_count=len(evals),
            )
            db.add(version)
            db.flush()
            job = db.get(TrainingJob, self.job_id)
            job.model_version_id = version.id
            job.status = "done"
            job.progress = 1.0
            acc = metrics.get("acc_drug")
            job.message = f"اكتمل التدريب - دقة أسماء الأدوية {acc * 100:.1f}%" if acc is not None else "اكتمل التدريب"
            job.finished_at = utcnow()
            db.commit()
        self.ctx.audit.record("model_trained", target=version.name, details={"metrics": metrics})

    def _loss(self, model, processor, sample: Sample, device):
        image = open_jpeg(self.ctx.blobs.get(sample.image_blob, "image"))
        full = processor.apply_chat_template(
            common.messages(sample.target), tokenize=False, add_generation_prompt=False
        )
        prompt = processor.apply_chat_template(common.messages(), tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[full], images=[image], return_tensors="pt").to(device)
        prompt_len = processor(text=[prompt], images=[image], return_tensors="pt")["input_ids"].shape[1]
        labels = inputs["input_ids"].clone()
        labels[:, :prompt_len] = -100  # learn only the answer, not the question
        return model(**inputs, labels=labels).loss

    def evaluate(self, model, processor, evals: list[Sample]) -> dict:
        lexicon = self.ctx.lexicon.get()
        model.eval()
        accs, fields, cers, cloud = [], [], [], []
        parsed = 0
        for i, sample in enumerate(evals):
            self.update(
                progress=0.85 + 0.12 * i / max(1, len(evals)),
                message=f"تقييم النموذج على روشتات لم يرها ({i + 1}/{len(evals)})",
            )
            image = open_jpeg(self.ctx.blobs.get(sample.image_blob, "image"))
            text, pieces, probs = common.generate(model, processor, image)
            try:
                reading = reading_from_output(text, pieces, probs)
                parsed += 1
            except EngineError:
                accs.append(0.0)
                continue
            items = [
                build_item(
                    dict(m.model_dump(), read_name=m.drug_name), lexicon, doctor_counts={}, ai_confidence=m.confidence
                )
                for m in reading.medications
            ]
            result = compare(items, sample.items)
            accs.append(result.acc_drug)
            fields.append(result.acc_fields)
            cers.append(result.cer)
            if sample.cloud_acc is not None:
                cloud.append(sample.cloud_acc)
        model.train()

        def mean(xs):
            return round(sum(xs) / len(xs), 4) if xs else None

        return {
            "acc_drug": mean(accs),
            "acc_fields": mean(fields),
            "cer": mean(cers),
            "parse_rate": round(parsed / len(evals), 4) if evals else None,
            "cloud_acc_drug": mean(cloud),
            "eval_count": len(evals),
        }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Rushd local model training")
    parser.add_argument("--job-id", type=int, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ctx = build_context(Settings())
    trainer = Trainer(ctx, args.job_id)
    try:
        trainer.run()
    except Cancelled:
        _finish(ctx, args.job_id, "cancelled", "تم إيقاف التدريب")
    except Exception as exc:
        log.exception("training failed")
        message = str(exc) if str(exc) and not str(exc).isascii() else "فشل التدريب - راجع سجل التدريب"
        _finish(ctx, args.job_id, "failed", message)
        raise SystemExit(1) from exc


def _finish(ctx: AppContext, job_id: int, status: str, message: str) -> None:
    with ctx.sf() as db:
        job = db.get(TrainingJob, job_id)
        job.status = status
        job.message = message[:400]
        job.finished_at = utcnow()
        db.commit()


if __name__ == "__main__":
    main()
