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
"""Step 6 smoke: run_turn() with mocked LLM (httpx MockTransport) + mocked TTS (mock WS).

Verifies the orchestrator wires LLM → TTS into a single async stream that yields:
  {"kind": "reply_text", "text": "..."}
  bytes (PCM)
  {"kind": "reply_end"}
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# Mock LLM response
MOCK_LLM_REPLY = "我最近工作压力很大,想找人说说。"


async def main() -> None:
    # ---- Mock LLM via httpx MockTransport ----
    async def llm_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "messages" in body
        assert any("persona" in (m.get("role") or m.get("content", "")) for m in body["messages"]) or any(
            m.get("role") == "system" for m in body["messages"]
        ), f"expected system prompt in messages, got: {body}"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": MOCK_LLM_REPLY},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    # Patch chat() by monkey-patching phase_b.llm.minimax_client module after import
    from phase_b.llm import minimax_client
    from phase_b.coach.orchestrator import run_turn
    from phase_b.personas.loader import load as load_persona

    # Stub chat to call MockTransport directly.
    transport = httpx.MockTransport(llm_handler)

    async def stub_chat(messages, system=None, **kwargs):
        # Replicate the real chat() shape but using the mock transport.
        async with httpx.AsyncClient(transport=transport) as h:
            r = await h.post(
                "http://stub/v1/chat/completions",
                json={"messages": ([{"role": "system", "content": system}] if system else []) + list(messages)},
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    minimax_client.chat = stub_chat

    # Also patch the orchestrator's local `chat` binding (since it does
    # `from phase_b.llm.minimax_client import chat`, that name is bound at
    # orchestrator module load — patching minimax_client.chat alone won't
    # redirect the call).
    from phase_b.coach import orchestrator as orch
    orch.chat = stub_chat

    # ---- Mock TTS via mock WS server ----
    PCM = b"\x00\x01" * 1600  # 100ms of "audio" at 16kHz

    async def mock_tts(ws, path=None):
        await ws.recv()  # text request
        for _ in range(3):
            await ws.send(PCM)
        await ws.send(json.dumps({"event": "finished"}))

    server = await websockets.serve(mock_tts, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    # Patch synthesize() to point at the mock.
    from phase_b.tts import minimax_tts

    async def stub_synthesize(text, **kwargs):
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"text": text}))
            while True:
                msg = await ws.recv()
                if isinstance(msg, (bytes, bytearray)):
                    if msg:
                        yield bytes(msg)
                else:
                    obj = json.loads(msg)
                    if obj.get("event") == "finished":
                        return

    minimax_tts.synthesize = stub_synthesize
    from phase_b.coach import orchestrator as orch
    orch.synthesize = stub_synthesize

    # ---- Run the orchestrator ----
    # First, verify a persona loads.
    p = load_persona("vec-01")
    print(f"[smoke] persona loaded: {p['id']} (difficulty={p['difficulty']})")

    print("[smoke] running turn...")
    events = []
    async for ev in run_turn(
        session_id="test-session-01",
        persona_id="vec-01",
        client_text="你最近怎么样?",
    ):
        if isinstance(ev, dict):
            events.append(("dict", ev.get("kind"), ev.get("text", ev.get("error", ""))))
        else:
            events.append(("bytes", len(ev)))

    server.close()
    await server.wait_closed()

    print(f"[smoke] events:")
    for e in events:
        print(f"  {e}")
    kinds = [e for e in events if e[0] == "dict"]
    audio_chunks = [e for e in events if e[0] == "bytes"]
    assert any(k[1] == "reply_text" for k in kinds), "expected reply_text event"
    assert any(k[1] == "reply_end" for k in kinds), "expected reply_end event"
    assert len(audio_chunks) == 3, f"expected 3 audio chunks, got {len(audio_chunks)}"
    reply_text = next(k[2] for k in kinds if k[1] == "reply_text")
    assert reply_text == MOCK_LLM_REPLY, f"expected mocked reply, got {reply_text!r}"
    print(f"[smoke] OK — reply_text={reply_text!r}, audio chunks={len(audio_chunks)}")


if __name__ == "__main__":
    asyncio.run(main())