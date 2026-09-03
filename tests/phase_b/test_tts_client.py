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
"""Step 5 smoke: spin up a local mock WS server, run TTS client through it."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import websockets


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.tts.minimax_tts import synthesize  # noqa: E402


# Fake "voice" — 100ms of silence at 16kHz int16 mono = 3200 bytes.
PCM_CHUNK = b"\x00\x00" * 1600


async def mock_tts_server(ws, path=None):
    """Receive a text request, reply with 3 PCM chunks then a 'finished' event."""
    first = await ws.recv()
    obj = json.loads(first)
    assert obj["text"], "TTS client should send text"
    # Send 3 fake PCM chunks (100ms each).
    for _ in range(3):
        await ws.send(PCM_CHUNK)
    await ws.send(json.dumps({"event": "finished"}))
    await ws.close()


async def main() -> None:
    # Start mock server on a free port.
    server = await websockets.serve(mock_tts_server, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    print(f"[smoke] mock TTS server on ws://127.0.0.1:{port}")

    ws_url = f"ws://127.0.0.1:{port}"
    chunks = []
    async for chunk in synthesize(
        text="你好,世界",
        ws_url=ws_url,
        api_key="sk-test",
        model="mock-tts",
        voice="mock-voice",
        sample_rate=16000,
        timeout_s=5.0,
    ):
        chunks.append(chunk)
        print(f"[smoke] chunk {len(chunks)}: {len(chunk)} bytes")

    server.close()
    await server.wait_closed()
    assert len(chunks) == 3, f"expected 3 chunks, got {len(chunks)}"
    assert all(len(c) == 3200 for c in chunks), "expected 3200-byte PCM chunks"
    print(f"[smoke] OK — {len(chunks)} chunks, total {sum(len(c) for c in chunks)} bytes")


if __name__ == "__main__":
    asyncio.run(main())