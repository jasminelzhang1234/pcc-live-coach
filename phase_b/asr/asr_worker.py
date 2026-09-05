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
    """Streaming ASR using FunASR's SenseVoiceSmall + fsmn-vad.

    Design (rewrite of the old FIFO-chunk decoder):

    The previous implementation sliced the audio buffer into 1s chunks and
    ran ``generate()`` on each chunk in isolation. FunASR's VAD runs on the
    whole input — feeding it an isolated 1s slice meant the VAD almost
    never saw a complete speech segment, so every chunk came back as
    ``empty speech`` and the user was never transcribed.

    New behaviour:

    * Buffer all incoming PCM (no FIFO slicing).
    * Trigger a decode when EITHER:
      - the trailing ``silence_ms`` of the buffer is below the silence RMS
        threshold AND the buffer already holds ``>= min_audio_ms`` of audio
        (i.e. the user has paused long enough for the sentence to be over);
      - OR the buffer has accumulated ``>= max_audio_ms`` of audio (backstop
        so we never starve the UI if the user talks continuously).
    * Each decode runs ``generate(sentence_timestamp=True)`` against the
    *entire* current buffer. FunASR's VAD now sees the full audio and emits
    one ``sentence_info`` per detected segment, each with absolute
    ``start``/``end`` ms offsets into the buffer.
    * We track the highest ``end`` ms we have already emitted
    (``_emitted_until_ms``) and only emit segments whose ``start`` is past
    ``_emitted_until_ms - overlap_ms`` (the overlap window). This prevents
    double-counting the tail of the previous decode.
    * After each partial decode, we keep the last ``overlap_ms`` of audio in
    the buffer as VAD context for the next round; everything before that is
    discarded.
    * On ``stop()`` we run one last decode so the final sentence of the
    session is never lost to the overlap window.

    Events emitted on ``events()``:

    * ``{"event": "partial", "text", "audio_ms", "latency_ms", "is_final"}``
      — ``is_final`` is True only for the last decode done inside ``stop()``.
    * ``{"event": "error", "error": str}`` on decode failure.
    """

    # Decode triggers.
    MIN_AUDIO_MS = 1500        # need ≥1.5s of audio before silence can trigger
    MAX_AUDIO_MS = 8000        # hard cap → flush even without silence
    MAX_PENDING_AUDIO_BYTES = 32000  # bound audio received while model loads
    SILENCE_MS = 1200          # trailing silence needed to trigger flush (was 800 — too eager; users were committed mid-thought)
    OVERLAP_MS = 1500          # keep last 1.5s as VAD context for next round
    SILENCE_RMS_THRESHOLD = 200  # int16 RMS below this counts as silence

    def __init__(
        self,
        model: str = "iic/SenseVoiceSmall",
        sample_rate: int = 16000,
        chunk_ms: int = 100,    # poll interval (was 1000); decode triggers are separate
        language: str = "auto",
    ) -> None:
        self._model_name = model
        self._sample_rate = sample_rate
        self._chunk_ms = chunk_ms
        self._language = language
        self._model: Optional[Any] = None
        self._buffer = bytearray()
        self._pending_audio: Deque[bytes] = deque()
        self._pending_audio_size = 0
        self._events: Optional[asyncio.Queue] = None  # created in start() to bind to running loop
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._model_ready = False
        self._emitted_until_ms: int = 0  # highest sentence end already emitted
        self._last_decode_audio_ms: int = 0  # buffer length at last successful decode start

    async def start(self) -> None:
        if self._running:
            return
        self._events = asyncio.Queue()
        self._model = await _get_model(self._model_name)
        pending_audio = self.mark_ready()
        self._running = True
        if pending_audio:
            self._buffer.extend(pending_audio)
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # Final flush so the very last sentence isn't lost to the overlap window.
        try:
            await self._flush(is_final=True)
        except Exception:
            logger.exception("final flush failed")
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def feed(self, pcm_bytes: bytes) -> None:
        """Append raw 16kHz int16 mono PCM. Called from the WS handler."""
        if self._running:
            self._buffer.extend(pcm_bytes)
            return
        if not self._model_ready:
            self._pending_audio.append(bytes(pcm_bytes))
            self._pending_audio_size += len(pcm_bytes)
            overflow = self._pending_audio_size - self.MAX_PENDING_AUDIO_BYTES
            if overflow > 0:
                logger.warning("pending ASR audio buffer full; dropping oldest audio")
            while overflow > 0:
                dropped = self._pending_audio.popleft()
                if len(dropped) <= overflow:
                    overflow -= len(dropped)
                    self._pending_audio_size -= len(dropped)
                    continue
                kept = dropped[overflow:]
                self._pending_audio.appendleft(kept)
                self._pending_audio_size -= overflow
                overflow = 0

    def pending_audio_bytes(self) -> int:
        """Return the number of bytes queued while the model was not ready."""
        return self._pending_audio_size

    def mark_ready(self) -> bytes:
        """Mark ready and return all pre-ready audio for ordered replay."""
        self._model_ready = True
        pending = b"".join(self._pending_audio)
        self._pending_audio.clear()
        self._pending_audio_size = 0
        return pending

    def take_pending_audio(self) -> bytes:
        """Take and clear pre-ready audio for the caller to feed explicitly."""
        pending = b"".join(self._pending_audio)
        self._pending_audio.clear()
        self._pending_audio_size = 0
        return pending

    def clear_buffer(self) -> None:
        """Discard all buffered audio and reset the dedupe cursor.

        Call this when a new turn starts so any audio left over from the
        previous utterance (or stale mic-bleed captured during TTS playback
        in the gap before reply_end fired the silence trigger) doesn't get
        committed as the first partial of the new turn.
        """
        self._buffer = bytearray()
        self._emitted_until_ms = 0
        self._last_decode_audio_ms = 0

    def _buffer_audio_ms(self) -> int:
        return len(self._buffer) * 1000 // (self._sample_rate * 2)

    def _trailing_silence_ms(self) -> int:
        """Length of the trailing silence in the buffer, in ms.

        Walks back from the buffer tail in 100ms windows, returning the
        duration of consecutive windows whose int16 RMS is below the
        silence threshold. Returns 0 if the very last window is loud.
        """
        samples_per_window = self._sample_rate // 10  # 100ms
        bytes_per_window = samples_per_window * 2
        if len(self._buffer) < bytes_per_window:
            return 0
        n_windows = len(self._buffer) // bytes_per_window
        silence = 0
        for i in range(n_windows - 1, -1, -1):
            start = i * bytes_per_window
            chunk = self._buffer[start : start + bytes_per_window]
            samples = np.frombuffer(chunk, dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
            if rms < self.SILENCE_RMS_THRESHOLD:
                silence += 100
            else:
                break
        return silence

    async def _run_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            await asyncio.sleep(self._chunk_ms / 1000.0)
            if not self._should_flush():
                continue
            try:
                await self._flush(is_final=False)
            except Exception:
                logger.exception("flush failed")

    def _should_flush(self) -> bool:
        audio_ms = self._buffer_audio_ms()
        if audio_ms < self.MIN_AUDIO_MS:
            return False
        if audio_ms >= self.MAX_AUDIO_MS:
            return True
        # Need to have grown past the last decode start so we don't re-decode
        # the same audio twice while paused.
        if audio_ms <= self._last_decode_audio_ms:
            return False
        return self._trailing_silence_ms() >= self.SILENCE_MS

    async def _flush(self, is_final: bool) -> None:
        loop = asyncio.get_running_loop()
        if not self._buffer:
            return
        buf_copy = bytes(self._buffer)
        audio_ms = self._buffer_audio_ms()
        is_utterance_end = is_final or (
            self._trailing_silence_ms() >= self.SILENCE_MS
        )
        self._last_decode_audio_ms = self._buffer_audio_ms()
        try:
            result = await loop.run_in_executor(None, self._decode, buf_copy, is_final)
        except Exception as e:
            logger.exception("ASR decode failed")
            await self._events.put({"event": "error", "error": str(e)})
            return
        if result is None:
            logger.info("asr flush → no new sentences (VAD found none)")
            return  # no new sentences
        if result.get("text"):
            result["is_utterance_end"] = is_utterance_end
            logger.info("asr flush → emitting partial: %r", result.get("text"))
            await self._events.put({"event": "partial", **result})
        # Trim buffer: keep the last OVERLAP_MS as context for VAD next round.
        overlap_bytes = self._sample_rate * self.OVERLAP_MS // 1000 * 2
        if len(self._buffer) > overlap_bytes:
            self._buffer = self._buffer[-overlap_bytes:]
            # Anything we kept already lives in the overlap window — don't
            # re-emit it next time.
            self._last_decode_audio_ms = self._buffer_audio_ms()

    def _decode(self, pcm_bytes: bytes, is_final: bool) -> Optional[dict]:
        """Run VAD-segmented ASR on the whole buffer. Returns the joined
        text of newly-finished sentences, or None if nothing new."""
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio_ms = int(len(pcm_bytes) / 2 / self._sample_rate * 1000)
        t0 = time.time()
        out = self._model.generate(
            input=audio,
            language=self._language,
            batch_size=1,
            sentence_timestamp=True,
        )
        latency_ms = int((time.time() - t0) * 1000)
        if not out:
            return None
        sentence_info = out[0].get("sentence_info") or []
        # sentence_info may be empty if the VAD didn't fire (pure silence).
        if not sentence_info:
            return None
        import re

        # Only emit sentences that start past the dedupe window.
        threshold_ms = self._emitted_until_ms - self.OVERLAP_MS
        new_sentences = []
        seen_keys: set = set()  # dedupe VAD segments that share the same (start,end)
        for s in sentence_info:
            try:
                start = int(s["start"])
                end = int(s["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if start < threshold_ms:
                continue
            txt = re.sub(r"<\|[^|]*\|>", "", s.get("text", "")).strip()
            if not txt:
                continue
            # SenseVoiceSmall sometimes returns duplicate (start,end) segments
            # that the naive "".join() turns into "abcabc" garbage — drop them.
            key = (start, end, txt)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            new_sentences.append((start, end, txt))
        if not new_sentences:
            return None
        # Overlap dedupe: FunASR sometimes returns multiple hypotheses for
        # the same audio span (e.g. 5 overlapping segments for one user
        # sentence). The naive "".join() concatenates them all, producing
        # repetition like "达到一个什么成果你想拿到有个什么成果你想拿到".
        # Sort by start, then for each cluster of overlapping segments keep
        # only the longest text — it's the most complete ASR hypothesis.
        if len(new_sentences) > 1:
            new_sentences.sort(key=lambda x: x[0])
            deduped = [new_sentences[0]]
            for s_start, s_end, s_txt in new_sentences[1:]:
                prev_start, prev_end, prev_txt = deduped[-1]
                if s_start < prev_end:
                    # Overlap with previous — keep the longer text.
                    if len(s_txt) > len(prev_txt):
                        deduped[-1] = (s_start, s_end, s_txt)
                    continue
                deduped.append((s_start, s_end, s_txt))
            new_sentences = deduped
        # Advance the dedupe cursor to the end of the newest emitted sentence.
        self._emitted_until_ms = max(end for _, end, _ in new_sentences)
        joined = "".join(t for _, _, t in new_sentences)
        try:
            logger.warning("DEBUG joined: %r", joined)
        except Exception:
            pass
        return {
            "text": joined,
            "audio_ms": audio_ms,
            "latency_ms": latency_ms,
            "is_final": is_final,
        }

    async def events(self) -> AsyncIterator[dict]:
        while True:
            ev = await self._events.get()
            yield ev