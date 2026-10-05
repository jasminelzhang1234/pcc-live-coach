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

import asyncio
import logging
from typing import AsyncIterator, Dict, List, Optional, Union

from phase_b.llm.minimax_client import chat
from phase_b.personas.loader import load as load_persona
from phase_b.tts.minimax_tts import synthesize


logger = logging.getLogger(__name__)

TurnEvent = Union[Dict[str, object], bytes]


def _build_system_prompt(persona_id: str, user_difficulty: int = 0,
                          persona: Optional[Dict[str, object]] = None) -> str:
    """Compose a system prompt from persona sections + hard rules.

    Pass `persona=...` to avoid a second disk read when the caller already
    has the persona dict loaded (run_turn does this for Gap 6 model pin).
    """
    p = persona if persona is not None else load_persona(persona_id)
    rules = p.get("hard_rules") or []
    rules_block = "\n".join(f"- {r}" for r in rules) if isinstance(rules, list) else str(rules)
    persona_diff = p.get("difficulty")
    # user_difficulty=0 means UI didn't override; otherwise honor it and surface
    # the mismatch so the LLM knows the user asked for a different level.
    if user_difficulty and user_difficulty != persona_diff:
        difficulty_line = f"难度: {user_difficulty} (用户选择) / persona 推荐: {persona_diff}"
    else:
        difficulty_line = f"难度: {persona_diff}"
    return (
        "你正在扮演一名 ICF 教练陪练对象。\n"
        f"persona_id: {p.get('id')}\n"
        f"{difficulty_line}\n\n"
        "## 不可越界硬约束\n"
        f"{rules_block}\n\n"
        "## 风格\n"
        f"{p.get('sections', {}).get('语言风格', '')}\n\n"
        "## 反应规则\n"
        f"{p.get('sections', {}).get('反应规则表', '')}\n\n"
        "请保持角色。每轮教练说完后,你按 persona 反应表回应(简短,1-3 句)。"
        "请始终使用自然、简体中文回复，不要模仿教练的方言、粤语或错别字，除非 persona 明确要求。"
    )


async def run_turn(
    *,
    session_id: str,
    persona_id: str,
    client_text: str,
    user_difficulty: int = 0,
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
    # Load persona once for both system-prompt building (Gap 6 — model pin)
    # and the system-prompt string assembly.
    _persona = load_persona(persona_id)
    system = _build_system_prompt(persona_id, user_difficulty=user_difficulty, persona=_persona)
    messages: List[Dict[str, str]] = list(history) + [{"role": "user", "content": client_text}]

    # Gap 6 (LLM upgrade drift): honor persona's pinned model if set, falling
    # back to the env LLM_MODEL. The persona author records the model at
    # persona-tuning time; if you upgrade the model, re-validate with anchor
    # sessions and bump `model_pin_date` in the persona frontmatter.
    _persona_model = (str(_persona.get("model") or "")).strip()

    logger.info("[%s] LLM call (persona=%s, text=%r)", session_id, persona_id, client_text[:40])

    # Gap 1: retry primary → fallback model on transient failure.
    # Reads llm_model / llm_fallback_model / llm_retry_max from settings.
    # max_attempts caps total calls across both models (e.g. 2 = 1 primary
    # + 1 fallback). Exponential backoff between attempts.
    from phase_b.config import get_settings
    _s = get_settings()
    _primary = _persona_model or _s.llm_model
    _candidates: List[str] = []
    if _primary:
        _candidates.append(_primary)
    if _s.llm_fallback_model and _s.llm_fallback_model not in _candidates:
        _candidates.append(_s.llm_fallback_model)
    _max_attempts = max(1, min(_s.llm_retry_max, len(_candidates) or 1))

    reply: Optional[str] = None
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    last_err: Optional[BaseException] = None
    last_used_model: Optional[str] = None
    for attempt, model in enumerate(_candidates[:_max_attempts]):
        try:
            # Gap 3: capture token usage from the LLM response. We use
            # return_usage=True to get (text, input_tokens, output_tokens).
            result = await chat(
                messages=messages, system=system, model=model, return_usage=True,
            )
            # chat() with return_usage=True returns (str, int, int).
            text, in_tok, out_tok = result
            reply = text
            last_input_tokens += in_tok
            last_output_tokens += out_tok
            last_used_model = model
            if attempt > 0:
                logger.info("[%s] LLM recovered via fallback model=%s", session_id, model)
            break
        except Exception as e:
            last_err = e
            err_type = type(e).__name__
            logger.warning(
                "[%s] LLM attempt %d (%s) failed: %s",
                session_id, attempt + 1, model, e,
            )
            if attempt + 1 < _max_attempts:
                # Brief backoff before the next attempt.
                await asyncio.sleep(0.5 * (2 ** attempt))
    if reply is None:
        logger.exception("[%s] LLM failed after %d attempt(s)", session_id, _max_attempts)
        print(f"[orch] LLM FAILED ({type(last_err).__name__}): {last_err}", flush=True)
        err_msg = str(last_err) if last_err else "unknown"
        yield {"kind": "error", "stage": "llm", "error": err_msg or (type(last_err).__name__ if last_err else "unknown")}
        return

    # Gap 3: surface token usage to the caller (router forwards to tracker).
    yield {"kind": "token_usage",
           "input_tokens": last_input_tokens,
           "output_tokens": last_output_tokens,
           "model": last_used_model or ""}

    logger.info("[%s] LLM reply (%d chars): %r", session_id, len(reply), reply[:80])
    print(f"[orch] LLM OK: {reply[:60]!r}", flush=True)
    # Some MiniMax models emit a `<think>...</think>` reasoning block before the
    # actual reply. Strip it so it doesn't leak into the transcript and TTS.
    import re as _re
    visible = _re.sub(r"<think>.*?</think>\s*", "", reply, flags=_re.DOTALL).strip()
    if not visible:
        logger.warning("[%s] LLM reply was only reasoning; emitting fallback", session_id)
        visible = "（我在想怎么回应你）"
    yield {"kind": "reply_text", "text": visible, "session_id": session_id}

    try:
        async for chunk in synthesize(visible):
            yield chunk
    except Exception as e:
        logger.exception("[%s] TTS failed", session_id)
        yield {"kind": "error", "stage": "tts", "error": str(e)}
        return

    yield {"kind": "reply_end", "session_id": session_id}