# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
"""Regression tests for the new VAD-segmented ASR trigger logic.

The previous ASRWorker sliced the audio buffer into 1s chunks and ran
FunASR on each chunk in isolation — VAD never saw a complete speech
segment, so the decoder returned ``empty speech`` for every chunk and
nothing was ever transcribed. The new ASRWorker accumulates the buffer,
triggers on trailing silence or a 5s cap, runs ``generate(sentence_timestamp=True)``
on the whole buffer, dedupes by sentence ``start`` ms, and trims to an
overlap window.

These tests cover the trigger / dedupe / overlap / final-flush logic
without loading the real FunASR model — they substitute a fake model
that returns canned ``sentence_info`` lists and exercises:
  * silence trigger fires when trailing silence >= 800ms (with >= 1.5s buffered)
  * silence trigger is suppressed when buffer < 1.5s
  * timeout trigger fires when buffer >= 5s even without silence
  * dedupe: a second decode that returns the same sentences emits nothing
  * overlap trim: after flush, only the last OVERLAP_MS of audio remains
  * final flush: stop() runs one last decode marked is_final=True
"""
from __future__ import annotations

import asyncio
import sys
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


def test_model_not_ready_audio_is_bounded_and_replayed_in_order(caplog, monkeypatch):
    worker = aw.ASRWorker()
    monkeypatch.setattr(worker, "MAX_PENDING_AUDIO_BYTES", 4)

    worker.feed(b"aa")
    worker.feed(b"bb")
    worker.feed(b"cc")

    assert worker.pending_audio_bytes() == 4
    assert worker._buffer == bytearray()
    assert "pending ASR audio buffer full" in caplog.text

    worker.mark_ready()
    assert worker._buffer == bytearray()
    assert worker.pending_audio_bytes() == 4
    assert worker.take_pending_audio() == b"bbcc"
    assert worker.pending_audio_bytes() == 0


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
