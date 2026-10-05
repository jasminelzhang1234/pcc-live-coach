# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Gap 3 — LLM/ASR cost calculation + CSV column flow unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402

from phase_b.llm.cost import (  # noqa: E402
    asr_cost_usd,
    llm_cost_usd,
    session_cost,
    _normalize_model,
)


class TestNormalizeModel:
    def test_strips_date_suffix(self):
        # 8-digit trailing components are stripped.
        assert _normalize_model("MiniMax-M3-20251015") == "MiniMax-M3"
        assert _normalize_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"

    def test_passthrough_without_date(self):
        assert _normalize_model("MiniMax-M3") == "MiniMax-M3"
        assert _normalize_model("claude-sonnet-4-5") == "claude-sonnet-4-5"

    def test_empty(self):
        assert _normalize_model("") == ""


class TestLLMCost:
    def test_minimax_m3_basic(self):
        # 1M input + 1M output = $3.00 + $15.00 = $18.00
        cost = llm_cost_usd("MiniMax-M3", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == 18.0

    def test_minimax_m3_realistic_session(self):
        # 45 min session, ~15 turns, ~1500 tokens/turn each side.
        # 15 * 1500 = 22500 input + 22500 output
        cost = llm_cost_usd(
            "MiniMax-M3", input_tokens=22_500, output_tokens=22_500,
        )
        # 0.0225 * 3 + 0.0225 * 15 = 0.0675 + 0.3375 = 0.405
        assert abs(cost - 0.405) < 0.001

    def test_normalizes_date_suffix(self):
        # Same price with or without date.
        a = llm_cost_usd("MiniMax-M3", 1_000_000, 1_000_000)
        b = llm_cost_usd("MiniMax-M3-20251015", 1_000_000, 1_000_000)
        assert a == b

    def test_unknown_model_returns_zero(self):
        assert llm_cost_usd("unknown-model-xyz", 1_000_000, 1_000_000) == 0.0

    def test_empty_model_returns_zero(self):
        assert llm_cost_usd("", 1_000_000, 1_000_000) == 0.0


class TestASRCost:
    def test_basic(self):
        # 45 minutes ≈ $0.27
        cost = asr_cost_usd(45.0)
        assert abs(cost - 0.27) < 0.001

    def test_zero_minutes(self):
        assert asr_cost_usd(0) == 0.0


class TestSessionCost:
    def test_returns_tuple(self):
        llm, asr = session_cost(
            "MiniMax-M3", input_tokens=22_500, output_tokens=22_500, audio_minutes=45.0,
        )
        assert abs(llm - 0.405) < 0.001
        assert abs(asr - 0.27) < 0.001


class TestCSVAppendGap3:
    """Verify the new cost columns flow through build_row + append_row."""

    def test_build_row_includes_cost_columns(self, tmp_path):
        from phase_b.tracker.csv_append import _load_header, build_row, append_row

        # Write a 101-col header (95 + 6 Gap 3 columns).
        header = (
            ["session_id", "date", "conversation_date", "conversation_time", "reeval_of",
             "persona", "difficulty", "topic", "judge_main", "judge_2",
             "source_type", "audio_path", "transcript_path", "audio_quality_notes",
             "llm_input_tokens", "llm_output_tokens", "llm_model_used", "llm_cost_usd",
             "asr_minutes", "asr_cost_usd"]
            + [f"claude_{i}" for i in range(40)]
            + [f"deepseek_{i}" for i in range(40)]
            + ["claude_total_✔", "claude_total_△", "claude_total_✘",
               "must_hit_✘_count", "key_weakness", "claude_deepseek_agreement",
               "eval_version"]
        )
        # Pad to the actual built length (107 with the columns above).
        target_len = len(header)
        assert target_len > 95, "should have more than 95 cols after additions"

        csv = tmp_path / "tracker.csv"
        with open(csv, "w", newline="", encoding="utf-8") as f:
            import csv as _csv
            w = _csv.writer(f)
            w.writerow(header)

        loaded = _load_header(csv)
        row = build_row(
            session_id="real-2026-10-05-01",
            persona="vec-01",
            difficulty=2,
            topic="压力管理",
            audio_path="raw/real-2026-10-05-01.wav",
            transcript_path="dialogues/real-2026-10-05-01.jsonl",
            header=loaded,
            llm_input_tokens=22_500,
            llm_output_tokens=22_500,
            llm_model_used="MiniMax-M3",
            asr_minutes=45.0,
        )
        assert row["llm_input_tokens"] == "22500"
        assert row["llm_output_tokens"] == "22500"
        assert row["llm_model_used"] == "MiniMax-M3"
        assert row["asr_minutes"] == "45.000"
        # Cost ≈ 0.405 for MiniMax-M3 at 22.5K in + 22.5K out
        assert abs(float(row["llm_cost_usd"]) - 0.405) < 0.001
        # ASR cost ≈ 0.27 for 45 min
        assert abs(float(row["asr_cost_usd"]) - 0.27) < 0.001
