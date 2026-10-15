"""Reader engines: the cloud vision model and the locally trained model."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field

import anthropic
from pydantic import ValidationError

from ..config import MODEL_PRICES
from . import prompts
from .schema import PrescriptionReading

log = logging.getLogger("rushd.ai")

_RESPONSE_SCHEMA = anthropic.transform_schema(PrescriptionReading.model_json_schema())


class EngineError(Exception):
    """Failure with an Arabic message that is safe to show to the user."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class FewShotExample:
    image_jpeg: bytes
    medications: list[dict]


@dataclass
class ReadContext:
    doctor_label: str = ""
    frequent_drugs: list[tuple[str, int]] = field(default_factory=list)
    fewshot: list[FewShotExample] = field(default_factory=list)
    uncertain_lines: list[str] = field(default_factory=list)


@dataclass
class EngineOutput:
    reading: PrescriptionReading
    engine: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    served_by: str = ""


def estimate_cost(model: str, usage) -> float:
    price_in, price_out, price_cache_read, price_cache_write = MODEL_PRICES.get(model, MODEL_PRICES["claude-opus-5-5"])
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        (usage.input_tokens or 0) * price_in
        + (usage.output_tokens or 0) * price_out
        + cache_read * price_cache_read
        + cache_write * price_cache_write
    ) / 1_000_000


def _image_block(jpeg: bytes) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()},
    }


class ClaudeEngine:
    """Reads a prescription with Claude vision and structured outputs."""

    name = "claude"

    def __init__(self, api_key: str | None, *, timeout: float, max_retries: int, client=None):
        self._client = client
        if self._client is None and api_key:
            self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=max_retries)

    @property
    def available(self) -> bool:
        return self._client is not None

    def build_request(self, image_jpeg: bytes, ctx: ReadContext, *, model: str, effort: str, fallbacks: bool) -> dict:
        content: list[dict] = []
        if ctx.fewshot:
            label = f" ({ctx.doctor_label})" if ctx.doctor_label else ""
            content.append({"type": "text", "text": prompts.FEWSHOT_INTRO.format(doctor=label)})
            for i, example in enumerate(ctx.fewshot, start=1):
                content.append(_image_block(example.image_jpeg))
                content.append({"type": "text", "text": prompts.format_example(i, example.medications)})
            # Consecutive prescriptions from the same doctor reuse this cached prefix.
            content[-1]["cache_control"] = {"type": "ephemeral"}
        if ctx.frequent_drugs:
            drugs = ", ".join(f"{name} ({count})" for name, count in ctx.frequent_drugs)
            content.append({"type": "text", "text": prompts.FREQUENT_DRUGS.format(drugs=drugs)})
        if ctx.uncertain_lines:
            items = "\n".join(f"- {line}" for line in ctx.uncertain_lines)
            content.append({"type": "text", "text": prompts.SECOND_LOOK.format(items=items)})
        content.append(_image_block(image_jpeg))
        content.append({"type": "text", "text": prompts.TARGET})

        request: dict = {
            "model": model,
            "max_tokens": 16000,
            "system": [{"type": "text", "text": prompts.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
        }
        # Server-side fallback keeps a false-positive safety decline from failing the read.
        # Haiku has no server-side fallback, so the parameter is pointless there.
        if fallbacks and not model.startswith("claude-haiku"):
            request["betas"] = ["server-side-fallback-2026-07-01"]
            request["fallbacks"] = "default"
        return request

    def read(self, image_jpeg: bytes, ctx: ReadContext, *, model: str, effort: str, fallbacks: bool) -> EngineOutput:
        if self._client is None:
            raise EngineError("لم يتم إعداد مفتاح خدمة الذكاء الاصطناعي السحابية (ANTHROPIC_API_KEY)")
        request = self.build_request(image_jpeg, ctx, model=model, effort=effort, fallbacks=fallbacks)
        try:
            response = self._client.beta.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise EngineError("مفتاح خدمة الذكاء الاصطناعي غير صحيح") from exc
        except anthropic.PermissionDeniedError as exc:
            raise EngineError("المفتاح لا يملك صلاحية استخدام هذا النموذج") from exc
        except anthropic.NotFoundError as exc:
            raise EngineError(f"النموذج {model} غير متاح لهذا الحساب") from exc
        except anthropic.RateLimitError as exc:
            raise EngineError("تم تجاوز حد الطلبات لدى الخدمة السحابية، سيُعاد المحاولة", retryable=True) from exc
        except anthropic.BadRequestError as exc:
            log.error("Claude rejected the request: %s", exc.message)
            raise EngineError("رفضت الخدمة السحابية الطلب (صورة غير صالحة أو إعداد خاطئ)") from exc
        except anthropic.APIStatusError as exc:
            raise EngineError("الخدمة السحابية غير متاحة مؤقتاً", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise EngineError("تعذر الاتصال بالخدمة السحابية - تحقق من الإنترنت", retryable=True) from exc

        if response.stop_reason == "refusal":
            raise EngineError("امتنع النموذج عن قراءة هذه الصورة")
        if response.stop_reason == "max_tokens":
            raise EngineError("انقطعت القراءة قبل اكتمالها، أعد المحاولة", retryable=True)
        text = next((block.text for block in response.content if block.type == "text"), None)
        if not text:
            raise EngineError("لم يرجع النموذج قراءة", retryable=True)
        try:
            reading = PrescriptionReading.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            log.warning("unparseable reading: %s", exc)
            raise EngineError("رجعت قراءة غير مكتملة، أعد المحاولة", retryable=True) from exc

        usage = response.usage
        return EngineOutput(
            reading=reading,
            engine=self.name,
            model=model,
            tokens_in=(usage.input_tokens or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
            tokens_out=usage.output_tokens or 0,
            cost_usd=estimate_cost(model, usage),
            served_by=getattr(response, "model", model) or model,
        )
