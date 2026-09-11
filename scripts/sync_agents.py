#!/usr/bin/env python3
"""
单向同步 .claude/agents/ (Claude Code) → .github/agents/ (GitHub Copilot)。

单一事实源:.claude/agents/*.md(Claude Code 工作流的源,v4 起确立)。
.github/agents/*.agent.md 是生成的副本,任何修改必须先改 .claude/agents/ 再跑本脚本。

差异:
- 文件后缀:.claude/agents/<name>.md → .github/agents/<name>.agent.md
- 工具名大小写:`['Read','Glob']` → `['read','glob']`
  (Claude Code 使用 PascalCase 工具名;GitHub Copilot 用 lowercase)

默认行为:每次 sync 完整覆盖 .github/agents/(不允许在 .github/agents/ 改后再 sync,
否则会被冲掉——这是 source-of-truth 约束)。

用法:
    python3 scripts/sync_agents.py          # 同步(.github/agents/ 被覆盖)
    python3 scripts/sync_agents.py --check  # 检查 .github/agents/ 是否已同步

退出码:
    0  同步成功 / 无漂移
    1  --check 模式下检测到漂移
    2  缺源文件 / 解析失败

历史:
    2026-08-22: 初版,方向为 .github → .claude(当时 .github/agents/ 是 source)
    2026-09-11: 方向翻转为 .claude → .github(因 v4 隐私脱敏工作流在 .claude 完成,
              且 .github/agents/ 的 v3 旧版含未脱敏真人案例锚点)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 项目根 = 本脚本所在目录的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_DIR = PROJECT_ROOT / ".claude" / "agents"  # 源
GITHUB_DIR = PROJECT_ROOT / ".github" / "agents"  # 镜像

# 已知 Claude Code 工具名的大小写映射(扩展时在此追加)
# Claude Code 用 PascalCase,GitHub Copilot 用 lowercase — 此映射做转换
TOOL_CASE_MAP = {
    "Read": "read",
    "Glob": "glob",
    "Grep": "grep",
    "Bash": "bash",
    "Write": "write",
    "Edit": "edit",
    "WebFetch": "webfetch",
    "WebSearch": "websearch",
    "NotebookEdit": "notebookedit",
}

# 匹配 tools: 后的引号列表,逐个替换大小写
TOOLS_RE = re.compile(r"(tools:\s*)\[([^\]]+)\]")


def transform_tools_block(match: re.Match[str]) -> str:
    """'tools: ['Read', 'Glob']' → 'tools: ['read', 'glob']'"""
    prefix = match.group(1)
    inner = match.group(2)
    items: list[str] = []
    for raw in re.findall(r"'([^']+)'|\"([^\"]+)\"", inner):
        name = raw[0] or raw[1]
        canonical = TOOL_CASE_MAP.get(name)
        if canonical is None:
            print(
                f"  warn: 未知工具 '{name}',按原样写入。"
                f"如需大小写映射,请在 TOOL_CASE_MAP 中追加。",
                file=sys.stderr,
            )
            items.append(f"'{name}'")
        elif canonical != name:
            items.append(f"'{canonical}'")
        else:
            items.append(f"'{name}'")
    return f"{prefix}[{', '.join(items)}]"


def claude_to_github(source: Path) -> str:
    """读取 .claude/agents/<name>.md,生成 GitHub Copilot 版本正文。"""
    text = source.read_text(encoding="utf-8")
    return TOOLS_RE.sub(transform_tools_block, text)


def sync_all() -> list[tuple[Path, Path]]:
    """把所有 .claude/agents/*.md 完整覆盖到 .github/agents/*.agent.md。"""
    if not CLAUDE_DIR.is_dir():
        print(f"error: 源目录不存在 {CLAUDE_DIR}", file=sys.stderr)
        sys.exit(2)

    GITHUB_DIR.mkdir(parents=True, exist_ok=True)
    results: list[tuple[Path, Path]] = []

    for src in sorted(CLAUDE_DIR.glob("*.md")):
        # xxx.md → xxx.agent.md
        stem = src.name[: -len(".md")]
        dst = GITHUB_DIR / f"{stem}.agent.md"
        dst.write_text(claude_to_github(src), encoding="utf-8")
        results.append((src, dst))
    return results


def check_drift() -> list[tuple[Path, Path]]:
    """检查 .github/agents/ 是否与 .claude/agents/ 一致;不一致的文件对返回。"""
    drift: list[tuple[Path, Path]] = []
    for src in sorted(CLAUDE_DIR.glob("*.md")):
        stem = src.name[: -len(".md")]
        dst = GITHUB_DIR / f"{stem}.agent.md"
        if not dst.exists():
            drift.append((src, dst))
            continue
        expected = claude_to_github(src)
        actual = dst.read_text(encoding="utf-8")
        if actual != expected:
            drift.append((src, dst))
    return drift


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查 .github/agents/ 是否与 .claude/agents/ 一致,发现漂移则退出码 1",
    )
    args = parser.parse_args()

    if args.check:
        drift = check_drift()
        if drift:
            print(f"drift: {len(drift)} 个文件不一致")
            for src, dst in drift:
                print(f"  - {src.relative_to(PROJECT_ROOT)} ↔ {dst.relative_to(PROJECT_ROOT)}")
            print("\n请运行: python3 scripts/sync_agents.py")
            sys.exit(1)
        print("ok: .claude/agents/ 与 .github/agents/ 同步")
        return

    pairs = sync_all()
    if not pairs:
        print(f"warn: .claude/agents/ 下没有 *.md", file=sys.stderr)
        return
    print(f"synced {len(pairs)} agent(s):")
    for src, dst in pairs:
        print(f"  {src.relative_to(PROJECT_ROOT)} → {dst.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
