# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
"""Regression tests for P0-2: difficulty override wiring.

Locks the contract that the UI-selected difficulty reaches the LLM prompt:
- no override → persona's hardcoded difficulty
- user value matches persona → simple "难度: N"
- user value differs → "难度: N (用户选择) / persona 推荐: M"
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.coach.orchestrator import _build_system_prompt  # noqa: E402


# ---- no override: persona frontmatter wins ---------------------------------


def test_no_override_uses_persona_difficulty():
    prompt = _build_system_prompt("vec-01")  # vec-01 frontmatter 难度: 2
    # The "难度:" line must reference 2, with no "(用户选择)" suffix.
    lines = [ln for ln in prompt.splitlines() if ln.startswith("难度:")]
    assert lines, "expected a 难度: line in the prompt"
    assert lines[0] == "难度: 2"


# ---- match: concise form ---------------------------------------------------


def test_override_matches_persona_still_simple():
    prompt = _build_system_prompt("vec-01", user_difficulty=2)
    lines = [ln for ln in prompt.splitlines() if ln.startswith("难度:")]
    assert lines[0] == "难度: 2"
    assert "用户选择" not in prompt


# ---- mismatch: surfaced for LLM --------------------------------------------


def test_override_mismatch_surfaces_both_values():
    prompt = _build_system_prompt("vec-01", user_difficulty=1)  # vec-01 = 2
    lines = [ln for ln in prompt.splitlines() if ln.startswith("难度:")]
    assert len(lines) == 1
    line = lines[0]
    assert "1 (用户选择)" in line, f"missing user-choice annotation: {line!r}"
    assert "persona 推荐: 2" in line, f"missing persona recommendation: {line!r}"


def test_override_mismatch_with_higher_value():
    # vec-02 frontmatter 难度: 3; user picks 1.
    prompt = _build_system_prompt("vec-02", user_difficulty=1)
    line = next(ln for ln in prompt.splitlines() if ln.startswith("难度:"))
    assert "1 (用户选择)" in line
    assert "persona 推荐: 3" in line


# ---- run_turn signature ---------------------------------------------------


def test_run_turn_accepts_user_difficulty_kwarg():
    # If the kwarg were removed, every caller (router, smoke tests) breaks.
    from phase_b.coach.orchestrator import run_turn
    import inspect
    sig = inspect.signature(run_turn)
    assert "user_difficulty" in sig.parameters
    assert sig.parameters["user_difficulty"].default == 0