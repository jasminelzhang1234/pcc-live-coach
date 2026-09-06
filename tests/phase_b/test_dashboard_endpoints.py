# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Dashboard v2 endpoints — transcript / audio / track.

Spec: docs/superpowers/specs/2026-09-06-phase-b-dashboard-v2-design.md
Plan:  docs/superpowers/plans/2026-09-06-phase-b-dashboard-v2.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client_with_session(tmp_path):
    """Spin up the FastAPI app with a session that has dialogue JSONL."""
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    recorder = SessionRecorder(sessions_dir, "demo-001")
    recorder.open()
    state = SessionState(
        session_id="demo-001",
        persona_id="vec-01",
        topic="demo",
        difficulty=2,
        recorder=recorder,
        started_ms=1000,
    )
    # Write a minimal dialogue JSONL: session_start, two utterance pairs,
    # session_end. ms values are wall-clock; the endpoint must sort by ms
    # so coach/client order matches real wall-clock arrival.
    dialogue_path = Path(recorder.dialogue_path)
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dialogue_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "_meta", "event": "session_start",
                            "session_id": "demo-001", "started_ms": 1000,
                            "started_iso": "2026-09-06T10:00:00"}) + "\n")
        f.write(json.dumps({"role": "coach", "event": "utterance",
                            "turn": 1, "text": "最近怎么样?", "ms": 1000}) + "\n")
        f.write(json.dumps({"role": "client", "event": "utterance",
                            "turn": 1, "text": "还行吧,就是有点累。", "ms": 3000}) + "\n")
        f.write(json.dumps({"role": "coach", "event": "utterance",
                            "turn": 2, "text": "能具体说说吗?", "ms": 6500}) + "\n")
        f.write(json.dumps({"role": "client", "event": "utterance",
                            "turn": 2, "text": "工作上的事", "ms": 9000}) + "\n")
        f.write(json.dumps({"role": "_meta", "event": "session_end",
                            "session_id": "demo-001", "ended_ms": 10000}) + "\n")
    recorder.close()

    from phase_b.wire import router as router_mod
    orig_get_manager = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    mgr._sessions["demo-001"] = state

    from phase_b.server import app
    with TestClient(app) as c:
        yield c, state
    router_mod.get_manager = orig_get_manager


# ---- /api/session/{id}/transcript -----------------------------------------


def test_transcript_endpoint_returns_only_utterances(client_with_session):
    """Only event=='utterance' rows should be returned; _meta filtered out."""
    client, state = client_with_session
    r = client.get(f"/api/session/{state.id}/transcript")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session_id"] == state.id
    turns = data["turns"]
    # 4 utterance rows in fixture, sorted by ms.
    assert len(turns) == 4
    # No _meta entries.
    assert all("turn" in t for t in turns)
    assert all(t["role"] in ("coach", "client") for t in turns)


def test_transcript_endpoint_alternates_coach_client(client_with_session):
    client, state = client_with_session
    r = client.get(f"/api/session/{state.id}/transcript")
    turns = r.json()["turns"]
    assert [t["role"] for t in turns] == ["coach", "client", "coach", "client"]


def test_transcript_endpoint_includes_ms_and_text(client_with_session):
    client, state = client_with_session
    r = client.get(f"/api/session/{state.id}/transcript")
    turns = r.json()["turns"]
    assert turns[0]["ms"] == 1000
    assert turns[0]["text"] == "最近怎么样?"
    assert turns[3]["ms"] == 9000
    assert turns[3]["text"] == "工作上的事"


def test_transcript_endpoint_404_for_unknown_session(client_with_session):
    client, _ = client_with_session
    r = client.get("/api/session/no-such-id/transcript")
    assert r.status_code == 404


# ---- /api/session/{id}/audio ----------------------------------------------


def test_audio_endpoint_serves_wav_bytes(client_with_session):
    """Audio endpoint must return the recorded wav with audio/wav content-type
    so the browser can `<audio>` it inline."""
    client, state = client_with_session
    # Re-open the recorder (fixture closed it) so write_audio can append PCM.
    state.recorder.open()
    state.recorder.write_audio(b"\x00\x00" * 16000)  # 1s of PCM silence
    state.recorder.close()
    audio_path = Path(state.recorder.audio_path)
    expected_bytes = audio_path.read_bytes()
    assert state.recorder.audio_bytes() > 0

    r = client.get(f"/api/session/{state.id}/audio")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/wav")
    # Content-Length header must match file size (so the browser can
    # render a progress bar).
    assert int(r.headers["content-length"]) == len(expected_bytes)
    assert r.content == expected_bytes


def test_audio_endpoint_404_when_no_wav(client_with_session):
    """If the session has no recorded audio yet (probe-session / in-flight),
    the endpoint must 404 rather than return an empty file or 500."""
    client, state = client_with_session
    r = client.get(f"/api/session/{state.id}/audio")
    assert r.status_code == 404


def test_audio_endpoint_404_for_unknown_session(client_with_session):
    client, _ = client_with_session
    r = client.get("/api/session/no-such-id/audio")
    assert r.status_code == 404


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
