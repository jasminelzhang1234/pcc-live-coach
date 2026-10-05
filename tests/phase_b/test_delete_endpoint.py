# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Gap 2 — DELETE /api/session/{id}/audio + GET /api/sessions endpoint tests."""
from __future__ import annotations

import json
import sys
import types
import wave
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# Stub the `nls` + aliyun SDKs so router imports cleanly under pytest
# (mirrors the pattern in test_assess.py — these tests don't exercise ASR).
if "nls" not in sys.modules:
    _nls_stub = types.ModuleType("nls")
    _nls_stub.NlsSpeechTranscriber = type("NlsSpeechTranscriber", (), {})
    sys.modules["nls"] = _nls_stub
_aliyun_pkg = "alibabacloud_nls_cloud_meta20190228"
if _aliyun_pkg not in sys.modules:
    _aliyun_mod = types.ModuleType(_aliyun_pkg)
    _client_mod = types.ModuleType(f"{_aliyun_pkg}.client")
    _client_mod.Client = type("Client", (), {})
    sys.modules[_aliyun_pkg] = _aliyun_mod
    sys.modules[f"{_aliyun_pkg}.client"] = _client_mod
_tea_pkg = "alibabacloud_tea_openapi"
if _tea_pkg not in sys.modules:
    _tea_mod = types.ModuleType(_tea_pkg)
    _tea_models = types.ModuleType(f"{_tea_pkg}.models")
    _tea_models.Config = type("Config", (), {})
    sys.modules[_tea_pkg] = _tea_mod
    sys.modules[f"{_tea_pkg}.models"] = _tea_models


@pytest.fixture
def client_with_session(tmp_path, monkeypatch):
    """Spin up the FastAPI app with a fake manager that has a consented session."""
    from fastapi.testclient import TestClient
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder

    # Resolve tmp_path up-front so manager._sessions_dir.resolve() and the
    # recorder's WAV path both end up under the same root (pytest tmp_path
    # is often a /var/folders symlink that .resolve() would canonicalize).
    sessions_dir = (tmp_path / "sessions").resolve()
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    # Use real-* prefix so list_sessions(with_audio=true) glob matches.
    SID = "real-test-001"
    recorder = SessionRecorder(sessions_dir, SID)
    recorder.grant_consent()
    # Write some PCM so the wav is non-empty.
    with wave.open(str(recorder.audio_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)  # 1 second
    recorder.close()
    Path(recorder.dialogue_path).write_text(
        json.dumps({"role": "_meta", "event": "session_start", "session_id": SID}) + "\n"
    )

    state = SessionState(
        session_id=SID,
        persona_id="vec-01",
        topic="demo",
        difficulty=2,
        recorder=recorder,
        started_ms=1000,
    )
    mgr._sessions[SID] = state

    from phase_b.wire import router as router_mod
    orig = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    try:
        from phase_b.server import app
        with TestClient(app) as c:
            yield c, mgr, state
    finally:
        router_mod.get_manager = orig


def test_delete_audio_removes_wav_but_keeps_dialogue(client_with_session):
    c, mgr, state = client_with_session
    audio_p = Path(state.recorder.audio_path)
    dlg_p = Path(state.recorder.dialogue_path)
    assert audio_p.exists()
    assert dlg_p.exists()

    r = c.delete(f"/api/session/{state.id}/audio")

    assert r.status_code == 204
    assert audio_p.exists() is False, "WAV must be deleted"
    assert dlg_p.exists() is True, "dialogue JSONL must survive"


def test_delete_audio_unknown_session_404(client_with_session):
    c, _mgr, _state = client_with_session
    r = c.delete("/api/session/nope/audio")
    assert r.status_code == 404


def test_delete_audio_idempotent_when_wav_missing(client_with_session, tmp_path):
    """Calling DELETE on a session with no WAV file still returns 204."""
    c, mgr, state = client_with_session
    Path(state.recorder.audio_path).unlink()  # pre-delete
    r = c.delete(f"/api/session/{state.id}/audio")
    assert r.status_code == 204


def test_list_sessions_includes_in_memory(client_with_session):
    c, _mgr, state = client_with_session
    r = c.get("/api/sessions")
    assert r.status_code == 200
    data = r.json()
    sids = [s["id"] for s in data["sessions"]]
    assert state.id in sids


def test_list_sessions_with_audio_scans_disk(client_with_session, tmp_path):
    """with_audio=true picks up sessions no longer in memory (on-disk-only)."""
    c, mgr, state = client_with_session
    mgr._sessions.pop(state.id, None)
    Path(state.recorder.dialogue_path).unlink(missing_ok=True)
    # Sanity: WAV still exists on disk after dropping from memory.
    assert Path(state.recorder.audio_path).exists()

    r = c.get("/api/sessions?with_audio=true")
    assert r.status_code == 200
    sids = [s["id"] for s in r.json()["sessions"]]
    assert state.id in sids
    entry = next(s for s in r.json()["sessions"] if s["id"] == state.id)
    assert entry.get("on_disk_only") is True
