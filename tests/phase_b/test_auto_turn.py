from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.wire import router  # noqa: E402


class _Recorder:
    def __init__(self):
        self.dialogue = []

    def write_dialogue(self, value):
        self.dialogue.append(value)

    def write_audio(self, _pcm):
        pass


class _State:
    persona_id = "vec-01"
    difficulty = 0
    last_latency_ms = None

    def __init__(self):
        self.recorder = _Recorder()


class _Manager:
    def __init__(self):
        self.state = _State()

    def get(self, _session_id):
        return self.state

    def end(self, _session_id):
        return self.state


class _WebSocket:
    def __init__(self, messages):
        self.inbound = asyncio.Queue()
        for message in messages:
            self.inbound.put_nowait(message)
        self.sent = []

    async def accept(self):
        pass

    async def send_json(self, value):
        self.sent.append(value)

    async def send_bytes(self, value):
        self.sent.append(value)

    async def receive(self):
        message = await self.inbound.get()
        await asyncio.sleep(0)
        return {"type": "websocket.receive", "text": json.dumps(message)}

    async def close(self, **_kwargs):
        pass


class _Worker:
    instances = []

    def __init__(self, **_kwargs):
        self.events_queue = asyncio.Queue()
        self.clears = 0
        self.__class__.instances.append(self)

    async def start(self):
        pass

    async def stop(self):
        pass

    def feed(self, _pcm):
        pass

    def clear_buffer(self):
        self.clears += 1

    async def events(self):
        while True:
            yield await self.events_queue.get()


class _PendingLoadWorker(_Worker):
    load_cancelled = False

    async def start(self):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.__class__.load_cancelled = True
            raise


class _Settings:
    asr_model = "fake"
    asr_chunk_ms = 10
    asr_language = "auto"


async def _run_ws(monkeypatch, messages, run_turn_impl, worker_cls=_Worker):
    manager = _Manager()
    websocket = _WebSocket(messages)
    _Worker.instances.clear()
    monkeypatch.setattr(router, "get_manager", lambda: manager)
    monkeypatch.setattr(router, "ASRWorker", worker_cls)
    monkeypatch.setattr(router, "run_turn", run_turn_impl)
    monkeypatch.setattr("phase_b.config.get_settings", lambda: _Settings())
    task = asyncio.create_task(router._ws_session_impl(websocket, "session-1"))
    while not _Worker.instances:
        await asyncio.sleep(0)
    return task, websocket, manager, _Worker.instances[0]


async def _reply_turn(**_kwargs):
    yield {"kind": "reply_end"}


def test_utterance_end_auto_commits_once_and_max_duration_does_not(monkeypatch):
    async def scenario():
        task, websocket, manager, worker = await _run_ws(monkeypatch, [], _reply_turn)
        await worker.events_queue.put(
            {"event": "partial", "text": "持续说话", "audio_ms": 800, "is_utterance_end": False}
        )
        await worker.events_queue.put(
            {"event": "partial", "text": "持续说话", "audio_ms": 800, "is_utterance_end": True}
        )
        await websocket.inbound.put({"cmd": "end"})
        await task
        return websocket, manager

    websocket, manager = asyncio.run(scenario())
    utterances = [x for x in manager.state.recorder.dialogue if x.get("event") == "utterance"]
    assert [x["text"] for x in utterances] == ["持续说话"]
    assert not any(x.get("event") == "warn" for x in websocket.sent)


def test_identical_utterances_from_separate_asr_events_commit_twice(monkeypatch):
    async def scenario():
        calls = []

        async def record_turn(**kwargs):
            calls.append(kwargs["client_text"])
            yield {"kind": "reply_end"}

        task, websocket, manager, worker = await _run_ws(monkeypatch, [], record_turn)
        first = {"event": "partial", "text": "重复内容", "audio_ms": 800, "is_utterance_end": True}
        second = {"event": "partial", "text": "重复内容", "audio_ms": 800, "is_utterance_end": True}
        await worker.events_queue.put(first)
        for _ in range(10):
            await asyncio.sleep(0)
            if calls == ["重复内容"]:
                break
        await worker.events_queue.put(second)
        for _ in range(10):
            await asyncio.sleep(0)
            if calls == ["重复内容", "重复内容"]:
                break
        await websocket.inbound.put({"cmd": "end"})
        await task
        return calls, manager

    calls, manager = asyncio.run(scenario())
    utterances = [x for x in manager.state.recorder.dialogue if x.get("event") == "utterance"]
    assert calls == ["重复内容", "重复内容"]
    assert [x["text"] for x in utterances] == ["重复内容", "重复内容"]


def test_duplicate_auto_event_while_turn_is_active_commits_once(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        calls = []

        async def blocking_turn(**kwargs):
            calls.append(kwargs["client_text"])
            await release.wait()
            if False:
                yield {}

        task, websocket, _manager, worker = await _run_ws(monkeypatch, [], blocking_turn)
        event = {"event": "partial", "text": "同一事件", "audio_ms": 800, "is_utterance_end": True}
        await worker.events_queue.put(event)
        await asyncio.sleep(0)
        await worker.events_queue.put(event)
        for _ in range(10):
            await asyncio.sleep(0)
            if calls == ["同一事件"]:
                break
        release.set()
        await websocket.inbound.put({"cmd": "end"})
        await task
        return calls

    assert asyncio.run(scenario()) == ["同一事件"]


def test_utterance_end_with_different_latency_commits_once(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        calls = []

        async def record_turn(**kwargs):
            calls.append(kwargs["client_text"])
            await release.wait()
            if False:
                yield {}

        task, websocket, manager, worker = await _run_ws(monkeypatch, [], record_turn)
        first = {
            "event": "partial",
            "text": "延迟变化",
            "audio_ms": 800,
            "latency_ms": 101,
            "is_final": False,
            "is_utterance_end": True,
        }
        second = {**first, "latency_ms": 202}
        await worker.events_queue.put(first)
        for _ in range(10):
            await asyncio.sleep(0)
            if calls == ["延迟变化"]:
                break
        await worker.events_queue.put(second)
        for _ in range(10):
            await asyncio.sleep(0)
        release.set()
        await websocket.inbound.put({"cmd": "end"})
        await task
        return calls, manager

    calls, manager = asyncio.run(scenario())
    utterances = [x for x in manager.state.recorder.dialogue if x.get("event") == "utterance"]
    assert calls == ["延迟变化"]
    assert [x["text"] for x in utterances] == ["延迟变化"]


def test_utterance_end_final_upgrade_commits_once(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        calls = []

        async def record_turn(**kwargs):
            calls.append(kwargs["client_text"])
            await release.wait()
            if False:
                yield {}

        task, websocket, manager, worker = await _run_ws(monkeypatch, [], record_turn)
        first = {
            "event": "partial",
            "text": "最终状态变化",
            "audio_ms": 800,
            "is_final": False,
            "is_utterance_end": True,
        }
        second = {**first, "is_final": True}
        await worker.events_queue.put(first)
        for _ in range(10):
            await asyncio.sleep(0)
            if calls == ["最终状态变化"]:
                break
        await worker.events_queue.put(second)
        for _ in range(10):
            await asyncio.sleep(0)
        release.set()
        await websocket.inbound.put({"cmd": "end"})
        await task
        return calls, manager

    calls, manager = asyncio.run(scenario())
    utterances = [x for x in manager.state.recorder.dialogue if x.get("event") == "utterance"]
    assert calls == ["最终状态变化"]
    assert [x["text"] for x in utterances] == ["最终状态变化"]


def test_end_cancels_pending_asr_load(monkeypatch):
    async def scenario():
        _PendingLoadWorker.load_cancelled = False
        task, websocket, _manager, _worker = await _run_ws(
            monkeypatch, [], _reply_turn, worker_cls=_PendingLoadWorker
        )
        await websocket.inbound.put({"cmd": "end"})
        await task
        return _PendingLoadWorker.load_cancelled

    assert asyncio.run(scenario()) is True


def test_end_closes_asr_submission_and_suppresses_late_turn_output(monkeypatch):
    async def scenario():
        calls = []

        async def late_turn(**kwargs):
            calls.append(kwargs["client_text"])
            yield {"kind": "reply_text", "text": "late reply"}
            yield b"late audio"
            yield {"kind": "reply_end"}

        task, websocket, manager, worker = await _run_ws(monkeypatch, [], late_turn)
        await websocket.inbound.put({"cmd": "end"})
        for _ in range(10):
            await asyncio.sleep(0)
            if any(x.get("event") == "ended" for x in websocket.sent):
                break
        await worker.events_queue.put(
            {"event": "partial", "text": "结束后语音", "audio_ms": 500, "is_utterance_end": True}
        )
        await task
        return calls, websocket, manager

    calls, websocket, manager = asyncio.run(scenario())
    assert calls == []
    assert websocket.sent[-1]["event"] == "ended"
    assert not any(x.get("event") in {"reply_text", "reply_end"} for x in websocket.sent)
    assert b"late audio" not in websocket.sent
    assert not any(x.get("event") == "utterance" for x in manager.state.recorder.dialogue)


def test_raised_turn_has_no_tail_messages_and_next_turn_can_run(monkeypatch):
    async def scenario():
        calls = []

        async def raising_then_success(**kwargs):
            calls.append(kwargs["client_text"])
            if len(calls) == 1:
                raise RuntimeError("turn exploded")
            yield {"kind": "reply_text", "text": "second reply"}
            yield {"kind": "reply_end"}

        task, websocket, manager, worker = await _run_ws(monkeypatch, [], raising_then_success)
        await worker.events_queue.put(
            {"event": "partial", "text": "第一回合", "audio_ms": 500, "is_utterance_end": True}
        )
        for _ in range(10):
            await asyncio.sleep(0)
            if any(x.get("stage") == "turn" for x in websocket.sent):
                break
        sent_after_error = len(websocket.sent)
        await worker.events_queue.put(
            {"event": "partial", "text": "第二回合", "audio_ms": 700, "is_utterance_end": True}
        )
        for _ in range(10):
            await asyncio.sleep(0)
            if calls == ["第一回合", "第二回合"]:
                break
        await websocket.inbound.put({"cmd": "end"})
        await task
        return calls, websocket, manager, sent_after_error

    calls, websocket, manager, sent_after_error = asyncio.run(scenario())
    assert calls == ["第一回合", "第二回合"]
    assert not any(
        x.get("turn") == 1 and x.get("event") in {"reply_text", "reply_end"}
        for x in websocket.sent
    )
    assert {"event": "reply_text", "text": "second reply", "turn": 2} in websocket.sent[sent_after_error:]
    assert {"event": "reply_end", "turn": 2} in websocket.sent[sent_after_error:]
    assert websocket.sent[-1] == {"event": "ended", "turn_count": 2, "barge_in_count": 0}
    assert [
        x["text"]
        for x in manager.state.recorder.dialogue
        if x.get("event") == "utterance" and x.get("role") == "coach"
    ] == [
        "第一回合",
        "第二回合",
    ]


def test_active_auto_turn_with_same_key_warns_instead_of_silent_dedupe(monkeypatch):
    async def scenario():
        release = asyncio.Event()

        async def blocking_turn(**_kwargs):
            await release.wait()
            if False:
                yield {}

        task, websocket, _manager, worker = await _run_ws(monkeypatch, [], blocking_turn)
        first = {"event": "partial", "text": "同一个 key", "audio_ms": 800, "is_utterance_end": True}
        second = {"event": "partial", "text": "同一个 key", "audio_ms": 800, "is_utterance_end": True}
        await worker.events_queue.put(first)
        await asyncio.sleep(0)
        await worker.events_queue.put(second)
        for _ in range(10):
            await asyncio.sleep(0)
            if any(x.get("msg") == "turn already in progress" for x in websocket.sent):
                break
        await websocket.inbound.put({"cmd": "end"})
        await task
        return websocket

    websocket = asyncio.run(scenario())
    assert any(x.get("msg") == "turn already in progress" for x in websocket.sent)


def test_active_auto_turn_warns_and_turn_error_clears_guard(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        calls = []

        async def failing_then_blocking(**kwargs):
            calls.append(kwargs["client_text"])
            if len(calls) == 1:
                yield {"kind": "error", "stage": "llm/tts", "error": "llm down"}
                return
            await release.wait()
            if False:
                yield {}

        task, websocket, manager, worker = await _run_ws(monkeypatch, [], failing_then_blocking)
        await worker.events_queue.put(
            {"event": "partial", "text": "第一回合", "audio_ms": 500, "is_utterance_end": True}
        )
        for _ in range(10):
            await asyncio.sleep(0)
            if any(x.get("event") == "error" and x.get("stage") == "llm/tts" for x in websocket.sent):
                break
        await worker.events_queue.put(
            {"event": "partial", "text": "第二回合", "audio_ms": 700, "is_utterance_end": True}
        )
        for _ in range(10):
            await asyncio.sleep(0)
            if calls == ["第一回合", "第二回合"]:
                break
        await websocket.inbound.put({"cmd": "barge_in"})
        for _ in range(10):
            await asyncio.sleep(0)
            if any(x.get("event") == "barge_in_stopped" for x in websocket.sent):
                break
        await websocket.inbound.put({"cmd": "end"})
        await task
        return calls, websocket, worker

    calls, websocket, worker = asyncio.run(scenario())
    assert calls == ["第一回合", "第二回合"]
    assert any(x.get("event") == "error" and x.get("stage") == "llm/tts" for x in websocket.sent)
    assert any(x.get("event") == "barge_in_stopped" for x in websocket.sent)
    assert worker.clears >= 2
