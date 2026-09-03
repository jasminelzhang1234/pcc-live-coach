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
"""MiniMax T2A WebSocket client (text → PCM audio chunks).

NOTE: The MiniMax T2A WS protocol is not officially published in detail; the
spike team never validated it. This implementation follows the most common
WebSocket-TTS pattern (send JSON text, receive binary frames). The exact
message schema MUST be cross-checked against MiniMax's API docs at the first
real key test. For now we:
  - Open WS to {ws_url}?model=...&voice=...&sample_rate=...
  - Header `Authorization: Bearer <api_key>`
  - Send `{"text": "..."}` (or chunked text messages if streaming)
  - Receive binary PCM frames
  - Receive a final JSON `{"event": "finished"}` to know we're done
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import websockets


logger = logging.getLogger(__name__)


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
    """Yield PCM audio chunks for `text`. Caller iterates until done."""
    from phase_b.config import get_settings

    s = get_settings()
    ws_url = ws_url or s.tts_ws_url
    api_key = api_key or s.tts_api_key
    model = model or s.tts_model
    voice = voice or s.tts_voice
    sample_rate = sample_rate or s.tts_sample_rate
    timeout_s = timeout_s if timeout_s is not None else s.tts_timeout_s

    headers = [("Authorization", f"Bearer {api_key}")] if api_key else []
    # Strip trailing slash, ensure trailing slash for ws_url + path join.
    base = ws_url.rstrip("/") + f"?model={model}&voice={voice}&sample_rate={sample_rate}"

    async with websockets.connect(base, additional_headers=headers, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"text": text}))
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.warning("TTS recv timeout after %ss", timeout_s)
                return
            if isinstance(msg, (bytes, bytearray)):
                if msg:
                    yield bytes(msg)
            else:
                try:
                    obj = json.loads(msg)
                except json.JSONDecodeError:
                    logger.warning("TTS sent non-JSON text: %r", msg[:100])
                    continue
                ev = obj.get("event")
                if ev in ("finished", "done", "complete"):
                    return
                if ev == "error":
                    raise RuntimeError(f"TTS server error: {obj}")