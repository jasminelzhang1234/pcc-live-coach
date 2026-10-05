# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
"""Regression tests for P2-2: SessionManager.end() orphan-cleanup fast path.

Locks the contract that a 0-audio, 0-turn session (start → end with no
recording and no utterance) leaves no audio/dialogue/rhythm artifacts
AND skips the tracker CSV row append, while a real session (any audio
byte or any utterance) keeps its artifacts and is appended as before.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.session.manager import SessionManager  # noqa: E402
from phase_b.session.recorder import SessionRecorder  # noqa: E402


@pytest.fixture
def mgr(tmp_path: Path) -> SessionManager:
    """Fresh SessionManager rooted in a tmp dir so tests don't pollute."""
    return SessionManager(sessions_dir=str(tmp_path))


def _csv_lines(mgr: SessionManager) -> int:
    """Count rows the manager has appended to its tracker CSV."""
    from phase_b.config import get_settings
    csv_path = Path(get_settings().tracker_csv)
    if not csv_path.is_absolute():
        csv_path = PROJECT_ROOT / csv_path
    return sum(1 for _ in csv_path.open()) if csv_path.is_file() else 0


def _existing(probe_state) -> dict:
    return {
        "wav": Path(probe_state.recorder.audio_path).is_file(),
        "dlg": Path(probe_state.recorder.dialogue_path).is_file(),
        "rhythm": Path(probe_state.recorder.rhythm_path).is_file(),
    }


# ---- probe: 0 audio + 0 turn → artifacts gone, CSV unchanged --------------


def test_probe_session_unlinks_artifacts_and_skips_csv(mgr: SessionManager):
    before = _csv_lines(mgr)
    state = mgr.start("vec-01", topic="probe", difficulty=1)
    mgr.end(state.id)
    assert _existing(state) == {"wav": False, "dlg": False, "rhythm": False}, (
        "0-turn probe must not leave artifacts on disk"
    )
    assert _csv_lines(mgr) == before, "0-turn probe must not append to tracker CSV"


# ---- real session: at least one utterance → artifacts kept, CSV appended --


def test_real_session_keeps_artifacts_and_appends_csv(mgr: SessionManager):
    before = _csv_lines(mgr)
    state = mgr.start("vec-01", topic="real", difficulty=2)
    # Gap 2: grant_consent opens the recorder (test bypasses WS handshake).
    state.recorder.grant_consent()
    # Synthesize a tiny utterance — even without audio bytes, the dialogue
    # line is enough to mark this as a real session.
    state.recorder.write_dialogue({
        "role": "client",
        "event": "utterance",
        "turn": 1,
        "text": "probe text",
        "ms": 0,
    })
    mgr.end(state.id)
    assert _existing(state) == {"wav": True, "dlg": True, "rhythm": True}, (
        "real session must keep all three artifacts"
    )
    assert _csv_lines(mgr) == before + 1, (
        "real session must append exactly one tracker CSV row"
    )


# ---- real session: only audio, no utterance → still kept (defensive) -------


def test_audio_only_session_kept(mgr: SessionManager):
    before = _csv_lines(mgr)
    state = mgr.start("vec-01", topic="audio-only", difficulty=2)
    # Gap 2: grant_consent opens the recorder (test bypasses WS handshake).
    state.recorder.grant_consent()
    state.recorder.write_audio(b"\x00\x00" * 800)  # 50ms of silence
    mgr.end(state.id)
    assert _existing(state) == {"wav": True, "dlg": True, "rhythm": True}
    assert _csv_lines(mgr) == before + 1


# ---- recorder exposes audio_bytes() ---------------------------------------


def test_recorder_audio_bytes_starts_at_zero():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = SessionRecorder(Path(d), "smoke")
        r.open()
        assert r.audio_bytes() == 0
        r.write_audio(b"\x00\x00" * 100)
        assert r.audio_bytes() == 200
        r.close()