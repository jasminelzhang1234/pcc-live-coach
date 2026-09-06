# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Task 3 — pcc-assessor endpoint + assess.py unit tests.

Spec: docs/superpowers/specs/2026-09-06-phase-b-dashboard-v2-design.md
Plan: docs/superpowers/plans/2026-09-06-phase-b-dashboard-v2.md

Strategy (A1):assess.py reads 4 KB files, builds a system prompt, calls LLM.
We inject httpx.MockTransport so the test doesn't hit the network.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# Stub the `nls` SDK + alibabacloud token client so the router module
# (which transitively imports phase_b.asr.aliyun_client) loads under
# the test env where these packages aren't installed. Endpoint tests
# for /assess don't exercise ASR at all — they only need the FastAPI
# app to import. Unit tests above don't touch the router and are
# unaffected.
if "nls" not in sys.modules:
    _nls_stub = types.ModuleType("nls")
    _nls_stub.NlsSpeechTranscriber = type("NlsSpeechTranscriber", (), {})
    _nls_stub.TokenClient = type("TokenClient", (), {})
    sys.modules["nls"] = _nls_stub

_aliyun_pkg = "alibabacloud_nls_cloud_meta20190228"
if _aliyun_pkg not in sys.modules:
    _aliyun_mod = types.ModuleType(_aliyun_pkg)
    _client_mod = types.ModuleType(f"{_aliyun_pkg}.client")
    _client_mod.Client = type("Client", (), {})
    sys.modules[_aliyun_pkg] = _aliyun_mod
    sys.modules[f"{_aliyun_pkg}.client"] = _client_mod

# alibabacloud_tea_openapi (used by aliyun_client for credential models)
_tea_pkg = "alibabacloud_tea_openapi"
if _tea_pkg not in sys.modules:
    _tea_mod = types.ModuleType(_tea_pkg)
    _tea_models = types.ModuleType(f"{_tea_pkg}.models")
    _tea_models.Config = type("Config", (), {})
    _tea_models.Credential = type("Credential", (), {})
    sys.modules[_tea_pkg] = _tea_mod
    sys.modules[f"{_tea_pkg}.models"] = _tea_models

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# --- assess.py unit tests --------------------------------------------------


def test_load_kb_text_includes_all_four_files():
    """The system prompt must include the 4 KB files (pcc-assessor relies
    on every section being present to keep its accuracy)."""
    from phase_b.assess import load_kb_text, _KB_FILES

    text = load_kb_text()
    for fname in _KB_FILES:
        assert f"=== {fname} ===" in text, f"missing KB section header for {fname}"


def test_format_transcript_renders_role_prefix():
    """Coach/client turns must be labelled the way pcc-assessor KB examples use
    (教练: ... | 客户: ...). _meta rows / empty texts are dropped."""
    from phase_b.assess import _format_transcript

    turns = [
        {"role": "_meta", "event": "session_start", "text": "", "ms": 1},
        {"role": "coach", "text": "最近怎么样?", "ms": 2},
        {"role": "client", "text": "还行吧", "ms": 3},
        {"role": "coach", "text": "   ", "ms": 4},  # whitespace-only → dropped
    ]
    out = _format_transcript(turns)
    assert "教练: 最近怎么样?" in out
    assert "客户: 还行吧" in out
    assert "_meta" not in out
    # Whitespace-only text should be skipped (no empty 教练: line)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 2


def test_parse_assessment_response_strips_fenced_json():
    """LLM wrappers often emit ```json ... ``` blocks; parser must extract
    the JSON regardless."""
    from phase_b.assess import _parse_assessment_response

    raw = (
        "Here is the assessment:\n"
        "```json\n"
        '{"summary": {"verdict": "达标", "yes_count": 30}}\n'
        "```\n"
        "Done."
    )
    payload = _parse_assessment_response(raw)
    assert payload["summary"]["verdict"] == "达标"


def test_parse_assessment_response_handles_bare_json():
    from phase_b.assess import _parse_assessment_response

    payload = _parse_assessment_response('{"markers": {"3.1": {"verdict": "✔"}}}')
    assert "markers" in payload


def test_parse_assessment_response_raises_on_empty():
    from phase_b.assess import _parse_assessment_response

    with pytest.raises(ValueError, match="empty"):
        _parse_assessment_response("")


def test_parse_assessment_response_raises_on_no_json():
    from phase_b.assess import _parse_assessment_response

    with pytest.raises(ValueError, match="no JSON block"):
        _parse_assessment_response("sorry, no assessment available")


def test_validate_marker_keys_warns_on_missing(caplog):
    """If the LLM forgets a marker (e.g. truncated output), we don't
    hard-fail — the dashboard fills the missing marker with ✘. The function
    just logs a warning so we can debug the prompt if it keeps happening."""
    import logging
    from phase_b.assess import _validate_marker_keys

    caplog.set_level(logging.WARNING)
    _validate_marker_keys({"markers": {"3.1": {"verdict": "✔"}}})  # only 1 of 41
    assert any("missing markers" in rec.message for rec in caplog.records)


def test_save_and_load_assessment_roundtrip(tmp_path):
    """Saved JSON must round-trip with the same keys (so the dashboard
    can re-read after a manual override)."""
    from phase_b.assess import load_assessment, save_assessment

    payload = {
        "markers": {"3.1": {"verdict": "✔", "evidence": "好", "reason": "好"}},
        "summary": {"verdict": "达标", "yes_count": 1, "delta_count": 0, "no_count": 0},
    }
    out = save_assessment("demo-001", payload, base_dir=tmp_path)
    assert out.is_file()
    loaded = load_assessment("demo-001", base_dir=tmp_path)
    assert loaded["summary"]["verdict"] == "达标"


def test_load_assessment_returns_none_when_missing(tmp_path):
    from phase_b.assess import load_assessment

    assert load_assessment("never-assessed", base_dir=tmp_path) is None


# --- LLM mock + run_assessment integration ----------------------------------


def _mock_llm_response(payload: dict) -> str:
    """Build a JSON-string the way MiniMax-M3 would return it."""
    return json.dumps(payload, ensure_ascii=False)


def _mock_transport_factory(payload: dict):
    """Return an httpx.MockTransport that replies with the given payload."""

    def _handle(request: httpx.Request) -> httpx.Response:
        body = json.dumps({
            "choices": [{"message": {"content": _mock_llm_response(payload)}}],
        }).encode("utf-8")
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    return httpx.MockTransport(_handle)


def test_run_assessment_returns_parsed_payload():
    """End-to-end: assess.py → LLM mock → dict with markers + summary.

    We avoid `@pytest.mark.asyncio` (project doesn't ship pytest-asyncio)
    by wrapping the coroutine in asyncio.run().
    """
    import asyncio
    from phase_b.assess import run_assessment

    sample = {
        "markers": {
            "3.1": {"verdict": "✔", "evidence": "今天想聊啥", "reason": "明确确认"},
            "8.9": {"verdict": "✘", "evidence": "未见证据", "reason": "教练单方面宣布结束"},
        },
        "required_check": {
            "3.1": "✔", "3.4": "△", "6.7": "✔",
            "7.2_or_7.3": "✘", "8.5": "△", "8.9": "✘",
        },
        "structural_downgrades": ["8.9 教练单方面宣布 → ✘"],
        "summary": {
            "verdict": "未达标",
            "yes_count": 20, "delta_count": 10, "no_count": 11,
            "required_missed": 2, "key_weakness": "8.9 ✘ 收尾单方面",
        },
    }
    transport = _mock_transport_factory(sample)
    turns = [
        {"role": "coach", "text": "今天想聊啥?", "ms": 1},
        {"role": "client", "text": "工作上有点烦", "ms": 2},
        {"role": "coach", "text": "那我们今天就到这吧", "ms": 3},
    ]
    payload = asyncio.run(run_assessment(turns, transport=transport))
    assert payload["summary"]["verdict"] == "未达标"
    assert payload["markers"]["3.1"]["verdict"] == "✔"


def test_run_assessment_raises_on_empty_transcript():
    """No dialogue rows = nothing to assess; fail fast rather than send
    a $0 LLM call that hallucinates markers for a non-existent session."""
    import asyncio
    from phase_b.assess import run_assessment

    def _run():
        return asyncio.run(run_assessment(
            [], transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"{}"))
        ))

    with pytest.raises(ValueError, match="empty transcript"):
        _run()


# --- Endpoint tests (FastAPI TestClient + mocked LLM) ----------------------


@pytest.fixture
def assess_client(tmp_path, monkeypatch):
    """Spin up the FastAPI app with a session that has dialogue JSONL,
    and monkeypatch run_assessment so the endpoint test doesn't hit the
    network (the unit-test above covers the LLM path itself)."""
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder
    from phase_b import assess as assess_mod

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    recorder = SessionRecorder(sessions_dir, "demo-002")
    recorder.open()
    state = SessionState(
        session_id="demo-002",
        persona_id="vec-01",
        topic="demo",
        difficulty=2,
        recorder=recorder,
        started_ms=1000,
    )
    dialogue_path = Path(recorder.dialogue_path)
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dialogue_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "_meta", "event": "session_start",
                            "session_id": "demo-002", "started_ms": 1000}) + "\n")
        f.write(json.dumps({"role": "coach", "event": "utterance",
                            "turn": 1, "text": "今天想聊啥?", "ms": 1000}) + "\n")
        f.write(json.dumps({"role": "client", "event": "utterance",
                            "turn": 1, "text": "工作上有点烦", "ms": 3000}) + "\n")
        f.write(json.dumps({"role": "_meta", "event": "session_end",
                            "session_id": "demo-002", "ended_ms": 5000}) + "\n")
    recorder.close()

    # Monkeypatch run_assessment to skip LLM.
    sample = {
        "markers": {"3.1": {"verdict": "✔", "evidence": "今天想聊啥", "reason": "好"}},
        "summary": {
            "verdict": "达标",
            "yes_count": 30, "delta_count": 5, "no_count": 6,
            "required_missed": 0, "key_weakness": "无明显短板",
        },
    }

    async def fake_run(turns, *, transport=None):
        return sample

    monkeypatch.setattr(assess_mod, "run_assessment", fake_run)

    # Redirect save_assessment into tmp_path so we don't pollute phase_b/_assessments.
    real_save = assess_mod.save_assessment

    def fake_save(session_id, payload, base_dir=None):
        return real_save(session_id, payload, base_dir=tmp_path / "_assessments")

    monkeypatch.setattr(assess_mod, "save_assessment", fake_save)

    from phase_b.wire import router as router_mod

    orig_get_manager = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    mgr._sessions["demo-002"] = state

    from phase_b.server import app

    with TestClient(app) as c:
        yield c, state, sample
    router_mod.get_manager = orig_get_manager


def test_assess_endpoint_returns_summary_and_saves_json(assess_client):
    """Happy path: POST /assess triggers LLM, returns summary, drops json."""
    client, state, sample = assess_client
    r = client.post(f"/api/session/{state.id}/assess")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == state.id
    assert body["summary"]["verdict"] == sample["summary"]["verdict"]
    # File must have been saved to tmp_path/_assessments/<id>.json
    out = Path(body["assessment_path"])
    assert out.is_file()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["summary"]["verdict"] == "达标"


def test_assess_endpoint_404_for_unknown_id(assess_client):
    client, _, _ = assess_client
    r = client.post("/api/session/no-such-id/assess")
    assert r.status_code == 404


def test_assess_endpoint_404_when_no_dialogue(tmp_path):
    """Session exists but dialogue JSONL hasn't been written (probe-session
    or in-flight session). 404 rather than 500."""
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder
    from phase_b.wire import router as router_mod

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    recorder = SessionRecorder(sessions_dir, "demo-003")
    state = SessionState(
        session_id="demo-003",
        persona_id="vec-01",
        topic="demo",
        difficulty=0,
        recorder=recorder,
        started_ms=1000,
    )
    # Deliberately don't write a dialogue file.

    orig = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    mgr._sessions["demo-003"] = state

    from phase_b.server import app

    with TestClient(app) as c:
        r = c.post("/api/session/demo-003/assess")
        assert r.status_code == 404
    router_mod.get_manager = orig


def test_assess_endpoint_502_on_llm_parse_failure(tmp_path, monkeypatch):
    """If LLM returns garbage, endpoint must surface a 502 so the dashboard
    can show a 'please retry' message rather than silently returning empty."""
    from phase_b.session.manager import SessionManager, SessionState
    from phase_b.session.recorder import SessionRecorder
    from phase_b import assess as assess_mod
    from phase_b.wire import router as router_mod

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    mgr = SessionManager(sessions_dir=str(sessions_dir))
    recorder = SessionRecorder(sessions_dir, "demo-004")
    recorder.open()
    state = SessionState(
        session_id="demo-004", persona_id="vec-01", topic="demo", difficulty=0,
        recorder=recorder, started_ms=1000,
    )
    dialogue_path = Path(recorder.dialogue_path)
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dialogue_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "coach", "event": "utterance",
                            "turn": 1, "text": "hi", "ms": 1000}) + "\n")
    recorder.close()

    async def fake_run(turns, *, transport=None):
        raise ValueError("no JSON block in LLM response")

    monkeypatch.setattr(assess_mod, "run_assessment", fake_run)

    orig = router_mod.get_manager
    router_mod.get_manager = lambda: mgr
    mgr._sessions["demo-004"] = state

    from phase_b.server import app

    with TestClient(app) as c:
        r = c.post("/api/session/demo-004/assess")
        assert r.status_code == 502
        assert "assess parse failed" in r.json()["detail"]
    router_mod.get_manager = orig


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))