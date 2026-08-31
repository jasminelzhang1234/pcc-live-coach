#!/usr/bin/env python3
"""
PostToolUse hook: tracker.csv 写入后,自动重生成 trending chart + tracker-analysis。

触发条件:
  - tool_name ∈ {Write, Edit, MultiEdit}
  - tool_input.file_path 命中 progress/tracker.csv(相对/绝对路径都支持)

行为:
  - 跑 scripts/analyze_tracker.py → progress/tracker-analysis-{date}.md
  - 跑 scripts/gen_trending_chart.py → progress/trending-chart-{date}.html
  - 都成功 → stderr 输出 ✅
  - 任一失败 → stderr 输出 ⚠️(不阻塞后续操作,hook exit 0)

用法(被 .claude/settings.json 注册为 PostToolUse hook):
    Write|Edit|MultiEdit  →  python3 scripts/hook_regen_chart.py

环境变量:
    HOOK_REGEN_DRY_RUN=1   dry-run 模式:不跑脚本,只打印要做什么

测试:
    echo '{"tool_name":"Write","tool_input":{"file_path":"progress/tracker.csv"}}' \\
        | python3 scripts/hook_regen_chart.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKER_REL = "progress/tracker.csv"
ANALYZE_SCRIPT = ROOT / "scripts" / "analyze_tracker.py"
GEN_SCRIPT = ROOT / "scripts" / "gen_trending_chart.py"

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def normalize_path(p: str) -> str:
    """绝对路径 → 相对工作区的路径。失败返回原值。"""
    if not p:
        return ""
    if not p.startswith("/"):
        return p
    try:
        return str(Path(p).resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return p


def main() -> int:
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}

    tool_name = data.get("tool_name", "")
    if tool_name not in WRITE_TOOLS:
        return 0  # 非写工具,跳过

    file_path_raw = data.get("tool_input", {}).get("file_path", "")
    file_path = normalize_path(file_path_raw)
    if file_path != TRACKER_REL:
        return 0  # 不是 tracker.csv,跳过

    dry_run = os.environ.get("HOOK_REGEN_DRY_RUN") == "1"

    # 验证源文件存在
    src = ROOT / TRACKER_REL
    if not src.exists():
        print(f"[hook] ⚠️ {TRACKER_REL} 不存在,跳过 regen", file=sys.stderr)
        return 0

    if dry_run:
        print(f"[hook DRY-RUN] 会跑:", file=sys.stderr)
        print(f"  python3 scripts/analyze_tracker.py", file=sys.stderr)
        print(f"  python3 scripts/gen_trending_chart.py", file=sys.stderr)
        return 0

    # 跑 analyze_tracker.py
    print(f"[hook] tracker.csv 已更新,开始重生成...", file=sys.stderr)
    results = []
    for label, script in [("analyze_tracker.py", ANALYZE_SCRIPT), ("gen_trending_chart.py", GEN_SCRIPT)]:
        try:
            result = subprocess.run(
                ["python3", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                results.append((label, True, result.stdout.strip()))
            else:
                results.append((label, False, result.stderr.strip() or result.stdout.strip()))
        except subprocess.TimeoutExpired:
            results.append((label, False, "timeout (>60s)"))
        except Exception as e:
            results.append((label, False, f"exception: {e}"))

    # 输出汇总
    for label, ok, msg in results:
        icon = "✅" if ok else "❌"
        first_line = msg.splitlines()[0] if msg else ""
        print(f"[hook] {icon} {label}: {first_line}", file=sys.stderr)

    # 失败也不阻塞(返回 0);PostToolUse 没有 decision 协议
    return 0


if __name__ == "__main__":
    sys.exit(main())