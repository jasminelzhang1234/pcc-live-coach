#!/usr/bin/env python3
"""
PreToolUse hook: 防止 PCC 三 agent 越权写到其他 agent 的领域。

每个 agent 只能写自己的归档位置(其余目录视为越权):
- pcc-coachee  → sessions/transcripts/vec-XX-{date}-session-NN.md
- pcc-assessor → practice-logs/{date}-vec-XX-session-NN-*.md
- pcc-tracker  → progress/tracker.csv + progress/tracker-analysis-{date}.md

其他 agent(非 PCC 三件套)或未识别 agent:不做限制,放行。

用法(被 .claude/settings.json 注册为 PreToolUse hook):
    Write|Edit|MultiEdit  →  python3 scripts/hook_guard_writes.py

输入(从 stdin 读 JSON):
{
  "tool_name": "Write",
  "tool_input": {"file_path": "practice-logs/2026-08-24-vec-01-完整评估报告.md", ...},
  "transcript_path": "/path/to/.claude/agents/pcc-coachee.md",
  ...
}

输出(JSON 到 stdout,exit 0):
  允许:无输出
  阻止:{"decision": "block", "reason": "..."}

环境变量:
  CLAUDE_AGENT_NAME  若 harness 设置,直接用此值
  PCC_HOOK_DRY_RUN=1  dry-run 模式:不阻止,只打印警告到 stderr

测试:
    echo '{"tool_name":"Write","tool_input":{"file_path":"tracker.csv"}}' | \\
        CLAUDE_AGENT_NAME=pcc-coachee python3 scripts/hook_guard_writes.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# 每个 PCC agent 允许的写路径正则(相对于工作区根)
AGENT_ALLOWED_PATTERNS: dict[str, list[str]] = {
    "pcc-coachee": [
        r"^sessions/transcripts/vec-\d{2}-\d{4}-\d{2}-\d{2}-session-\d+\.md$",
        r"^sessions/transcripts/voc-\d{2}-\d{4}-\d{2}-\d{2}-session-\d+\.md$",
    ],
    "pcc-assessor": [
        r"^practice-logs/\d{4}-\d{2}-\d{2}-vec-\d{2}-session-\d{2}-.+\.md$",
        r"^practice-logs/\d{4}-\d{2}-\d{2}-voc-\d{2}-session-\d{2}-.+\.md$",
    ],
    "pcc-tracker": [
        r"^progress/tracker\.csv$",
        r"^progress/tracker-analysis-\d{4}-\d{2}-\d{2}\.md$",
    ],
}

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def detect_agent_from_env() -> str:
    """从环境变量推断 agent 名。"""
    return os.environ.get("CLAUDE_AGENT_NAME", "").strip()


def detect_agent_from_transcript(transcript_path: str) -> str:
    """从 transcript_path 推断(备用方案)。"""
    m = re.search(r"/agents/(pcc-[a-z]+)\.md", transcript_path)
    return m.group(1) if m else ""


def detect_agent_from_stdin(data: dict) -> str:
    """从 stdin JSON 的字段推断(备用)。"""
    transcript = data.get("transcript_path", "")
    return detect_agent_from_transcript(transcript)


def is_path_allowed(agent: str, file_path: str) -> tuple[bool, str]:
    """检查 file_path 是否匹配 agent 的允许模式。"""
    if not agent or agent not in AGENT_ALLOWED_PATTERNS:
        return True, ""  # 非 PCC agent,不限

    patterns = AGENT_ALLOWED_PATTERNS[agent]
    fp = file_path.lstrip("/")  # 兼容绝对路径
    # 兼容 ./ 开头
    fp = re.sub(r"^\./", "", fp)

    for pat in patterns:
        if re.match(pat, fp):
            return True, ""

    allowed_str = " | ".join(patterns)
    reason = (
        f"❌ PCC 越权拦截 — Agent '{agent}' 不允许写到 '{file_path}'\n"
        f"   允许的路径模式:\n     - " + "\n     - ".join(patterns) + "\n"
        f"   如果确实是合法操作,请更新 scripts/hook_guard_writes.py 的允许列表。"
    )
    return False, reason


def main() -> int:
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}

    tool_name = data.get("tool_name", "")
    if tool_name not in WRITE_TOOLS:
        return 0  # 非写工具,不检查

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0  # 无路径信息,放行

    # 探测 agent 名(优先级:env > stdin transcript_path)
    agent = detect_agent_from_env() or detect_agent_from_stdin(data)

    allowed, reason = is_path_allowed(agent, file_path)

    if allowed:
        return 0  # 允许

    # Dry-run 模式:不阻止,只打印警告
    if os.environ.get("PCC_HOOK_DRY_RUN") == "1":
        print(f"[DRY-RUN] {reason}", file=sys.stderr)
        return 0

    # 阻止:输出 JSON 到 stdout (PreToolUse 协议)
    block = {"decision": "block", "reason": reason}
    print(json.dumps(block, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())