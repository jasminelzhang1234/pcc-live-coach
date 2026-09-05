#!/usr/bin/env python3
"""
单向同步 .github/agents/ (GitHub Copilot) → .claude/agents/ (Claude Code)。

单一事实源:.github/agents/*.agent.md(因为它的格式更通用,
且 GitHub Copilot 不接受 .claude/agents/ 这种隐藏目录)。
.claude/agents/*.md 是生成的副本,任何修改必须先改 .github/agents/ 再跑本脚本。

差异:
- 文件后缀:.github/agents/<name>.agent.md → .claude/agents/<name>.md
- 工具名大小写:`['read','glob']` → `['Read','Glob']`
  (Claude Code 使用大写工具名;GitHub Copilot 用小写)

默认行为:每次 sync 完整覆盖 .claude/agents/(不允许在 .claude/agents/ 改后再 sync,
否则会被冲掉——这是 source-of-truth 约束)。

用法:
    python scripts/sync_agents.py          # 同步(.claude/agents/ 被覆盖)
    python scripts/sync_agents.py --check  # 检查 .claude/agents/ 是否已同步

退出码:
    0  同步成功 / 无漂移
    1  --check 模式下检测到漂移
    2  缺源文件 / 解析失败
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 项目根 = 本脚本所在目录的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GITHUB_DIR = PROJECT_ROOT / ".github" / "agents"
CLAUDE_DIR = PROJECT_ROOT / ".claude" / "agents"

# 已知 Claude Code 工具名的大小写映射(扩展时在此追加)
TOOL_CASE_MAP = {
    "read": "Read",
    "glob": "Glob",
    "grep": "Grep",
    "bash": "Bash",
    "write": "Write",
    "edit": "Edit",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
    "notebookedit": "NotebookEdit",
}

# 匹配 tools: 后的引号列表,逐个替换大小写
TOOLS_RE = re.compile(r"(tools:\s*)\[([^\]]+)\]")


def transform_tools_block(match: re.Match[str]) -> str:
    """'tools: ['read', 'glob']' → 'tools: ['Read', 'Glob']'"""
    prefix = match.group(1)
    inner = match.group(2)
    items: list[str] = []
    for raw in re.findall(r"'([^']+)'|\"([^\"]+)\"", inner):
        name = raw[0] or raw[1]
        canonical = TOOL_CASE_MAP.get(name.lower())
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


def github_to_claude(source: Path) -> str:
    """读取 .github/agents/<name>.agent.md,生成 Claude Code 版本正文。"""
    text = source.read_text(encoding="utf-8")
    return TOOLS_RE.sub(transform_tools_block, text)


def sync_all() -> list[tuple[Path, Path]]:
    """把所有 .github/agents/*.agent.md 完整覆盖到 .claude/agents/*.md。"""
    if not GITHUB_DIR.is_dir():
        print(f"error: 源目录不存在 {GITHUB_DIR}", file=sys.stderr)
        sys.exit(2)

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    results: list[tuple[Path, Path]] = []

    for src in sorted(GITHUB_DIR.glob("*.agent.md")):
        # xxx.agent.md → xxx.md
        stem = src.name[: -len(".agent.md")]
        dst = CLAUDE_DIR / f"{stem}.md"
        dst.write_text(github_to_claude(src), encoding="utf-8")
        results.append((src, dst))
    return results


def check_drift() -> list[tuple[Path, Path]]:
    """检查 .claude/agents/ 是否与 .github/agents/ 一致;不一致的文件对返回。"""
    drift: list[tuple[Path, Path]] = []
    for src in sorted(GITHUB_DIR.glob("*.agent.md")):
        stem = src.name[: -len(".agent.md")]
        dst = CLAUDE_DIR / f"{stem}.md"
        if not dst.exists():
            drift.append((src, dst))
            continue
        expected = github_to_claude(src)
        actual = dst.read_text(encoding="utf-8")
        if actual != expected:
            drift.append((src, dst))
    return drift


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查 .claude/agents/ 是否与 .github/agents/ 一致,发现漂移则退出码 1",
    )
    args = parser.parse_args()

    if args.check:
        drift = check_drift()
        if drift:
            print(f"drift: {len(drift)} 个文件不一致")
            for src, dst in drift:
                print(f"  - {src.relative_to(PROJECT_ROOT)} ↔ {dst.relative_to(PROJECT_ROOT)}")
            print("\n请运行: python scripts/sync_agents.py")
            sys.exit(1)
        print("ok: .claude/agents/ 与 .github/agents/ 同步")
        return

    pairs = sync_all()
    if not pairs:
        print(f"warn: .github/agents/ 下没有 *.agent.md", file=sys.stderr)
        return
    print(f"synced {len(pairs)} agent(s):")
    for src, dst in pairs:
        print(f"  {src.relative_to(PROJECT_ROOT)} → {dst.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
