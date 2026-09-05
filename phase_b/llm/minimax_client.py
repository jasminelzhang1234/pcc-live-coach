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
"""MiniMax / OpenAI-compatible LLM client.

Uses raw HTTP via httpx (no SDK dependency). Single async `chat()` entry point.

For testing without network: pass a custom `transport=httpx.MockTransport(...)`.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Mapping, Optional

import httpx


logger = logging.getLogger(__name__)


def _messages_with_system(
    messages: Iterable[Mapping[str, str]],
    system: Optional[str],
) -> List[dict]:
    out: List[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        out.append({"role": m["role"], "content": m["content"]})
    return out


async def chat(
    messages: Iterable[Mapping[str, str]],
    system: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    timeout_s: Optional[float] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> str:
    """Send a chat completion request. Returns the assistant text.

    All config params override `phase_b.config.Settings` if provided (handy for tests).
    """
    from phase_b.config import get_settings

    s = get_settings()
    base_url = (base_url or s.llm_base_url).rstrip("/")
    api_key = api_key or s.llm_api_key
    model = model or s.llm_model
    max_tokens = max_tokens if max_tokens is not None else s.llm_max_tokens
    temperature = temperature if temperature is not None else s.llm_temperature
    timeout_s = timeout_s if timeout_s is not None else s.llm_timeout_s

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": model,
        "messages": _messages_with_system(messages, system),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM response missing choices: {data!r}")
    msg = choices[0].get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError(f"LLM response empty content: {data!r}")
    logger.info(
        "LLM reply: model=%s tokens=%s preview=%r",
        model,
        data.get("usage", {}).get("completion_tokens"),
        text[:60],
    )
    return text