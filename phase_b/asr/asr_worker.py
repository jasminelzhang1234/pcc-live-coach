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
"""ASR worker — wraps AliyunASRClient with a stable event contract.

History:
- 2026-08: v1 used FunASR (SenseVoiceSmall offline + 1.8s silence trigger).
  Never reached end-to-end success.
- 2026-09-06: swapped to Aliyun NLS streaming WebSocket (real-time partial).

External contract:

    worker = ASRWorker(sample_rate=...)
    await worker.start()
    worker.feed(pcm_bytes)              # 16kHz int16 mono PCM, non-blocking
    async for ev in worker.events():    # {"event": "partial"|"error"|"done", ...}
        ...
    await worker.stop()

Event schema (unchanged):
    {"event": "partial", "text", "audio_ms", "latency_ms", "is_utterance_end": bool}
    {"event": "error",   "error": "..."}
    {"event": "done"}

is_utterance_end=True is the trigger router.py uses for auto-submit.
With Aliyun NLS, this fires on SentenceEnd (end of sentence by max_sentence_silence).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Optional

from phase_b.asr.aliyun_client import AliyunASRClient


logger = logging.getLogger(__name__)


class ASRWorker:
    """Wrapper around AliyunASRClient preserving the legacy FunASR event schema.

    The internal client is a single AliyunASRClient (one task_id per worker).
    Events from the client are pumped into an asyncio.Queue so callers can
    `async for` over them without coupling to the websocket iteration directly.
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        # Aliyun NLS reads credentials from .env via phase_b.config.get_settings().
        from phase_b.config import get_settings
        s = get_settings()
        if not (s.aliyun_asr_appkey and s.aliyun_access_key_id and s.aliyun_access_key_secret):
            raise RuntimeError(
                "阿里云 ASR 凭证未配置。需要在 .env 设置 ALIYUN_ASR_APPKEY / "
                "ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET(见 "
                "phase_b/_reports/aliyun-asr-setup-2026-09-06.md)"
            )
        self._sample_rate = sample_rate
        self._client = AliyunASRClient(
            appkey=s.aliyun_asr_appkey,
            ak_id=s.aliyun_access_key_id,
            ak_secret=s.aliyun_access_key_secret,
            sample_rate=sample_rate,
        )
        self._events: Optional[asyncio.Queue] = None
        self._running = False
        self._lifecycle_lock: Optional[asyncio.Lock] = None
        self._pump_task: Optional[asyncio.Task] = None
        self._t_start: float = 0.0

    async def start(self) -> None:
        if self._lifecycle_lock is None:
            self._lifecycle_lock = asyncio.Lock()
        async with self._lifecycle_lock:
            if self._running:
                return
            self._events = asyncio.Queue()
            self._t_start = time.time()
            try:
                await self._client.start()
            except Exception as e:
                logger.exception("aliyun-asr client.start failed")
                await self._events.put({"event": "error", "error": f"start failed: {e}"})
                raise
            self._running = True
            self._pump_task = asyncio.create_task(self._pump_loop(), name="asr-pump")

    async def stop(self) -> None:
        if self._lifecycle_lock is None:
            self._lifecycle_lock = asyncio.Lock()
        async with self._lifecycle_lock:
            if not self._running:
                return
            self._running = False
            try:
                await self._client.stop()
            except Exception:
                logger.exception("client.stop failed")
            if self._pump_task is not None:
                self._pump_task.cancel()
                try:
                    await self._pump_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._pump_task = None

    async def restart(self) -> None:
        """Stop and re-start in place, with a fresh events queue.

        Reused by router.py when _pump_loop dies unexpectedly (e.g. Aliyun WS
        drops mid-session). Caller MUST not call feed() between stop() and
        the new start() finishing — feed() is silently dropped while not
        _running.

        Exponential backoff is the caller's responsibility (router owns the
        outer retry budget — see pump_asr in router.py).
        """
        await self.stop()
        self._events = asyncio.Queue()
        await self.start()

    def feed(self, pcm_bytes: bytes) -> None:
        """Push PCM to the underlying client. Non-blocking.

        Pre-running calls are silently dropped (matches old FunASR behavior
        where pre-load audio was queued, but Aliyun doesn't have a
        model-loading window — credentials are read at process start).
        """
        if not self._running or not pcm_bytes:
            return
        self._client.feed(pcm_bytes)

    async def _pump_loop(self) -> None:
        """Forward AliyunASRClient events to the queue until 'done' or error."""
        if self._events is None:
            return
        try:
            async for ev in self._client.events():
                if self._events is None:
                    return
                # Rewrite 'final' → 'partial' with is_utterance_end=True for
                # backward compat with router.py pump_asr() (which only listens
                # to event=="partial"). Aliyun's SentenceEnd already carries
                # is_utterance_end=True.
                if ev.get("event") == "final":
                    ev = {
                        "event": "partial",
                        "text": ev.get("text", ""),
                        "audio_ms": ev.get("audio_ms", 0),
                        "latency_ms": ev.get("latency_ms", 0),
                        "is_utterance_end": True,
                        "is_final": True,
                    }
                await self._events.put(ev)
                if ev.get("event") == "done":
                    return
                if ev.get("event") == "error" and ev.get("fatal"):
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("pump_loop crashed")
            try:
                await self._events.put({"event": "error", "error": str(e)})
            except Exception:
                pass

    async def events(self) -> AsyncIterator[dict]:
        while True:
            if self._events is None:
                return
            ev = await self._events.get()
            yield ev