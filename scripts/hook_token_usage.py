#!/usr/bin/env python3
"""
Stop hook: 每次 Claude Code session 结束,把 token 用量 + 估算费用
append 到 progress/token-usage.csv。

注册位置:.claude/settings.json 的 hooks.Stop
触发时机:Claude Code 用户结束,或 agent 任务跑完

输入(stdin JSON,Claude Code Stop 事件):
  {
    "session_id": "uuid",
    "transcript_path": "/path/to/<uuid>.jsonl",
    "cwd": "/path/to/workspace",
    "hook_event_name": "Stop"
  }

输出:
  - stderr 进度信息(✅ session xxx: 50.3K tokens, $0.32)
  - 失败/异常 → stderr,不阻塞,exit 0

去重策略:同一 session_id 已记录过则跳过。

测试:
  echo '{"session_id":"abc","transcript_path":"/path/to/26096f98-034a-4bb8-bc37-ab64a2f0bc0e.jsonl","hook_event_name":"Stop"}' \\
    | python3 scripts/hook_token_usage.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 复用 calc_token_cost.py 的核心函数(同目录)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from calc_token_cost import calc_session_cost  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOKEN_CSV = ROOT / "progress" / "token-usage.csv"
PROJECTS_DIR = Path.home() / ".claude" / "projects"

CSV_HEADER = [
    "timestamp", "session_id", "agent",
    "model", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "total_tokens",
    "estimated_cost_usd",
]


def detect_agent_from_transcript(transcript_path: str) -> str:
    """从 transcript_path 反推 agent 名(复用 hook_guard_writes.py 思路)。

    注意:Stop hook 的 transcript_path 通常指向 session jsonl,而非 agent
    定义文件;真正能拿到 agent 名的路径格式是 PreToolUse/PostToolUse 的
    transcript_path(指向 .claude/agents/pcc-*.md)。Stop hook 这里大概率
    拿不到,因此下面有 fallback:从 jsonl 内容反推。
    """
    m = re.search(r"/agents/(pcc-[a-z]+)\.md", transcript_path)
    return m.group(1) if m else ""


def detect_agent_from_jsonl(jsonl_path: Path) -> str:
    """fallback: 从 jsonl 里 user message 文本匹配 pcc-* agent 关键词。"""
    try:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "user":
                    continue
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    text = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                else:
                    text = str(content)
                m = re.search(r"\bpcc-(coachee|assessor|tracker)\b", text)
                if m:
                    return f"pcc-{m.group(1)}"
    except Exception:
        pass
    return ""


def is_already_recorded(csv_path: Path, session_id: str) -> bool:
    """去重:同 session_id 出现过 → 跳过。"""
    if not csv_path.exists():
        return False
    try:
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("session_id") == session_id:
                    return True
    except Exception:
        pass
    return False


def resolve_jsonl(transcript_path: str | None, session_id: str | None) -> Path | None:
    """优先用 transcript_path(若指向 .jsonl);否则用 session_id 在 projects_dir 下找。"""
    if transcript_path and transcript_path.endswith(".jsonl"):
        p = Path(transcript_path)
        if p.is_file():
            return p
    if session_id:
        for cand in PROJECTS_DIR.rglob(f"{session_id}.jsonl"):
            return cand
    return None


def write_csv_row(csv_path: Path, row: list) -> None:
    """追加一行到 csv。文件不存在则写 header。"""
    is_new = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)


def main() -> int:
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(f"[hook] ⚠️ stdin JSON 解析失败: {e}", file=sys.stderr)
        return 0

    session_id = (data.get("session_id") or "").strip()
    transcript_path = (data.get("transcript_path") or "").strip()

    if not session_id:
        print("[hook] ⚠️ stdin 无 session_id,跳过", file=sys.stderr)
        return 0

    jsonl = resolve_jsonl(transcript_path, session_id)
    if jsonl is None:
        print(f"[hook] ⚠️ 找不到 session {session_id[:8]}... 的 jsonl,跳过",
              file=sys.stderr)
        return 0

    if is_already_recorded(TOKEN_CSV, session_id):
        print(f"[hook] ⏭ session {session_id[:8]}... 已记录,跳过", file=sys.stderr)
        return 0

    try:
        cost = calc_session_cost(jsonl)
    except Exception as e:
        print(f"[hook] ❌ calc_session_cost 失败: {e}", file=sys.stderr)
        return 0

    if not cost["buckets"]:
        print(f"[hook] ⚠️ session {session_id[:8]}... 无 assistant usage,跳过",
              file=sys.stderr)
        return 0

    # agent 名:优先 transcript_path,fallback 到 jsonl 内容
    agent = detect_agent_from_transcript(transcript_path) or \
            detect_agent_from_jsonl(jsonl)

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 按 model 分桶,每个 model 写一行
    for model, b in sorted(cost["buckets"].items()):
        row = [
            ts, session_id, agent,
            model, b["input"], b["output"],
            b["cache_read"], b["cache_write"],
            b["input"] + b["output"] + b["cache_read"] + b["cache_write"],
            b["cost_usd"],
        ]
        write_csv_row(TOKEN_CSV, row)

    total_k = cost["total_tokens"] / 1000
    print(
        f"[hook] ✅ {session_id[:8]}... [{agent or 'unknown'}]: "
        f"{total_k:.1f}K tokens, ${cost['total_cost_usd']:.4f} "
        f"({len(cost['buckets'])} models)",
        file=sys.stderr,
    )

    if cost["unmatched_models"]:
        print(
            f"[hook] ⚠️ 未匹配定价表的 model: {cost['unmatched_models']}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[hook] ❌ uncaught: {e}", file=sys.stderr)
        sys.exit(0)
