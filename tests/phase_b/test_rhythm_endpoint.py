# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Step 10 — /api/session/{id}/rhythm endpoint."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import shutil  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client_with_session(tmp_path):
    """Spin up the FastAPI app with a session that has rhythm JSONL."""
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    # Manually create a state + rhythm file (avoid touching get_manager singleton).
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
    # Write two rhythm turns.
    rhythm_path = Path(recorder.rhythm_path)
    rhythm_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rhythm_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"turn": 1, "ts": 1000, "coach_chars": 5, "coach_dur_ms": 2000,
                            "cpm": 150, "cpm_band": "ideal", "pre_silence_ms": 1000,
                            "silence_5_5": False, "client_filled_silence": False,
                            "barge_in_count": 0, "client_interruption_by_coach_ms": 0,
                            "speaker_role": "coach"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"turn": 2, "ts": 6500, "coach_chars": 13, "coach_dur_ms": 2500,
                            "cpm": 312, "cpm_band": "fast", "pre_silence_ms": 3500,
                            "silence_5_5": True, "client_filled_silence": False,
                            "barge_in_count": 2, "client_interruption_by_coach_ms": 0,
                            "speaker_role": "coach"}, ensure_ascii=False) + "\n")
    recorder.close()

    # Patch the wire router's get_manager to return our fixture manager.
    from phase_b.wire import router as router_mod
    orig_get_manager = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    # Also register state with the singleton so /api/session/{id} works.
    mgr._sessions["demo-001"] = state

    from phase_b.server import app
    with TestClient(app) as c:
        yield c, state
    router_mod.get_manager = orig_get_manager


def test_rhythm_endpoint_returns_turns_and_kpis(client_with_session):
    client, state = client_with_session
    r = client.get(f"/api/session/{state.id}/rhythm")
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] == state.id
    assert len(data["turns"]) == 2
    assert data["turns"][0]["cpm"] == 150
    assert data["turns"][1]["silence_5_5"] is True
    k = data["kpis"]
    # mean_cpm = (150 + 312) / 2 = 231
    assert k["mean_cpm"] == 231
    assert k["silence_5_5_count"] == 1
    assert k["barge_in_count"] == 2
    assert k["turn_count"] == 2


def test_rhythm_endpoint_404_for_unknown_session(client_with_session):
    client, _ = client_with_session
    r = client.get("/api/session/no-such-id/rhythm")
    assert r.status_code == 404


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
