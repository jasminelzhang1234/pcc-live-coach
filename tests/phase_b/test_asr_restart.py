# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Gap 1 — ASRWorker.restart() unit tests.

We stub AliyunASRClient with a fake that we can drive deterministically.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from typing import AsyncIterator, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# Stub the nls / aliyun SDKs so asr_worker module imports without them
# (the ASRWorker tests don't exercise real Aliyun — they patch the client).
for _stub_pkg, _attrs in [
    ("nls", {"NlsSpeechTranscriber": type("NlsSpeechTranscriber", (), {})}),
]:
    if _stub_pkg not in sys.modules:
        _m = types.ModuleType(_stub_pkg)
        for k, v in _attrs.items():
            setattr(_m, k, v)
        sys.modules[_stub_pkg] = _m
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


class FakeAliyunClient:
    """Stub AliyunASRClient with controllable event stream + lifecycle hooks."""

    def __init__(self, *, events_to_emit: List[dict], start_should_fail: bool = False):
        self._events = list(events_to_emit)
        self._start_should_fail = start_should_fail
        self.start_called = 0
        self.stop_called = 0
        self.feed_called = 0
        self._stopped = False

    async def start(self):
        self.start_called += 1
        # Reset the stop flag on start (real Aliyun client clears state on
        # re-init — without this, restart() never produces fresh events).
        self._stopped = False
        if self._start_should_fail:
            raise RuntimeError("simulated Aliyun start failure")
        return None

    async def stop(self):
        self.stop_called += 1
        self._stopped = True

    def feed(self, pcm: bytes):
        self.feed_called += 1

    async def events(self) -> AsyncIterator[dict]:
        for ev in self._events:
            if self._stopped:
                return
            yield ev


@pytest.fixture
def fake_aliyun(monkeypatch):
    """Patch phase_b.asr.asr_worker.AliyunASRClient with our fake."""
    from phase_b.asr import asr_worker
    captured: List[FakeAliyunClient] = []

    def factory(appkey, ak_id, ak_secret, sample_rate=16000, **kwargs):
        fake = FakeAliyunClient(events_to_emit=[])
        captured.append(fake)
        return fake

    monkeypatch.setattr(asr_worker, "AliyunASRClient", factory)

    # Settings need credentials — set via env.
    monkeypatch.setenv("ALIYUN_ASR_APPKEY", "test-key")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "test-sk")
    return captured


def test_restart_calls_stop_then_start(fake_aliyun):
    """restart() should call stop() then start() on the same client."""
    from phase_b.asr.asr_worker import ASRWorker

    async def run():
        worker = ASRWorker(sample_rate=16000)
        await worker.start()
        first = fake_aliyun[0]
        await worker.restart()
        return first

    first = asyncio.run(run())
    # initial start + restart's start
    assert first.start_called == 2, "restart() must call client.start() a second time"
    # initial stop didn't run (start() doesn't stop), but restart() does call stop
    assert first.stop_called == 1, "restart() must call client.stop() exactly once"


def test_restart_resets_events_queue(fake_aliyun):
    """After restart(), events() yields from the fresh queue (not stale events)."""
    from phase_b.asr.asr_worker import ASRWorker

    async def run():
        worker = ASRWorker(sample_rate=16000)
        await worker.start()
        # Drain whatever the initial start might produce. Then mutate the
        # fake's events list before restart, so we can assert the new queue
        # actually carries the fresh event (proving the queue was reset).
        fake_aliyun[0]._events = [{"event": "partial", "text": "fresh", "is_utterance_end": True}]
        await worker.restart()
        # Poll the queue with a small timeout to absorb pump-loop scheduling latency.
        ev = await asyncio.wait_for(worker.events().__anext__(), timeout=2.0)
        return ev

    ev = asyncio.run(run())
    assert ev["text"] == "fresh", "events queue must be reset on restart"


def test_restart_propagates_start_failure(fake_aliyun):
    """If the underlying client.start() raises on restart, the exception propagates."""
    from phase_b.asr.asr_worker import ASRWorker

    async def run():
        worker = ASRWorker(sample_rate=16000)
        # Replace the auto-injected fake with one whose start() raises.
        # This is what the production code path will hit on the next start().
        failing = FakeAliyunClient(events_to_emit=[], start_should_fail=True)
        worker._client = failing
        # Mark worker as running so restart()'s stop() runs (otherwise it
        # returns early without exercising the failure path).
        worker._running = True
        await worker.restart()

    with pytest.raises(RuntimeError, match="simulated Aliyun start failure"):
        asyncio.run(run())
