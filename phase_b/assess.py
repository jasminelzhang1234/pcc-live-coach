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
"""PCC 评估 — 同步调用版(参考 .claude/agents/pcc-assessor.md v3)。

设计:
- 不复制 pcc-assessor 的判定规则;而是从 knowledge/ 读 4 个 KB 文件,
  整包塞进 system prompt,让 LLM 用同一份知识底座做判定。
- 评估结果 = 完整 37 marker 三档(✔/△/✘)+ 必命中项 + 结构性降档 + 整体判定。
- 落盘到 assessments/{session_id}.json,前端 dashboard 直接渲染。
- 通过 transport=httpx.MockTransport(...) 可注入假 LLM 响应,便于测试。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import httpx

from phase_b.llm.minimax_client import chat as llm_chat


logger = logging.getLogger(__name__)


# 37 marker ID 列表 — 严格按 pcc-assessor.md § 三档判定 + pcc-markers-2025.md 的顺序
MARKER_IDS: List[str] = [
    # 能力 3 — 建立合约
    "3.1", "3.2", "3.3", "3.4", "3.5", "3.6",
    # 能力 4 — 营造融洽氛围
    "4.1", "4.2", "4.3", "4.4", "4.5", "4.6",
    # 能力 5 — 主动倾听
    "5.1", "5.2", "5.3", "5.4", "5.5",
    # 能力 6 — 提问与反映
    "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7",
    # 能力 7 — 启发觉察
    "7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8",
    # 能力 8 — 设计行动 / 收尾
    "8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "8.9",
]


# pcc-markers-2025.md / competency-rules.md / failure-patterns.md / session-arc.md
_KB_FILES = (
    "pcc-markers-2025.md",
    "competency-rules.md",
    "failure-patterns.md",
    "session-arc.md",
)


# 必命中项(marker ID → 标题)
REQUIRED_MARKERS: Dict[str, str] = {
    "3.1": "确认本次会话想达成什么",
    "3.4": "定义需要处理什么",
    "6.7": "简洁地反映或总结",
    "7.2": "探索超越当前认知(关于'我是谁')",
    "7.3": "探索超越当前认知(关于'这事是什么')",
    "8.5": "设计会后的思考、反思或行动",
    "8.9": "共同决定如何结束会话",
}


def _knowledge_dir() -> Path:
    """Locate the knowledge/ directory (project root).

    phase_b/assess.py → phase_b/ → project root → knowledge/.
    On macOS the 云同步 path contains a literal space ('PCC Live Coach'),
    so resolve() preserves the full path; parents[1] is the project root.
    """
    return Path(__file__).resolve().parents[1] / "knowledge"


def load_kb_text() -> str:
    """Read the 4 PCC knowledge files and concatenate them for the system prompt.

    Missing files are silently skipped — assessment still runs but with
    degraded accuracy (the LLM is told which KB sections were absent).
    """
    base = _knowledge_dir()
    chunks: List[str] = []
    for fname in _KB_FILES:
        path = base / fname
        if not path.is_file():
            logger.warning("KB file missing: %s", path)
            chunks.append(f"\n\n# === {fname} (MISSING) ===\n\n")
            continue
        chunks.append(f"\n\n# === {fname} ===\n\n")
        chunks.append(path.read_text(encoding="utf-8"))
    return "".join(chunks)


def _format_transcript(turns: List[Mapping[str, Any]]) -> str:
    """Render dialogue JSONL turns into the 'coach: ... | client: ...' form
    that pcc-assessor KB examples use."""
    out: List[str] = []
    for t in turns:
        role = t.get("role", "?")
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if role == "coach":
            out.append(f"教练: {text}")
        elif role == "client":
            out.append(f"客户: {text}")
    return "\n".join(out)


_SYSTEM_PROMPT_TEMPLATE = """你是 ICF PCC 表现评估考官。
**你的价值在于严格,不在于让用户感觉良好。**

# 任务

给定一段教练对话逐字稿,逐条对照 37 条 PCC Markers 做判定,输出 JSON。

# 严格铁律(违反任何一条,本次评估作废)

1. **没有可引用的逐字稿原话 → 一律判 ✘**。不得用"教练显然是想……""从上下文看应该是"作为证据。
2. **只认客户听得到的话与可观察行为**。不认教练的意图、心理活动、准备工作。
3. **默认怀疑立场**:先假设不成立,由证据推翻。模糊地带向下取整,绝不向上。
4. **7.2/7.3 的判定要格外保守**:必须同时指出"教练问了什么"与"客户因此产生了什么新东西"。只有前者没有后者一律降为 △。
5. **不得为了鼓励用户而放宽判定**。
6. **不得编造行号或原话**。所有引用必须能在这份逐字稿里找到。

# 三档判定

- **✔**:能引用逐字稿原话,且该原话独立成立,无需善意解读
- **△**:动作出现但不完整(只问不跟进、总结但未确认、有邀请但客户未回应)
- **✘**:无可引用原话

# 必命中项(任一 ✘ 即对应能力整条未达标)

3.1 / 3.4 / 6.7 / (7.2 或 7.3) / 8.5 / 8.9

# 结构性降档规则

- 3.1 未命中 → 5.2、8.1 自动 ✘(链式降档)
- 会话结尾由教练单方面宣布 → 8.9 判 ✘,无解释空间
- 教练字数占比 ≥30% → 7.8 判 ✘;20–30% 判 △
- 分享观察后客户否定,教练再推一次 → 7.5 判 ✘,且 4.4 降至 ✘
- 总结后未给客户确认机会 → 6.7 降至 △
- 6.7 △ → 4.4 降至 ✘(链式降档)
- 8.5 / 8.7 客户自发提 = 至少 △;只有"全场未有任何回应"才 ✘

# 9 条细读反偏松规则(必须应用)

- 8.2:总结里出现"我也有/我自己也/我感觉我也" → ✘(焦点投给自己)
- 7.5:客户否定后教练继续坚持/解释 → ✘(未降权重)
- 8.3:整场未出现"关于这件事/对这件事/你怎么看这件事/站在今天回头看你怎么看"探问 → ✘
- 6.5:总结段 70%+ 是教练视角/自陈 → ✘
- 8.8:客户自发设计行动后,教练未确认/庆祝/鼓励 → ✘
- 3.4:议题 3 次以上跳变未确认 → ✘(议程套娃)
- 5.2:客户反问"你呢?你是怎么做的?"后,教练回答自己经历/转开话题 → ✘
- 6.7:长段总结(>= 3 句)后未给客户确认机会 → △(不升 ✔)
- 6.7 / 8.2 / 8.3:教练先列总结方向,客户做"确认"动作 → ✘(替客户先列,模式 B)

# 知识底座(必读)

{kb}

# 输出格式(严格 JSON,不要任何额外文字)

```json
{{
  "markers": {{
    "3.1": {{"verdict": "✔|△|✘", "evidence": "<逐字稿原话或'未见证据'>", "reason": "<一句话>"}},
    "3.2": {{...}},
    ...
    "8.9": {{...}}
  }},
  "required_check": {{
    "3.1": "✔|△|✘",
    "3.4": "✔|△|✘",
    "6.7": "✔|△|✘",
    "7.2_or_7.3": "✔|△|✘",
    "8.5": "✔|△|✘",
    "8.9": "✔|△|✘"
  }},
  "structural_downgrades": [
    "<触发哪条结构性降档规则 + 哪段原话,例:3.1 未命中 → 5.2/8.1 自动 ✘>"
  ],
  "summary": {{
    "verdict": "达标|边缘|未达标",
    "yes_count": <int>,
    "delta_count": <int>,
    "no_count": <int>,
    "required_missed": <int>,
    "key_weakness": "<一句话,本场最弱能力 / 必命中项,如 '3.4 ✘ 能力 3 整体未达标'>"
  }}
}}
```

37 marker ID 顺序:3.1 3.2 3.3 3.4 3.5 3.6 4.1 4.2 4.3 4.4 4.5 4.6 5.1 5.2 5.3 5.4 5.5 6.1 6.2 6.3 6.4 6.5 6.6 6.7 7.1 7.2 7.3 7.4 7.5 7.6 7.7 7.8 8.1 8.2 8.3 8.4 8.5 8.6 8.7 8.8 8.9
"""


# Greedy match the first {...} block in the assistant response. Some LLM
# wrappers emit the JSON inside ```json ... ``` fences; this regex tolerates
# either bare-JSON or fenced JSON.
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _parse_assessment_response(raw: str) -> Dict[str, Any]:
    """Extract the JSON object from the LLM response.

    Raises ValueError if no JSON block is found or JSON is malformed.
    """
    if not raw or not raw.strip():
        raise ValueError("empty LLM response")
    text = raw.strip()
    # Strip leading ```json fence if present
    fence_open = text.startswith("```")
    if fence_open:
        # Drop first line (```json or ```) and last ```
        lines = text.splitlines()
        # Find first line that's just opening fence
        start = 0
        for i, ln in enumerate(lines):
            if ln.strip().startswith("```"):
                start = i + 1
                break
        # Find last line that's just closing fence
        end = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        raise ValueError(f"no JSON block in LLM response: {raw[:200]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON in LLM response: {e}; head={raw[:200]!r}") from e


def _validate_marker_keys(payload: Dict[str, Any]) -> None:
    """Log a warning if the LLM returned an unexpected marker ID or
    missing required keys. We don't hard-fail — the dashboard tolerates
    partial output and falls back to ✘ for missing markers."""
    markers = payload.get("markers") or {}
    if not isinstance(markers, dict):
        raise ValueError("'markers' missing or not a dict")
    expected = set(MARKER_IDS)
    got = set(markers.keys())
    missing = expected - got
    extra = got - expected
    if missing:
        logger.warning("LLM assessment missing markers: %s", sorted(missing))
    if extra:
        logger.warning("LLM assessment returned unknown markers: %s", sorted(extra))


async def run_assessment(
    turns: List[Mapping[str, Any]],
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Dict[str, Any]:
    """Run the full 37-marker PCC assessment on a transcript.

    Returns the parsed JSON dict with keys:
      - markers: {<id>: {verdict, evidence, reason}}
      - required_check: {<id or '7.2_or_7.3'>: verdict}
      - structural_downgrades: [str]
      - summary: {verdict, yes_count, delta_count, no_count, required_missed, key_weakness}

    `turns` is the list of dialogue rows (each with role/text/ms/etc.).
    Raises ValueError on parse failures (caller decides retry/fallback).
    """
    kb_text = load_kb_text()
    transcript = _format_transcript(list(turns))
    if not transcript.strip():
        raise ValueError("empty transcript; cannot assess")
    system = _SYSTEM_PROMPT_TEMPLATE.format(kb=kb_text)
    user = f"# 对话逐字稿\n\n{transcript}\n\n# 输出\n\n请按 system 提示里的 JSON schema 输出。"
    raw = await llm_chat(
        [{"role": "user", "content": user}],
        system=system,
        transport=transport,
    )
    payload = _parse_assessment_response(raw)
    _validate_marker_keys(payload)
    return payload


def assessment_out_path(session_id: str, base_dir: Optional[Path] = None) -> Path:
    """Where the assessment JSON for a given session should live on disk.

    Defaults to `phase_b/_assessments/<session_id>.json`. Tests can pass
    a custom base_dir to redirect under tmp_path.
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent / "_assessments"
    return base_dir / f"{session_id}.json"


def save_assessment(
    session_id: str,
    payload: Mapping[str, Any],
    base_dir: Optional[Path] = None,
) -> Path:
    """Persist the assessment payload. Returns the written path."""
    out = assessment_out_path(session_id, base_dir=base_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("assessment saved: %s", out)
    return out


def load_assessment(
    session_id: str,
    base_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Load a previously saved assessment, or None if absent."""
    out = assessment_out_path(session_id, base_dir=base_dir)
    if not out.is_file():
        return None
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None