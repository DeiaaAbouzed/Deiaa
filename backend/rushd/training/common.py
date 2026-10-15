"""Pieces shared by local training and local inference.

Heavy imports (torch, transformers, peft) happen inside functions so that the
web server never pays for them unless a local model is actually used.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile

PROMPT = (
    "Read this handwritten Egyptian prescription. Reply with JSON only: "
    '{"doctor": name or null, "medications": [{"drug_name", "strength", "form", "sig_text"}]}.'
)
MIN_PIXELS = 256 * 28 * 28
MAX_PIXELS = 1280 * 28 * 28
BUNDLE_FORMAT = "rushd-lora-v1"
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def target_text(result: dict) -> str:
    """The compact JSON the local model learns to produce for a verified prescription."""
    meds = [
        {
            "drug_name": item.get("brand"),
            "strength": item.get("strength") or None,
            "form": item.get("form"),
            "sig_text": item.get("sig_text") or None,
        }
        for item in result.get("items", [])
    ]
    doctor = (result.get("doctor") or {}).get("name")
    return json.dumps({"doctor": doctor, "medications": meds}, ensure_ascii=False, separators=(",", ":"))


def messages(answer: str | None = None) -> list[dict]:
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
    if answer is not None:
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
    return msgs


def extract_json(text: str) -> dict | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None


def name_confidences(pieces: list[str], probs: list[float], text: str) -> list[float]:
    """Geometric-mean probability of the tokens that spelled each drug name."""
    offsets, pos = [], 0
    for piece in pieces:
        offsets.append((pos, pos + len(piece)))
        pos += len(piece)
    out = []
    for m in re.finditer(r'"drug_name"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
        lo, hi = m.span(1)
        span = [p for (a, b), p in zip(offsets, probs) if a < hi and b > lo and p > 0]
        if span:
            out.append(math.exp(sum(math.log(p) for p in span) / len(span)))
        else:
            out.append(sum(probs) / len(probs) if probs else 0.5)
    return out


def pick_device(preference: str = "auto"):
    import torch

    if preference != "auto":
        return torch.device(preference)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_base(base_model: str, device, revision: str | None = None):
    """Load processor + model. Never runs remote code from the model hub."""
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    if device.type == "cuda" and torch.cuda.is_bf16_supported():
        dtype = torch.bfloat16
    elif device.type == "cuda":
        dtype = torch.float16
    else:
        dtype = torch.float32
    processor = AutoProcessor.from_pretrained(base_model, revision=revision, trust_remote_code=False)
    image_processor = getattr(processor, "image_processor", None)
    if image_processor is not None and isinstance(getattr(image_processor, "size", None), dict):
        if {"shortest_edge", "longest_edge"} <= set(image_processor.size):
            image_processor.size = {"shortest_edge": MIN_PIXELS, "longest_edge": MAX_PIXELS}
    model = AutoModelForImageTextToText.from_pretrained(
        base_model, revision=revision, dtype=dtype, trust_remote_code=False
    ).to(device)
    return processor, model


def lora_config(model, rank: int = 16):
    from peft import LoraConfig

    names = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
    targets = [t for t in LORA_TARGETS if t in names] or "all-linear"
    return LoraConfig(r=rank, lora_alpha=rank * 2, lora_dropout=0.05, target_modules=targets, bias="none")


def pack_adapter(model, base_model: str, meta: dict) -> bytes:
    """Adapter weights (safetensors - no pickle, no code) + config, zipped in memory."""
    from peft import get_peft_model_state_dict
    from safetensors.torch import save

    state = {k: v.detach().contiguous().cpu() for k, v in get_peft_model_state_dict(model).items()}
    config = model.peft_config["default"].to_dict()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("meta.json", json.dumps({"format": BUNDLE_FORMAT, "base_model": base_model, **meta}, default=str))
        zf.writestr(
            "adapter_config.json", json.dumps(config, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
        )
        zf.writestr("adapter.safetensors", save(state))
    return buf.getvalue()


def unpack_adapter(bundle: bytes) -> tuple[dict, dict, bytes]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        meta = json.loads(zf.read("meta.json"))
        if meta.get("format") != BUNDLE_FORMAT:
            raise ValueError("unknown adapter bundle format")
        return meta, json.loads(zf.read("adapter_config.json")), zf.read("adapter.safetensors")


def attach_adapter(model, config: dict, weights: bytes):
    from peft import PeftConfig, get_peft_model, set_peft_model_state_dict
    from safetensors.torch import load

    peft_model = get_peft_model(model, PeftConfig.from_peft_type(**config))
    set_peft_model_state_dict(peft_model, load(weights))
    return peft_model


def generate(model, processor, image, *, max_new_tokens: int = 700) -> tuple[str, list[str], list[float]]:
    """Greedy decode; returns (text, token pieces, token probabilities)."""
    import torch

    prompt = processor.apply_chat_template(messages(), tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[prompt], images=[image], return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False, output_scores=True, return_dict_in_generate=True
        )
    new_tokens = out.sequences[0, inputs["input_ids"].shape[1] :]
    tokenizer = processor.tokenizer
    special = set(tokenizer.all_special_ids)
    pieces, probs = [], []
    for token, scores in zip(new_tokens.tolist(), out.scores):
        if token in special:
            continue
        pieces.append(tokenizer.decode([token], skip_special_tokens=True))
        probs.append(float(torch.softmax(scores[0].float(), dim=-1)[token]))
    return "".join(pieces), pieces, probs
