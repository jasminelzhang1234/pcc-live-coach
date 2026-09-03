# Copyright 2026 the maintainer Zhang. Licensed under the Apache License, Version 2.0
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
"""In-process ASR worker using FunASR AutoModel.

Why in-process (not `funasr.bin.realtime_ws` subprocess)?
- The streaming model `FunAudioLLM/Fun-ASR-Nano-2512` requires vLLM, which
  is heavy and Mac-incompatible out of the box.
- `SenseVoiceSmall` (offline) is already validated in our venv at
  RTF 0.029 — fast enough for V1 chunked streaming.
- Trade-off accepted: no sub-word partial; we emit a sentence-level "partial"
  every ~chunk_ms, then a "final" when VAD signals end-of-utterance.

API:
    worker = ASRWorker(model="iic/SenseVoiceSmall")
    await worker.start()
    worker.feed(pcm_bytes)             # 16kHz int16 mono PCM
    async for ev in worker.events():   # {"event": "partial", ...} or {"event": "final", ...}
        ...
    await worker.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, AsyncIterator, Deque, List, Optional

import numpy as np


logger = logging.getLogger(__name__)


# Process-wide cache: {model_name: model_object}. Loading AutoModel is
# expensive (~3s); share it across all WS sessions in the same process.
_MODEL_CACHE: dict[str, Any] = {}
_MODEL_LOAD_LOCK = asyncio.Lock()


async def _get_model(model_name: str) -> Any:
    """Return a loaded AutoModel, initializing the cache entry once per process."""
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]
    # Import funasr OUTSIDE the lock so concurrent coroutines waiting on the
    # lock don't also block each other on the import.
    from funasr import AutoModel  # type: ignore

    async with _MODEL_LOAD_LOCK:
        if model_name in _MODEL_CACHE:
            return _MODEL_CACHE[model_name]
        loop = asyncio.get_running_loop()

        def _load():
            logger.info("ASR loading model %s ...", model_name)
            t0 = time.time()
            m = AutoModel(
                model=model_name,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device="cpu",
                disable_update=True,
            )
            logger.info("ASR model loaded in %.1fs", (time.time() - t0))
            return m

        model = await loop.run_in_executor(None, _load)
        _MODEL_CACHE[model_name] = model
        return model


class ASRWorker:
    def __init__(
        self,
        model: str = "iic/SenseVoiceSmall",
        sample_rate: int = 16000,
        chunk_ms: int = 1000,
        language: str = "auto",
    ) -> None:
        self._model_name = model
        self._sample_rate = sample_rate
        self._chunk_ms = chunk_ms
        self._language = language
        self._model: Optional[Any] = None
        self._buffer = bytearray()
        self._events: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._model = await _get_model(self._model_name)
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def feed(self, pcm_bytes: bytes) -> None:
        """Append raw 16kHz int16 mono PCM. Called from the WS handler."""
        if not self._running:
            return
        self._buffer.extend(pcm_bytes)

    async def _run_loop(self) -> None:
        loop = asyncio.get_running_loop()
        chunk_samples = self._sample_rate * self._chunk_ms // 1000
        chunk_bytes = chunk_samples * 2  # int16 = 2 bytes

        while self._running:
            await asyncio.sleep(self._chunk_ms / 1000.0)
            if len(self._buffer) < chunk_bytes:
                continue
            # Take a snapshot of the buffer, run inference on it.
            buf_copy = bytes(self._buffer[:chunk_bytes])
            self._buffer = self._buffer[chunk_bytes:]
            try:
                result = await loop.run_in_executor(None, self._decode, buf_copy)
            except Exception as e:
                logger.exception("ASR decode failed")
                await self._events.put({"event": "error", "error": str(e)})
                continue
            if result:
                await self._events.put({"event": "partial", **result})

    def _decode(self, pcm_bytes: bytes) -> dict:
        """Run offline ASR on a chunk. Returns dict with text, duration, latency_ms."""
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        t0 = time.time()
        out = self._model.generate(
            input=audio,
            language=self._language,
            batch_size=1,
        )
        latency_ms = (time.time() - t0) * 1000
        if not out or not out[0].get("text"):
            return {}
        # Strip sensevoice special tokens like <|zh|><|NEUTRAL|><|Speech|><|withitn|>
        import re

        text = re.sub(r"<\|[^|]*\|>", "", out[0]["text"]).strip()
        return {
            "text": text,
            "audio_ms": int(len(pcm_bytes) / 2 / self._sample_rate * 1000),
            "latency_ms": int(latency_ms),
        }

    async def events(self) -> AsyncIterator[dict]:
        while True:
            ev = await self._events.get()
            yield ev