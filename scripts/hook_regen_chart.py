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
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKER_REL = "progress/tracker.csv"
REAL_CSV_REL = "progress/tracker-sessions.csv"
ANALYZE_SCRIPT = ROOT / "scripts" / "analyze_tracker.py"
GEN_SCRIPT = ROOT / "scripts" / "gen_trending_chart.py"
GEN_REAL_SCRIPT = ROOT / "scripts" / "gen_trending_chart_real.py"

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

    # 分支:tracker.csv(AI)→ 跑 AI 版;tracker-sessions.csv(真人)→ 跑真人版
    if file_path == TRACKER_REL:
        # AI:analyze_tracker.py(默认 tracker.csv)+ gen_trending_chart.py
        plan = [
            ("analyze_tracker.py", ["python3", str(ANALYZE_SCRIPT)], ROOT / "progress" / f"tracker-analysis-{datetime.now():%Y-%m-%d}.md"),
            ("gen_trending_chart.py", ["python3", str(GEN_SCRIPT)], ROOT / "progress" / "trending-chart.html"),
        ]
        pipeline_label = "AI persona pipeline"
    elif file_path == REAL_CSV_REL:
        # 真人:analyze_tracker.py --csv real --out tracker-analysis-real-{date}.md + gen_trending_chart_real.py
        real_analysis_out = ROOT / "progress" / f"tracker-analysis-real-{datetime.now():%Y-%m-%d}.md"
        plan = [
            (
                "analyze_tracker.py (real)",
                ["python3", str(ANALYZE_SCRIPT), "--csv", str(ROOT / REAL_CSV_REL), "--out", str(real_analysis_out)],
                real_analysis_out,
            ),
            ("gen_trending_chart_real.py", ["python3", str(GEN_REAL_SCRIPT)], ROOT / "progress" / "trending-chart-real.html"),
        ]
        pipeline_label = "real sessions pipeline"
    else:
        return 0  # 不是 AI 也不是真人 csv,跳过

    dry_run = os.environ.get("HOOK_REGEN_DRY_RUN") == "1"

    # 验证源文件存在
    src = ROOT / TRACKER_REL
    if not src.exists():
        print(f"[hook] ⚠️ {TRACKER_REL} 不存在,跳过 regen", file=sys.stderr)
        return 0

    if dry_run:
        print(f"[hook DRY-RUN] {pipeline_label} 会跑:", file=sys.stderr)
        for label, cmd, _ in plan:
            print(f"  {' '.join(cmd)}", file=sys.stderr)
        return 0

    print(f"[hook] {file_path} 已更新,跑 {pipeline_label}...", file=sys.stderr)
    results = []
    for label, cmd, expected_out in plan:
        try:
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                # 确认产物存在(覆盖式文件必然存在,但保险起见)
                produced = expected_out.exists() if expected_out else True
                results.append((label, produced, result.stdout.strip()))
            else:
                results.append((label, False, result.stderr.strip() or result.stdout.strip()))
        except subprocess.TimeoutExpired:
            results.append((label, False, "timeout (>60s)"))
        except Exception as e:
            results.append((label, False, f"exception: {e}"))

    for label, ok, msg in results:
        icon = "✅" if ok else "❌"
        first_line = msg.splitlines()[0] if msg else ""
        print(f"[hook] {icon} {label}: {first_line}", file=sys.stderr)

    # 失败也不阻塞(返回 0);PostToolUse 没有 decision 协议
    return 0


if __name__ == "__main__":
    sys.exit(main())