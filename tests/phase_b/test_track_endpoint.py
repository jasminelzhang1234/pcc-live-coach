# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Task 4 — POST /api/session/{id}/track endpoint + csv upsert unit tests.

Spec: docs/superpowers/specs/2026-09-06-phase-b-dashboard-v2-design.md
Plan: docs/superpowers/plans/2026-09-06-phase-b-dashboard-v2.md

The endpoint:
1. Upserts one row into progress/tracker-real-sessions.csv (idempotent)
2. Runs scripts/gen_trending_chart_real.py to refresh the chart

Tests:
- csv_append.upsert_session_row unit tests (insert / replace / no-csv)
- Endpoint happy path: insert, returns chart_path
- Endpoint idempotency: two POSTs for same session_id → still one row
- Endpoint 404s: unknown id / no dialogue
"""
from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# Stub aliyun-nls SDK + alibabacloud_tea_openapi so router module loads.
for _mod_name in ("nls",):
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        _stub.NlsSpeechTranscriber = type("NlsSpeechTranscriber", (), {})
        _stub.TokenClient = type("TokenClient", (), {})
        sys.modules[_mod_name] = _stub

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
    _tea_models.Credential = type("Credential", (), {})
    sys.modules[_tea_pkg] = _tea_mod
    sys.modules[f"{_tea_pkg}.models"] = _tea_models

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# --- upsert_session_row unit tests -----------------------------------------


HEADER_95 = ["session_id", "date", "persona", "difficulty", "topic", "audio_path",
             "transcript_path"] + [f"col_{i}" for i in range(7, 95)]


def _write_csv_with_rows(csv_path: Path, rows: list[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER_95, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            full = {col: r.get(col, "") for col in HEADER_95}
            writer.writerow(full)


def _read_csv_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_upsert_inserts_when_no_prior_row(tmp_path):
    """First call for a session_id: must append a single row and report 'inserted'."""
    from phase_b.tracker.csv_append import build_row, upsert_session_row

    csv_path = tmp_path / "tracker.csv"
    _write_csv_with_rows(csv_path, [])
    row = build_row(
        session_id="real-2026-09-06-01",
        persona="vec-01", difficulty=2, topic="压力管理",
        audio_path="raw/x.wav", transcript_path="dialogues/x.jsonl",
        header=HEADER_95,
    )
    status = upsert_session_row(csv_path=csv_path, row=row)
    assert status == "inserted"
    rows = _read_csv_rows(csv_path)
    assert len(rows) == 1
    assert rows[0]["session_id"] == "real-2026-09-06-01"


def test_upsert_replaces_when_prior_row_exists(tmp_path):
    """Re-running /track for the same session must NOT duplicate the row —
    the old one is dropped and the new one inserted (idempotent contract)."""
    from phase_b.tracker.csv_append import build_row, upsert_session_row

    csv_path = tmp_path / "tracker.csv"
    _write_csv_with_rows(csv_path, [
        {"session_id": "real-2026-09-06-01", "topic": "压力管理"},
        {"session_id": "real-2026-09-06-02", "topic": "其他"},
    ])
    row = build_row(
        session_id="real-2026-09-06-01",
        persona="vec-01", difficulty=2, topic="压力管理(updated)",
        audio_path="raw/x.wav", transcript_path="dialogues/x.jsonl",
        header=HEADER_95,
    )
    status = upsert_session_row(csv_path=csv_path, row=row)
    assert status == "replaced"
    rows = _read_csv_rows(csv_path)
    assert len(rows) == 2, "must not duplicate; total row count stays the same"
    by_id = {r["session_id"]: r for r in rows}
    assert by_id["real-2026-09-06-01"]["topic"] == "压力管理(updated)"
    assert by_id["real-2026-09-06-02"]["topic"] == "其他"


def test_upsert_returns_no_csv_when_file_missing(tmp_path):
    """If the canonical CSV isn't on disk (first run, header not written
    yet), the function reports 'no_csv' rather than crashing. The caller
    (endpoint) propagates this so the dashboard can prompt the user to
    run the bootstrap."""
    from phase_b.tracker.csv_append import build_row, upsert_session_row

    csv_path = tmp_path / "tracker.csv"
    assert not csv_path.is_file()
    row = build_row(
        session_id="real-2026-09-06-01", persona="vec-01", difficulty=0,
        topic="x", audio_path="a", transcript_path="b", header=HEADER_95,
    )
    status = upsert_session_row(csv_path=csv_path, row=row)
    assert status == "no_csv"


# --- Endpoint tests ---------------------------------------------------------


@pytest.fixture
def track_env(tmp_path, monkeypatch):
    """Spin up the FastAPI app with:
    - a real session that has dialogue JSONL + rhythm JSONL
    - a tracker CSV (95-col header) under tmp_path/progress/tracker-real-sessions.csv
    - a stub gen_trending_chart_real.py under tmp_path/scripts/ that just writes an empty html
    - tracker_csv settings pointed at the tmp_path CSV
    """
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder
    from phase_b import config as config_mod

    # Set up sessions + dialogue JSONL.
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    recorder = SessionRecorder(sessions_dir, "demo-track")
    recorder.open()
    state = SessionState(
        session_id="demo-track",
        persona_id="vec-01",
        topic="压力管理",
        difficulty=2,
        recorder=recorder,
        started_ms=1000,
    )
    dialogue_path = Path(recorder.dialogue_path)
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dialogue_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "_meta", "event": "session_start",
                            "session_id": "demo-track", "started_ms": 1000}) + "\n")
        f.write(json.dumps({"role": "coach", "event": "utterance",
                            "turn": 1, "text": "最近怎么样?", "ms": 1000}) + "\n")
        f.write(json.dumps({"role": "client", "event": "utterance",
                            "turn": 1, "text": "工作有点烦", "ms": 3000}) + "\n")
    # Minimal rhythm JSONL so KPIs are non-zero.
    rhythm_path = Path(recorder.rhythm_path)
    rhythm_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rhythm_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"speaker_role": "coach", "turn": 1, "cpm": 180,
                            "pre_silence_ms": 500, "silence_5_5": False,
                            "barge_in_count": 0}) + "\n")
        f.write(json.dumps({"speaker_role": "client", "turn": 1, "cpm": 0,
                            "pre_silence_ms": 2500, "silence_5_5": False,
                            "barge_in_count": 0}) + "\n")
    recorder.close()

    # Pre-create the 95-col CSV under progress/ so upsert has a header.
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir()
    csv_path = progress_dir / "tracker-real-sessions.csv"
    _write_csv_with_rows(csv_path, [])

    # Stub scripts/gen_trending_chart_real.py so the endpoint doesn't run
    # the real (heavy) chart generator. We monkeypatch subprocess.run at
    # the router module level instead — the endpoint calls subprocess.run
    # with the real repo-root path, so swapping the whole function lets us
    # redirect to a tmp_path chart file.
    progress_dir_chart = tmp_path / "chart_out"
    progress_dir_chart.mkdir()
    chart_out_path = progress_dir_chart / "trending-chart-real-2026-09-06.html"
    chart_out_path.write_text("<html>STUB</html>", encoding="utf-8")

    from phase_b.wire import router as router_mod

    def fake_subprocess_run(cmd, **kwargs):
        # Simulate a successful chart regen by returning a CompletedProcess.
        import subprocess as _sp
        return _sp.CompletedProcess(cmd, 0, stdout="[stub] ok\n", stderr="")

    monkeypatch.setattr(router_mod.subprocess, "run", fake_subprocess_run)
    # Tell the endpoint where the (stub) chart was written.
    monkeypatch.setattr(router_mod, "_chart_output_path", lambda repo_root=None: str(chart_out_path))

    # Redirect config.tracker_csv to tmp_path/progress/tracker-real-sessions.csv
    # by setting env, then re-reading settings (config is frozen dataclass).
    monkeypatch.setenv("TRACKER_CSV", str(csv_path))
    import importlib
    config_mod = importlib.reload(config_mod)
    monkeypatch.setattr(config_mod, "get_settings", lambda: config_mod.Settings(
        tracker_csv=str(csv_path),
    ))

    orig_get_manager = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    mgr._sessions["demo-track"] = state

    from phase_b.server import app

    with TestClient(app) as c:
        yield c, state, csv_path

    router_mod.get_manager = orig_get_manager


def test_track_endpoint_inserts_row_and_returns_chart_path(track_env):
    """Happy path: POST /track appends one row + regenerates the chart."""
    client, state, csv_path = track_env
    r = client.post(f"/api/session/{state.id}/track")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == state.id
    assert body["csv_status"] == "inserted"
    assert body["chart_path"] is not None
    # Stub chart script wrote a real file
    assert Path(body["chart_path"]).is_file()
    # Tracker CSV got the new row
    rows = _read_csv_rows(csv_path)
    assert len(rows) == 1
    assert rows[0]["session_id"] == state.id
    # KPIs come from rhythm jsonl
    assert body["kpis"]["mean_cpm"] == 180


def test_track_endpoint_is_idempotent(track_env):
    """Two POST /track for the same session → still ONE row (replaced)."""
    client, state, csv_path = track_env
    r1 = client.post(f"/api/session/{state.id}/track")
    r2 = client.post(f"/api/session/{state.id}/track")
    assert r1.json()["csv_status"] == "inserted"
    assert r2.json()["csv_status"] == "replaced"
    rows = _read_csv_rows(csv_path)
    assert len(rows) == 1, "second call must NOT duplicate the row"


def test_track_endpoint_404_for_unknown_session(track_env):
    client, _, _ = track_env
    r = client.post("/api/session/no-such-id/track")
    assert r.status_code == 404


def test_track_endpoint_404_when_no_dialogue(tmp_path, monkeypatch):
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder
    from phase_b import config as config_mod
    from phase_b.wire import router as router_mod

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    recorder = SessionRecorder(sessions_dir, "demo-nodlg")
    state = SessionState(
        session_id="demo-nodlg", persona_id="vec-01", topic="x", difficulty=0,
        recorder=recorder, started_ms=1000,
    )
    # No dialogue / rhythm files written.

    # Provide a tracker CSV so the endpoint doesn't fail for the wrong reason.
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir()
    csv_path = progress_dir / "tracker-real-sessions.csv"
    _write_csv_with_rows(csv_path, [])

    monkeypatch.setenv("TRACKER_CSV", str(csv_path))
    import importlib
    config_mod = importlib.reload(config_mod)
    monkeypatch.setattr(config_mod, "get_settings", lambda: config_mod.Settings(
        tracker_csv=str(csv_path),
    ))

    orig = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    mgr._sessions["demo-nodlg"] = state

    from phase_b.server import app

    with TestClient(app) as c:
        r = c.post("/api/session/demo-nodlg/track")
        assert r.status_code == 404
    router_mod.get_manager = orig


def test_track_endpoint_handles_no_csv_file(tmp_path, monkeypatch):
    """When the canonical CSV hasn't been written (no header), the
    endpoint reports csv_status='no_csv' and still tries to regenerate
    the chart. The user can then bootstrap the header separately."""
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder
    from phase_b import config as config_mod
    from phase_b.wire import router as router_mod

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    recorder = SessionRecorder(sessions_dir, "demo-nocsv")
    recorder.open()
    state = SessionState(
        session_id="demo-nocsv", persona_id="vec-01", topic="x", difficulty=0,
        recorder=recorder, started_ms=1000,
    )
    dialogue_path = Path(recorder.dialogue_path)
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dialogue_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "coach", "event": "utterance",
                            "turn": 1, "text": "hi", "ms": 1000}) + "\n")
    recorder.close()

    # CSV does NOT exist.
    csv_path = tmp_path / "progress" / "tracker-real-sessions.csv"
    # We still point config at the missing path.
    monkeypatch.setenv("TRACKER_CSV", str(csv_path))
    import importlib
    config_mod = importlib.reload(config_mod)
    monkeypatch.setattr(config_mod, "get_settings", lambda: config_mod.Settings(
        tracker_csv=str(csv_path),
    ))

    # Stub subprocess.run + chart output path so the endpoint doesn't
    # run the real chart generator.
    progress_dir_chart = tmp_path / "chart_out"
    progress_dir_chart.mkdir()
    chart_out_path = progress_dir_chart / "trending-chart-real-2026-09-06.html"
    chart_out_path.write_text("<html>STUB</html>", encoding="utf-8")
    import subprocess as _sp
    monkeypatch.setattr(router_mod.subprocess, "run",
                        lambda cmd, **kw: _sp.CompletedProcess(cmd, 0, stdout="ok", stderr=""))
    monkeypatch.setattr(router_mod, "_chart_output_path", lambda repo_root=None: str(chart_out_path))

    orig = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    mgr._sessions["demo-nocsv"] = state

    from phase_b.server import app

    with TestClient(app) as c:
        r = c.post("/api/session/demo-nocsv/track")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["csv_status"] == "no_csv"
    router_mod.get_manager = orig


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))