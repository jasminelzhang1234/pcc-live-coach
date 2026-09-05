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
"""Step 4 smoke: LLM client uses MockTransport — no network."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.llm import chat  # noqa: E402


def mock_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["model"], "model missing"
    assert body["messages"], "messages missing"
    # Echo back a canned Chinese greeting for the user message.
    user_msg = next((m for m in body["messages"] if m["role"] == "user"), None)
    sys_msg = next((m for m in body["messages"] if m["role"] == "system"), None)
    reply = f"你好,教练已收到:{user_msg['content'][:20] if user_msg else ''}"
    if sys_msg:
        reply += f"(system: {sys_msg['content'][:20]})"
    payload = {
        "id": "mock-1",
        "model": body["model"],
        "choices": [{"message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }
    return httpx.Response(200, json=payload)


async def main() -> None:
    transport = httpx.MockTransport(mock_handler)
    reply = await chat(
        messages=[{"role": "user", "content": "你好,我最近遇到一些管理难题"}],
        system="reply briefly",
        base_url="http://mock.local",
        api_key="sk-test",
        model="mock-model",
        max_tokens=50,
        transport=transport,
    )
    print("[smoke] LLM reply:", reply)
    assert "你好" in reply, "reply should contain Chinese greeting"
    assert "你好,我最近遇到一些管理难题" in reply, "reply should echo user"
    assert "reply briefly" in reply, "reply should include system"
    print("[smoke] OK")


if __name__ == "__main__":
    asyncio.run(main())