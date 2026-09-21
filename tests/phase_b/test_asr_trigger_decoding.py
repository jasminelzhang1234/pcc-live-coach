# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
"""Regression tests for VAD-segmented ASR trigger and lifecycle behavior."""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Any, List

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


from phase_b.asr import asr_worker as aw  # noqa: E402


# ---- fake model ------------------------------------------------------------


class _FakeModel:
    """Stub FunASR AutoModel. Records every call and returns scripted results."""

    def __init__(self, script: List[List[dict]]):
        # script[i] = sentence_info list to return on the i-th generate() call.
        self._script = list(script)
        self.calls: List[np.ndarray] = []

    def generate(self, input=None, **kwargs):
        self.calls.append(np.asarray(input))
        if not self._script:
            return [{"text": "", "sentence_info": []}]
        return [{"text": "<|zh|>" + "".join(s["text"] for s in self._script[0]) + "<|withitn|>",
                 "sentence_info": self._script.pop(0)}]


# ---- helpers ---------------------------------------------------------------


def _silence_pcm(ms: int) -> bytes:
    """Int16 silence of ``ms`` milliseconds at 16kHz mono."""
    samples = 16000 * ms // 1000
    return b"\x00\x00" * samples


def _tone_pcm(ms: int, amplitude: int = 5000) -> bytes:
    """Int16 sine-ish tone loud enough to exceed SILENCE_RMS_THRESHOLD."""
    samples = 16000 * ms // 1000
    # Square wave: alternating ±amplitude — guarantees RMS >> threshold.
    half = samples // 2
    high = (amplitude).to_bytes(2, "little", signed=True) * half
    low = (-amplitude).to_bytes(2, "little", signed=True) * (samples - half)
    return high + low


def _drain(worker, n: int = 100) -> List[dict]:
    """Collect up to ``n`` events from worker.events() with a timeout."""
    out: List[dict] = []
    async def collect():
        for _ in range(n):
            try:
                ev = await asyncio.wait_for(worker.events().__anext__(), timeout=0.5)
            except asyncio.TimeoutError:
                break
            out.append(ev)
    asyncio.run(collect())
    return out


# ---- fixtures --------------------------------------------------------------


@pytest.fixture
def fast_trigger(monkeypatch):
    """Patch ASRWorker constants so silence/timeout triggers fire fast in tests."""
    monkeypatch.setattr(aw.ASRWorker, "MIN_AUDIO_MS", 300)
    monkeypatch.setattr(aw.ASRWorker, "MAX_AUDIO_MS", 800)
    monkeypatch.setattr(aw.ASRWorker, "SILENCE_MS", 200)
    monkeypatch.setattr(aw.ASRWorker, "OVERLAP_MS", 200)


# ---- silence trigger -------------------------------------------------------


def _make_worker(fake: _FakeModel) -> aw.ASRWorker:
    """Build an ASRWorker with a fake model + manually-created events queue.

    Bypasses real model loading and binds the asyncio.Queue to the test's
    running event loop (asyncio.Queue() must be created inside an async
    context on Python 3.9).
    """
    async def _setup():
        w = aw.ASRWorker(chunk_ms=50)
        w._events = asyncio.Queue()
        w._model = fake
        w._running = True
        return w
    return asyncio.run(_setup())


# ---- silence trigger -------------------------------------------------------


def test_silence_trigger_emits_partial(fast_trigger):
    fake = _FakeModel([[{"text": "你好", "start": 0, "end": 600}]])
    worker = _make_worker(fake)
    # Loud audio for 600ms then 250ms silence — meets MIN_AUDIO_MS and SILENCE_MS.
    worker.feed(_tone_pcm(600))
    worker.feed(_silence_pcm(250))
    assert worker._should_flush() is True
    asyncio.run(worker._flush(is_final=False))
    assert fake.calls, "model.generate was not called"
    assert worker._events.qsize() == 1
    ev = worker._events.get_nowait()
    assert ev["event"] == "partial"
    assert ev["text"] == "你好"
    assert ev["is_final"] is False
    assert ev["is_utterance_end"] is True


def test_normal_pause_does_not_end_utterance_too_early(monkeypatch):
    monkeypatch.setattr(aw.ASRWorker, "MIN_AUDIO_MS", 1500)
    monkeypatch.setattr(aw.ASRWorker, "SILENCE_MS", 1800)
    fake = _FakeModel([[{"text": "你想怎么来", "start": 0, "end": 1500}]])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(1800))
    worker.feed(_silence_pcm(1200))
    assert worker._should_flush() is False
    worker.feed(_silence_pcm(700))
    assert worker._should_flush() is True


def test_default_asr_language_is_chinese():
    assert aw.ASRWorker()._language == "zh"


# ---- minimum buffer guard --------------------------------------------------


def test_short_buffer_does_not_trigger(fast_trigger):
    fake = _FakeModel([[]])  # would return empty if called
    worker = _make_worker(fake)
    # Total 200ms — below MIN_AUDIO_MS (300) so silence trigger must be suppressed
    # even though the tail is silent.
    worker.feed(_tone_pcm(100))
    worker.feed(_silence_pcm(100))
    assert worker._should_flush() is False


# ---- timeout trigger -------------------------------------------------------


def test_timeout_trigger_fires_without_silence(fast_trigger):
    fake = _FakeModel([[{"text": "持续说话", "start": 0, "end": 800}]])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(900))  # >= MAX_AUDIO_MS=800; no silence at the tail
    assert worker._should_flush() is True
    asyncio.run(worker._flush(is_final=False))
    ev = worker._events.get_nowait()
    assert ev["text"] == "持续说话"
    assert ev["is_utterance_end"] is False


# ---- dedupe: a second decode that returns the same segments emits nothing -


def test_second_decode_same_segments_emits_nothing(fast_trigger):
    # Same sentence on two calls — only the first should emit.
    fake = _FakeModel([
        [{"text": "重复", "start": 0, "end": 400}],
        [{"text": "重复", "start": 0, "end": 400}],
    ])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(600))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))
    first = worker._events.get_nowait()
    assert first["text"] == "重复"

    # Feed a bit more audio so silence-trigger fires again on the same audio
    # (which will yield the same sentence_info again from the fake).
    worker.feed(_tone_pcm(200))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))
    # Dedupe: no new partial event should be in the queue.
    assert worker._events.qsize() == 0


# ---- overlap trim ----------------------------------------------------------


def test_overlap_trim_keeps_tail(fast_trigger):
    fake = _FakeModel([[{"text": "x", "start": 0, "end": 100}]])
    worker = _make_worker(fake)
    # 600ms loud + 250ms silence = 850ms; after flush, only last 200ms (OVERLAP_MS) remain.
    worker.feed(_tone_pcm(600))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))
    expected_bytes = 16000 * worker.OVERLAP_MS // 1000 * 2
    assert len(worker._buffer) == expected_bytes


# ---- final flush on stop ---------------------------------------------------


def test_stop_runs_final_flush(fast_trigger):
    fake = _FakeModel([
        [],                            # first decode returns nothing (silence)
        [{"text": "最后一句", "start": 0, "end": 300}],  # final decode
    ])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(500))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))
    assert worker._events.qsize() == 0  # first flush produced nothing
    # Now stop() must run a final flush even though silence trigger isn't refired.
    asyncio.run(worker.stop())
    assert worker._events.qsize() == 1
    ev = worker._events.get_nowait()
    assert ev["text"] == "最后一句"
    assert ev["is_final"] is True
    assert ev["is_utterance_end"] is True


def test_model_not_ready_audio_keeps_tail_of_single_oversized_chunk(caplog, monkeypatch):
    worker = aw.ASRWorker()
    monkeypatch.setattr(worker, "MAX_PENDING_AUDIO_BYTES", 4)

    worker.feed(b"012345")

    assert worker.pending_audio_bytes() == 4
    assert worker._buffer == bytearray()
    assert "pending ASR audio buffer full" in caplog.text
    assert worker.take_pending_audio() == b"2345"
    assert worker.pending_audio_bytes() == 0


def test_mark_ready_returns_pending_audio_for_router_replay_in_order(monkeypatch):
    worker = aw.ASRWorker()
    monkeypatch.setattr(worker, "MAX_PENDING_AUDIO_BYTES", 4)

    worker.feed(b"aa")
    worker.feed(b"bb")
    worker.feed(b"cc")

    pending = worker.mark_ready()
    assert pending == b"bbcc"
    assert worker.pending_audio_bytes() == 0

    # Simulate the future router's ready -> feed replay sequence.
    worker._running = True
    worker.feed(pending)
    assert worker._buffer == bytearray(b"bbcc")


def test_start_replays_pending_audio_into_decode_buffer(monkeypatch):
    fake = _FakeModel([[]])

    async def fake_get_model(_model_name):
        return fake

    monkeypatch.setattr(aw, "_get_model", fake_get_model)
    worker = aw.ASRWorker()
    worker.feed(b"before-ready")

    async def start_and_stop():
        await worker.start()
        assert worker._buffer == bytearray(b"before-ready")
        await worker.stop()

    asyncio.run(start_and_stop())

# ---- clear_buffer ----------------------------------------------------------


def test_clear_buffer_drops_buffered_audio_and_dedupe_cursor():
    """clear_buffer() must reset both _buffer and _emitted_until_ms so stale
    audio from before a new speak() doesn't surface as a phantom partial."""
    fake = _FakeModel([[{"text": "旧", "start": 0, "end": 200}]])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(400))  # buffered but never decoded
    assert len(worker._buffer) > 0
    worker._emitted_until_ms = 9999  # simulate a previous turn
    worker._last_decode_audio_ms = 5000
    worker.clear_buffer()
    assert worker._buffer == bytearray()
    assert worker._emitted_until_ms == 0
    assert worker._last_decode_audio_ms == 0


# ---- overlap dedupe --------------------------------------------------------


def test_overlapping_segments_keep_only_longest(fast_trigger):
    """FunASR sometimes returns multiple hypotheses for the same audio span
    (different start/end, different text but all claiming the same speech).
    The naive join produces repetition like '达到一个什么成果你想拿到你想拿到'.
    The overlap dedupe must keep only the longest text per cluster."""
    fake = _FakeModel([[
        {"text": "达到一个什么成果", "start": 1000, "end": 2500},
        {"text": "你想拿到有个什么成果", "start": 1500, "end": 4000},
        {"text": "你想拿到一个什么成果呢", "start": 2000, "end": 5500},
    ]])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(600))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))
    ev = worker._events.get_nowait()
    # The three segments overlap; longest text wins per cluster.
    assert ev["text"] == "你想拿到一个什么成果呢"


def test_non_overlapping_segments_concatenate(fast_trigger):
    """Legitimate consecutive segments must NOT be merged — dedupe must only
    drop overlapping ones, keep non-overlapping ones as-is."""
    fake = _FakeModel([[
        {"text": "第一句", "start": 1000, "end": 2500},
        {"text": "第二句", "start": 3000, "end": 4500},
        {"text": "第三句", "start": 5000, "end": 6500},
    ]])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(600))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))
    ev = worker._events.get_nowait()
    assert ev["text"] == "第一句第二句第三句"


def test_sentence_after_trim_is_not_filtered_by_old_absolute_cursor(fast_trigger):
    fake = _FakeModel([
        [{"text": "前句", "start": 0, "end": 600}],
        [{"text": "后句", "start": 250, "end": 500}],
    ])
    worker = _make_worker(fake)
    worker.feed(_tone_pcm(600))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))
    worker._events.get_nowait()

    worker.feed(_tone_pcm(300))
    worker.feed(_silence_pcm(250))
    asyncio.run(worker._flush(is_final=False))

    assert worker._events.get_nowait()["text"] == "后句"


def test_odd_pcm_bytes_are_buffered_until_decoder_input_is_even(caplog):
    fake = _FakeModel([[{"text": "偶数", "start": 0, "end": 1}]])
    worker = _make_worker(fake)

    worker.feed(b"\x01")
    worker.feed(b"\x02\x03\x04")
    asyncio.run(worker._flush(is_final=False))

    assert len(fake.calls[0]) == 2
    assert "odd PCM byte" in caplog.text


def test_stop_waits_for_background_flush_and_preserves_input_arriving_during_stop(
    fast_trigger,
):
    class _BlockingModel(_FakeModel):
        def __init__(self):
            super().__init__([
                [{"text": "后台", "start": 0, "end": 400}],
                [{"text": "停止时输入", "start": 0, "end": 400}],
            ])
            self.started = threading.Event()
            self.release = threading.Event()

        def generate(self, input=None, **kwargs):
            self.started.set()
            self.release.wait(timeout=2)
            return super().generate(input=input, **kwargs)

    async def scenario():
        fake = _BlockingModel()
        worker = aw.ASRWorker(chunk_ms=50)
        worker._events = asyncio.Queue()
        worker._model = fake
        worker._model_ready = True
        worker._running = True
        worker.feed(_tone_pcm(400))

        flush_task = asyncio.create_task(worker._flush(is_final=False))
        for _ in range(20):
            if fake.started.is_set():
                break
            await asyncio.sleep(0.01)
        stop_task = asyncio.create_task(worker.stop())
        worker.feed(_tone_pcm(400))
        fake.release.set()
        await asyncio.gather(flush_task, stop_task)
        events = [worker._events.get_nowait(), worker._events.get_nowait()]
        return fake, events

    fake, events = asyncio.run(scenario())
    assert len(fake.calls) == 2
    assert [event["text"] for event in events] == ["后台", "停止时输入"]


def test_concurrent_start_is_idempotent(monkeypatch):
    calls = 0

    async def fake_get_model(_model_name):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return _FakeModel([[]])

    monkeypatch.setattr(aw, "_get_model", fake_get_model)

    async def scenario():
        worker = aw.ASRWorker()
        await asyncio.gather(worker.start(), worker.start())
        task = worker._task
        await worker.stop()
        return task

    task = asyncio.run(scenario())
    assert calls == 1
    assert task is not None


def test_runtime_buffer_is_bounded_while_decode_is_in_flight(fast_trigger):
    class _SlowModel(_FakeModel):
        def generate(self, input=None, **kwargs):
            time.sleep(0.05)
            return super().generate(input=input, **kwargs)

    fake = _SlowModel([[]])

    async def scenario():
        worker = aw.ASRWorker()
        worker._events = asyncio.Queue()
        worker._model = fake
        worker._model_ready = True
        worker._running = True
        worker.feed(_tone_pcm(400))
        flush_task = asyncio.create_task(worker._flush(is_final=False))
        await asyncio.sleep(0.01)
        runtime_audio = bytes(range(256)) * ((worker.MAX_RUNTIME_AUDIO_BYTES + 256) // 256)
        runtime_audio = runtime_audio[:worker.MAX_RUNTIME_AUDIO_BYTES + 256]
        worker.feed(runtime_audio)
        await flush_task
        return worker, runtime_audio

    worker, runtime_audio = asyncio.run(scenario())
    assert len(runtime_audio) > worker.MAX_RUNTIME_AUDIO_BYTES
    assert len(worker._buffer) == worker.MAX_RUNTIME_AUDIO_BYTES
    assert worker._buffer == bytearray(runtime_audio[-worker.MAX_RUNTIME_AUDIO_BYTES:])
