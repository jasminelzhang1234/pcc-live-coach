# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""LLM / ASR cost calculation — Gap 3 (token / cost tracking).

Pricing is per-million-tokens (USD), normalized to a single `model` string
(prefix-match against model IDs with date suffixes like MiniMax-M3-20251015).

Update prices here when providers change their pricing — values are sourced
from public pricing pages (MiniMax / Anthropic / Aliyun) as of 2026-10.
"""

from __future__ import annotations

from typing import Tuple


# USD per 1M tokens. Add new models as needed.
_PRICING: dict[str, dict[str, float]] = {
    # MiniMax-M3 — primary default
    "MiniMax-M3":     {"input": 3.00,  "output": 15.00},
    "MiniMax-M2":     {"input": 1.00,  "output":  5.00},
    # OpenAI
    "gpt-4o":         {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":    {"input": 0.15,  "output":  0.60},
    # Anthropic
    "claude-sonnet-4-5":  {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":   {"input": 1.00,  "output":  5.00},
}


# Aliyun NLS streaming ASR — flat rate per minute (USD).
_ASR_USD_PER_MINUTE: float = 0.006  # ¥0.04 / min ≈ $0.006 (probe 2026-09)


def _normalize_model(model: str) -> str:
    """Strip date suffix: 'MiniMax-M3-20251015' → 'MiniMax-M3'."""
    if not model:
        return ""
    # Split on '-' and drop trailing components that look like dates (8 digits).
    parts = model.split("-")
    while len(parts) > 2 and parts[-1].isdigit() and len(parts[-1]) == 8:
        parts.pop()
    return "-".join(parts) or model


def llm_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute LLM cost in USD. Unknown model → 0 (don't fail on unknown pricing)."""
    norm = _normalize_model(model)
    tier = _PRICING.get(norm)
    if tier is None:
        return 0.0
    cost_in = (input_tokens / 1_000_000.0) * tier["input"]
    cost_out = (output_tokens / 1_000_000.0) * tier["output"]
    return round(cost_in + cost_out, 6)


def asr_cost_usd(audio_minutes: float) -> float:
    """Compute Aliyun NLS ASR cost in USD."""
    return round(audio_minutes * _ASR_USD_PER_MINUTE, 6)


def session_cost(model: str, input_tokens: int, output_tokens: int, audio_minutes: float) -> Tuple[float, float]:
    """Return (llm_cost_usd, asr_cost_usd) tuple for the whole session."""
    return llm_cost_usd(model, input_tokens, output_tokens), asr_cost_usd(audio_minutes)
