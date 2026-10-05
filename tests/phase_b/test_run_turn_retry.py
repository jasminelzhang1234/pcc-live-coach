# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Gap 1 — orchestrator LLM retry with fallback model.

Verifies that run_turn() retries the primary model on transient failure
and falls back to llm_fallback_model on the next attempt.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import List

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.coach.orchestrator import run_turn  # noqa: E402  (used by tests below)


def _stub_chat_factory(call_log: List[str], reply_for_model: dict):
    """Build a chat() stub that records calls and returns per-model replies.

    `call_log` is appended with the model name on each invocation.
    `reply_for_model` maps model name → reply text or "RAISE" to raise.
    """
    async def stub(messages, system=None, *, model=None, **kwargs):
        call_log.append(model or "")
        spec = reply_for_model.get(model or "")
        if spec == "RAISE":
            raise httpx.ReadTimeout("simulated primary timeout")
        return spec or f"reply from {model}"
    return stub


@pytest.fixture
def patched_orchestrator(monkeypatch):
    """Patch the orchestrator module so run_turn uses our stubbed chat()."""
    from phase_b.llm import minimax_client
    from phase_b.coach import orchestrator as orch

    # Force primary = "primary-model", fallback = "fallback-model", max = 2.
    from dataclasses import replace
    from phase_b.config import get_settings
    new = replace(get_settings(), llm_model="primary-model", llm_fallback_model="fallback-model", llm_retry_max=2)
    monkeypatch.setattr("phase_b.config.get_settings", lambda: new)

    # Also patch the chat imports inside the orchestrator module.
    call_log: List[str] = []
    replies = {"primary-model": "RAISE", "fallback-model": "recovered via fallback"}
    stub = _stub_chat_factory(call_log, replies)
    monkeypatch.setattr(orch, "chat", stub)
    monkeypatch.setattr(minimax_client, "chat", stub)
    return call_log, new, stub


def test_run_turn_falls_back_to_fallback_model_on_primary_timeout(patched_orchestrator):
    call_log, settings, stub = patched_orchestrator
    from phase_b.coach.orchestrator import run_turn

    async def collect():
        events = []
        async for ev in run_turn(
            session_id="test",
            persona_id="vec-01",
            client_text="你能告诉我最近怎么样?",
        ):
            events.append(ev)
        return events

    events = asyncio.run(collect())

    # Primary should have been tried once; fallback once.
    assert "primary-model" in call_log
    assert "fallback-model" in call_log
    # And the recovered reply_text must surface.
    reply_texts = [e.get("text") for e in events if isinstance(e, dict) and e.get("kind") == "reply_text"]
    assert any(t == "recovered via fallback" for t in reply_texts)


def test_run_turn_returns_error_when_all_attempts_fail(monkeypatch):
    from phase_b.coach import orchestrator as orch
    from phase_b.llm import minimax_client
    from phase_b.config import get_settings
    from dataclasses import replace

    # Both models raise; max_attempts caps at 2.
    new = replace(get_settings(), llm_model="primary-model", llm_fallback_model="fallback-model", llm_retry_max=2)
    monkeypatch.setattr("phase_b.config.get_settings", lambda: new)

    async def stub(messages, system=None, *, model=None, **kwargs):
        raise httpx.ConnectError("simulated network down")
    monkeypatch.setattr(orch, "chat", stub)
    monkeypatch.setattr(minimax_client, "chat", stub)

    async def collect():
        events = []
        async for ev in run_turn(session_id="test", persona_id="vec-01", client_text="hi"):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    # Expect exactly one {"kind":"error", "stage":"llm"} event.
    errors = [e for e in events if isinstance(e, dict) and e.get("kind") == "error"]
    assert len(errors) == 1
    assert errors[0]["stage"] == "llm"


def test_run_turn_skips_fallback_when_disabled(monkeypatch):
    """Setting llm_fallback_model="" should not retry past the primary."""
    from phase_b.coach import orchestrator as orch
    from phase_b.llm import minimax_client
    from phase_b.config import get_settings
    from dataclasses import replace

    call_log: List[str] = []

    async def stub(messages, system=None, *, model=None, **kwargs):
        call_log.append(model or "")
        raise httpx.ReadTimeout("transient")

    monkeypatch.setattr(orch, "chat", stub)
    monkeypatch.setattr(minimax_client, "chat", stub)

    new = replace(get_settings(), llm_model="primary-model", llm_fallback_model="", llm_retry_max=2)
    monkeypatch.setattr("phase_b.config.get_settings", lambda: new)

    async def collect():
        events = []
        async for ev in run_turn(session_id="test", persona_id="vec-01", client_text="hi"):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    # Only primary attempted, then error.
    assert call_log == ["primary-model"]
    errors = [e for e in events if isinstance(e, dict) and e.get("kind") == "error"]
    assert len(errors) == 1
