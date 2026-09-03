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
"""Coach orchestrator.

A "turn" pipeline: client_text (post-ASR) → LLM reply (with persona context)
→ TTS PCM chunks.

The WS handler (Step 6) decides WHEN to call run_turn(). V1 uses an explicit
commit (browser sends a JSON {"cmd": "speak"}); Step 7 will add VAD-triggered
or barge-in-triggered commits.

Yield protocol: each item is one of:
    {"kind": "reply_text", "text": "..."}    — coach reply text (for transcript)
    {"kind": "audio", "pcm": bytes}           — TTS PCM chunk (browser plays)
    {"kind": "reply_end"}                     — TTS finished
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Dict, List, Optional, Union

from phase_b.llm.minimax_client import chat
from phase_b.personas.loader import load as load_persona
from phase_b.tts.minimax_tts import synthesize


logger = logging.getLogger(__name__)

TurnEvent = Union[Dict[str, object], bytes]


def _build_system_prompt(persona_id: str) -> str:
    """Compose a system prompt from persona sections + hard rules."""
    p = load_persona(persona_id)
    rules = p.get("hard_rules") or []
    rules_block = "\n".join(f"- {r}" for r in rules) if isinstance(rules, list) else str(rules)
    return (
        "你正在扮演一名 ICF 教练陪练对象。\n"
        f"persona_id: {p.get('id')}\n"
        f"难度: {p.get('difficulty')}\n\n"
        "## 不可越界硬约束\n"
        f"{rules_block}\n\n"
        "## 风格\n"
        f"{p.get('sections', {}).get('语言风格', '')}\n\n"
        "## 反应规则\n"
        f"{p.get('sections', {}).get('反应规则表', '')}\n\n"
        "请保持角色。每轮教练说完后,你按 persona 反应表回应(简短,1-3 句)。"
    )


async def run_turn(
    *,
    session_id: str,
    persona_id: str,
    client_text: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> AsyncIterator[TurnEvent]:
    """Run one coach turn: LLM reply → TTS audio chunks.

    Yields dicts (control events) interleaved with raw PCM bytes for audio.
    Caller is responsible for distinguishing them; a simple isinstance check
    suffices (bytes vs dict).
    """
    if not client_text or not client_text.strip():
        return

    history = history or []
    system = _build_system_prompt(persona_id)
    messages: List[Dict[str, str]] = list(history) + [{"role": "user", "content": client_text}]

    logger.info("[%s] LLM call (persona=%s, text=%r)", session_id, persona_id, client_text[:40])
    try:
        reply = await chat(messages=messages, system=system)
    except Exception as e:
        logger.exception("[%s] LLM failed", session_id)
        print(f"[orch] LLM FAILED: {e}", flush=True)
        yield {"kind": "error", "stage": "llm", "error": str(e)}
        return

    logger.info("[%s] LLM reply (%d chars): %r", session_id, len(reply), reply[:80])
    print(f"[orch] LLM OK: {reply[:60]!r}", flush=True)
    yield {"kind": "reply_text", "text": reply, "session_id": session_id}

    try:
        async for chunk in synthesize(reply):
            yield chunk
    except Exception as e:
        logger.exception("[%s] TTS failed", session_id)
        yield {"kind": "error", "stage": "tts", "error": str(e)}
        return

    yield {"kind": "reply_end", "session_id": session_id}