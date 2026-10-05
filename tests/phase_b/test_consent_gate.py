# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Gap 2 — SessionRecorder consent gate unit tests.

Verifies that:
- write_audio() is a no-op before grant_consent()
- grant_consent() opens WAV + dialogue files
- write_dialogue() warns + drops before consent
- manager.start() no longer auto-opens the recorder
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.session.manager import SessionManager  # noqa: E402
from phase_b.session.recorder import SessionRecorder  # noqa: E402


def test_recorder_write_audio_silent_before_consent(tmp_path: Path):
    r = SessionRecorder(tmp_path, "smoke")
    assert r.consent_granted is False
    r.write_audio(b"\x00\x00" * 100)
    assert r.audio_bytes() == 0, "no bytes must be written before consent"
    assert Path(r.audio_path).exists() is False, "WAV must not exist before consent"


def test_recorder_grant_consent_opens_files(tmp_path: Path):
    r = SessionRecorder(tmp_path, "smoke")
    r.grant_consent()
    assert r.consent_granted is True
    assert Path(r.audio_path).exists() is True
    assert Path(r.dialogue_path).exists() is True
    r.write_audio(b"\x00\x00" * 100)
    assert r.audio_bytes() == 200
    r.close()


def test_recorder_grant_consent_idempotent(tmp_path: Path):
    r = SessionRecorder(tmp_path, "smoke")
    r.grant_consent()
    r.grant_consent()  # second call is a no-op
    assert r.consent_granted is True
    r.write_audio(b"\x00\x00" * 50)
    assert r.audio_bytes() == 100  # would be 200 if a second WAV got opened


def test_recorder_open_is_alias_for_grant_consent(tmp_path: Path):
    """Backward-compat: legacy code (and tests) calling open() still works."""
    r = SessionRecorder(tmp_path, "smoke")
    r.open()
    assert r.consent_granted is True
    assert Path(r.audio_path).exists() is True


def test_recorder_write_dialogue_warns_before_consent(tmp_path: Path, caplog):
    r = SessionRecorder(tmp_path, "smoke")
    with caplog.at_level("WARNING"):
        r.write_dialogue({"role": "coach", "event": "utterance", "turn": 1, "text": "hi", "ms": 0})
    assert Path(r.dialogue_path).exists() is False
    assert any("consent" in rec.message.lower() for rec in caplog.records), (
        "expected a warning about missing consent"
    )


def test_manager_start_does_not_auto_open_recorder(tmp_path: Path):
    """Gap 2: manager.start() creates a session but does NOT open files."""
    mgr = SessionManager(sessions_dir=str(tmp_path))
    state = mgr.start("vec-01", topic="probe", difficulty=1)
    r = state.recorder
    assert r.consent_granted is False
    assert Path(r.audio_path).exists() is False
    assert Path(r.dialogue_path).exists() is False


def test_manager_mark_consented_opens_and_writes_session_start(tmp_path: Path):
    mgr = SessionManager(sessions_dir=str(tmp_path))
    state = mgr.start("vec-01", topic="x", difficulty=2)
    ok = mgr.mark_consented(state.id)
    assert ok is True
    r = state.recorder
    assert r.consent_granted is True
    assert Path(r.audio_path).exists() is True
    # session_start marker should be the first dialogue line.
    content = Path(r.dialogue_path).read_text(encoding="utf-8")
    import json
    first = json.loads(content.splitlines()[0])
    assert first["event"] == "session_start"
    assert first["session_id"] == state.id
    assert first["persona_id"] == "vec-01"


def test_manager_mark_consented_unknown_session(tmp_path: Path):
    mgr = SessionManager(sessions_dir=str(tmp_path))
    assert mgr.mark_consented("nope") is False
