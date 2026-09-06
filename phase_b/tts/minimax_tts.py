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
"""MiniMax T2A v2 WebSocket client (text → PCM audio chunks).

Discovered protocol (no published docs at the URL we tried — 404; reverse-
engineered by probing the WS endpoint on 2026-09-05):

    1. Open WS to {ws_url}?model=...&voice=...&sample_rate=...
       Header `Authorization: Bearer <api_key>`
    2. Server replies  {"event":"connected_success"}
    3. Client sends   {"event":"task_start",
                       "model":...,
                       "voice_setting": {"voice_id":..., "speed":1, "vol":1, "pitch":0},
                       "audio_setting": {"sample_rate":..., "bitrate":128000, "format":"pcm"}}
       Server replies  {"event":"task_started","session_id":...}
    4. Client sends   {"event":"task_continue","text":"..."}
       Server streams {"event":<intermediate>, "data":{"audio":"<hex int16 LE PCM>"}}
       ...then {"event":"task_continued","extra_info":{...}}
    5. Client sends   {"event":"task_finish"}
       Server replies  {"event":"task_finished"}

NOTE: the "voice_id" / "sample_rate" top-level flat schema (probe variant C
in the spike) is rejected with status_code 2202 "invalid event" — they must
be nested under ``voice_setting`` and ``audio_setting``.
NOTE: audio is delivered as a hex string inside JSON, not as raw binary
frames. Each hex string decodes to int16 little-endian PCM bytes at the
sample rate we requested.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import websockets


logger = logging.getLogger(__name__)


# Default settings that worked in our 2026-09-05 spike. Centralised so the
# orchestrator and the standalone probe both use the same payload shape.
#
# IMPORTANT: ``speed`` / ``vol`` / ``pitch`` MUST be ints (1, 1, 0) — floats
# like 1.0 are rejected by MiniMax with status_code 2013
# "invalid params, invalid message format". ``vol`` and ``pitch`` are also
# optional (only ``voice_id`` and ``speed`` are strictly required).
_DEFAULT_VOICE_SETTING = {"speed": 1, "vol": 1, "pitch": 0}
_DEFAULT_AUDIO_SETTING = {"bitrate": 128000, "format": "pcm"}


async def synthesize(
    text: str,
    *,
    ws_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    voice: Optional[str] = None,
    sample_rate: Optional[int] = None,
    timeout_s: Optional[float] = None,
) -> AsyncIterator[bytes]:
    """Yield PCM audio chunks for ``text``. Caller iterates until done.

    On any protocol-level error (failure event, unexpected close, timeout),
    raises ``RuntimeError`` with the server's error message so the
    orchestrator can surface it to the client.
    """
    if not text or not text.strip():
        return

    from phase_b.config import get_settings

    s = get_settings()
    ws_url = ws_url or s.tts_ws_url
    api_key = api_key or s.tts_api_key
    model = model or s.tts_model
    voice = voice or s.tts_voice
    sample_rate = sample_rate or s.tts_sample_rate
    timeout_s = timeout_s if timeout_s is not None else s.tts_timeout_s

    headers = [("Authorization", f"Bearer {api_key}")] if api_key else []
    base = ws_url.rstrip("/") + f"?model={model}&voice={voice}&sample_rate={sample_rate}"

    voice_setting = {**_DEFAULT_VOICE_SETTING, "voice_id": voice}
    audio_setting = {**_DEFAULT_AUDIO_SETTING, "sample_rate": sample_rate}

    async with websockets.connect(
        base, additional_headers=headers, max_size=16 * 1024 * 1024, ping_interval=None
    ) as ws:
        # 1. drain connected_success
        await _expect_event(ws, "connected_success", timeout_s)

        # 2. task_start
        await ws.send(
            json.dumps(
                {
                    "event": "task_start",
                    "model": model,
                    "voice_setting": voice_setting,
                    "audio_setting": audio_setting,
                }
            )
        )
        await _expect_event(ws, "task_started", timeout_s)

        # 3. task_continue with the text → stream PCM until is_final=True.
        #
        # The server sends a stream of ``task_continued`` events, each with a
        # hex-encoded PCM chunk in ``data.audio`` and ``is_final: false``. The
        # last one carries ``is_final: true`` with an empty audio payload —
        # that's our end-of-stream marker, no ``task_finished`` arrives yet.
        await ws.send(json.dumps({"event": "task_continue", "text": text}))
        async for pcm in _drain_audio_until_final(ws, timeout_s):
            yield pcm

        # 4. task_finish → server replies once with ``task_finished`` and
        # closes the connection. No more audio chunks arrive at this stage.
        await ws.send(json.dumps({"event": "task_finish"}))
        final = await _recv_json(ws, timeout_s)
        if final.get("event") != "task_finished":
            raise RuntimeError(f"TTS expected task_finished, got {final!r}")


async def _expect_event(ws, expected: str, timeout_s: float) -> dict:
    """Receive one JSON message and assert it carries ``event == expected``.

    Any other event surfaces as RuntimeError; ``task_failed`` always raises
    with the server's error message.
    """
    msg = await _recv_json(ws, timeout_s)
    ev = msg.get("event")
    if ev == "task_failed":
        raise RuntimeError(f"TTS task_failed: {msg}")
    if ev != expected:
        raise RuntimeError(f"TTS expected event={expected!r} got {ev!r}: {msg}")
    return msg


async def _recv_json(ws, timeout_s: float) -> dict:
    """Receive one message and parse as JSON, with timeout protection.

    The MiniMax T2A v2 protocol never sends raw binary frames — audio is
    hex-encoded in JSON. If we get bytes here, it's a protocol surprise.
    """
    try:
        msg = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    except asyncio.TimeoutError:
        raise RuntimeError(f"TTS recv timeout after {timeout_s}s") from None
    if isinstance(msg, (bytes, bytearray)):
        # Unexpected: T2A v2 streams audio as hex inside JSON, not raw frames.
        raise RuntimeError(
            f"TTS returned unexpected binary frame ({len(msg)} bytes); "
            "expected JSON with hex-encoded audio"
        )
    try:
        return json.loads(msg)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"TTS returned non-JSON text: {msg[:100]!r}") from e


async def _drain_audio_until_final(ws, timeout_s: float) -> AsyncIterator[bytes]:
    """Yield PCM from ``data.audio`` until a ``task_continued`` with
    ``is_final: true`` (or empty audio) arrives. Raises on ``task_failed``."""
    while True:
        msg = await _recv_json(ws, timeout_s)
        ev = msg.get("event")
        if ev == "task_failed":
            raise RuntimeError(f"TTS task_failed: {msg}")
        data = msg.get("data") or {}
        audio_hex = data.get("audio") or ""
        if audio_hex:
            try:
                pcm = bytes.fromhex(audio_hex)
            except ValueError as e:
                raise RuntimeError(f"TTS returned non-hex audio payload: {e!r}") from e
            if pcm:
                yield pcm
        # is_final=true is the explicit end-of-stream signal. Empty audio in
        # a task_continued also marks the end (server's "nothing more" ack).
        if ev == "task_continued":
            if msg.get("is_final") is True or not audio_hex:
                return
        # Intermediate messages (no event field, just data.audio chunks)
        # fall through and loop again.
