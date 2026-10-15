"""Builds a tiny, randomly initialised Qwen2-VL checkpoint on disk.

It exercises exactly the same transformers/PEFT code paths as the real base
model, but trains in seconds on a CPU and needs no internet access.
"""

from __future__ import annotations

from pathlib import Path

SPECIAL = [
    "<|endoftext|>",
    "<|im_start|>",
    "<|im_end|>",
    "<|vision_start|>",
    "<|vision_end|>",
    "<|image_pad|>",
    "<|video_pad|>",
]
CHAT_TEMPLATE = (
    "{% for message in messages %}<|im_start|>{{ message['role'] }}\n"
    "{% if message['content'] is string %}{{ message['content'] }}{% else %}{% for c in message['content'] %}"
    "{% if c['type'] == 'image' %}<|vision_start|><|image_pad|><|vision_end|>{% elif c['type'] == 'text' %}{{ c['text'] }}{% endif %}"
    "{% endfor %}{% endif %}<|im_end|>\n{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}"
)


def build(path: Path, corpus: list[str]) -> Path:
    import torch
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import (
        AutoModelForImageTextToText,
        PreTrainedTokenizerFast,
        Qwen2VLConfig,
        Qwen2VLProcessor,
    )
    from transformers.models.qwen2_vl.image_processing_qwen2_vl import (
        Qwen2VLImageProcessor,
    )
    from transformers.models.qwen2_vl.video_processing_qwen2_vl import (
        Qwen2VLVideoProcessor,
    )

    torch.manual_seed(0)
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=700, special_tokens=SPECIAL, initial_alphabet=pre_tokenizers.ByteLevel.alphabet()
    )
    tok.train_from_iterator(corpus * 20, trainer)
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=tok, eos_token="<|im_end|>", pad_token="<|endoftext|>")
    processor = Qwen2VLProcessor(
        image_processor=Qwen2VLImageProcessor(min_pixels=56 * 56, max_pixels=28 * 28 * 16),
        tokenizer=tokenizer,
        video_processor=Qwen2VLVideoProcessor(),
        chat_template=CHAT_TEMPLATE,
    )
    ids = {t: tokenizer.convert_tokens_to_ids(t) for t in SPECIAL}
    config = Qwen2VLConfig(
        text_config=dict(
            vocab_size=len(tokenizer),
            hidden_size=64,
            intermediate_size=128,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=4096,
            rope_scaling={"type": "mrope", "mrope_section": [4, 2, 2]},
            bos_token_id=None,
            eos_token_id=ids["<|im_end|>"],
            pad_token_id=ids["<|endoftext|>"],
        ),
        vision_config=dict(
            depth=1,
            embed_dim=32,
            hidden_size=64,
            num_heads=2,
            mlp_ratio=2,
            patch_size=14,
            spatial_merge_size=2,
            in_channels=3,
            temporal_patch_size=2,
        ),
        image_token_id=ids["<|image_pad|>"],
        video_token_id=ids["<|video_pad|>"],
        vision_start_token_id=ids["<|vision_start|>"],
    )
    model = AutoModelForImageTextToText.from_config(config)
    model.generation_config.eos_token_id = ids["<|im_end|>"]
    model.generation_config.pad_token_id = ids["<|endoftext|>"]
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(path)
    processor.save_pretrained(path)
    return path
