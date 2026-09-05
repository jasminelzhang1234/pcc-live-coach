#!/usr/bin/env python3
"""
双向同步 .github/agents/ (GitHub Copilot) 与 .claude/agents/ (Claude Code)。

单一事实源:.github/agents/*.agent.md(因为它的格式更通用,
且 GitHub Copilot 不接受 .claude/agents/ 这种隐藏目录)。
.claude/agents/*.md 由本脚本生成,只在前者变更后重新生成。

差异点:
- 文件后缀:.github/agents/<name>.agent.md → .claude/agents/<name>.md
- 工具名大小写:['read','glob'] → ['Read','Glob']
  (Claude Code 使用大写工具名;GitHub Copilot 接受小写)

合并策略(默认):
- 以 .github/agents/<name>.agent.md 为基线,执行大小写转换后写入 .claude/agents/<name>.md
- 但 .claude/agents/<name>.md 中**独有的段落**(基线没有的 `#`/`##`/`###` 章节)
  会自动 append 到新文件末尾,避免内部增量(例如"评估后联动 — Tracker 转交"、
  "真人练习管线")被 sync 冲掉。
- 段落识别:用 markdown heading(`^#+ .+`)作为最小合并单位。

用法:
    python scripts/sync_agents.py          # 同步(merge 模式,保留派生独有段落)
    python scripts/sync_agents.py --overwrite  # 完全覆盖(原行为,慎用)
    python scripts/sync_agents.py --check  # 检查派生独有段落是否被保留

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

# 段落切分正则:匹配 markdown heading (`#`/`##`/`###`...),在行首
SECTION_RE = re.compile(r"^(#+ .+)$", re.MULTILINE)


def transform_tools_block(match: re.Match[str]) -> str:
    """'tools: ['read', 'glob']' → 'tools: ['Read', 'Glob']'"""
    prefix = match.group(1)
    inner = match.group(2)
    # 拆分每个 'foo',做大小写映射;未收录的工具保留原样并打印警告
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


def split_into_sections(text: str) -> list[tuple[str, str]]:
    """按 markdown heading 切分段落。

    返回 [(heading, content), ...]:
    - heading 为空字符串时,代表文件开头到第一个 heading 之间的内容(frontmatter / 简介)
    - content 包含 heading 自身 + 到下一个 heading 之间的所有文本
    """
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return [("", text)]
    sections: list[tuple[str, str]] = [("", text[: matches[0].start()])]
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1), text[start:end]))
    return sections


def find_extras_in_derived(
    baseline_text: str, derived_text: str
) -> list[tuple[str, str]]:
    """找出 derived(派生)中独有、baseline(基线)中没有的段落。"""
    baseline_headings = {h for h, _ in split_into_sections(baseline_text)}
    extras: list[tuple[str, str]] = []
    seen: set[str] = set()
    for heading, content in split_into_sections(derived_text):
        if heading and heading not in baseline_headings and heading not in seen:
            extras.append((heading, content))
            seen.add(heading)
    return extras


def merge_preserve_extras(baseline_text: str, derived_text: str) -> str:
    """合并:baseline 全文 + derived 中独有段落 append 到末尾。

    用于 .github/agents/ → .claude/agents/ 的同步,避免 sync 冲掉
    .claude/agents/ 中的内部增量段落。
    """
    extras = find_extras_in_derived(baseline_text, derived_text)
    result = baseline_text.rstrip() + "\n\n"
    for _, content in extras:
        result += content.rstrip() + "\n\n"
    return result.rstrip() + "\n"


def sync_all(overwrite: bool = False) -> list[tuple[Path, Path, int]]:
    """把所有 .github/agents/*.agent.md 同步到 .claude/agents/*.md。

    overwrite=False(默认):merge 模式,保留 .claude/agents/ 中独有段落
    overwrite=True:完全覆盖 .claude/agents/(原行为)

    返回 [(src, dst, preserved_section_count), ...]。
    """
    if not GITHUB_DIR.is_dir():
        print(f"error: 源目录不存在 {GITHUB_DIR}", file=sys.stderr)
        sys.exit(2)

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    results: list[tuple[Path, Path, int]] = []

    for src in sorted(GITHUB_DIR.glob("*.agent.md")):
        # xxx.agent.md → xxx.md
        stem = src.name[: -len(".agent.md")]
        dst = CLAUDE_DIR / f"{stem}.md"
        baseline = github_to_claude(src)
        if overwrite or not dst.exists():
            new_content = baseline
            preserved_count = 0
        else:
            existing = dst.read_text(encoding="utf-8")
            new_content = merge_preserve_extras(baseline, existing)
            preserved_count = len(find_extras_in_derived(baseline, existing))
        dst.write_text(new_content, encoding="utf-8")
        results.append((src, dst, preserved_count))
    return results


def check_drift() -> list[tuple[Path, Path, int]]:
    """检查 .claude/agents/ 是否缺失 .github/agents/ 中的 heading。

    drift 判定标准:dst 文件中缺少 baseline(.github/agents/) 有的某个 heading
    (说明 merge 时丢段落,或被手动覆盖)。

    返回 [(src, dst, missing_section_count), ...]。
    """
    drift: list[tuple[Path, Path, int]] = []
    for src in sorted(GITHUB_DIR.glob("*.agent.md")):
        stem = src.name[: -len(".agent.md")]
        dst = CLAUDE_DIR / f"{stem}.md"
        if not dst.exists():
            drift.append((src, dst, 0))
            continue
        baseline = github_to_claude(src)
        actual = dst.read_text(encoding="utf-8")
        baseline_headings = {h for h, _ in split_into_sections(baseline)}
        actual_headings = {h for h, _ in split_into_sections(actual)}
        missing = baseline_headings - actual_headings
        if missing:
            drift.append((src, dst, len(missing)))
    return drift


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查 .claude/agents/ 是否缺少 .github/agents/ 中的 heading,发现漂移则退出码 1",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="完全覆盖 .claude/agents/(丢弃内部独有段落,慎用)",
    )
    args = parser.parse_args()

    if args.check:
        drift = check_drift()
        if drift:
            print(f"drift: {len(drift)} 个文件缺失基线 heading")
            for src, dst, missing in drift:
                print(f"  - {dst.relative_to(PROJECT_ROOT)} 缺 {missing} 个 heading")
            print("\n请运行: python scripts/sync_agents.py")
            sys.exit(1)
        print("ok: .claude/agents/ 与 .github/agents/ heading 同步")
        return

    pairs = sync_all(overwrite=args.overwrite)
    if not pairs:
        print(f"warn: .github/agents/ 下没有 *.agent.md", file=sys.stderr)
        return
    print(f"synced {len(pairs)} agent(s):")
    for src, dst, preserved in pairs:
        rel_src = src.relative_to(PROJECT_ROOT)
        rel_dst = dst.relative_to(PROJECT_ROOT)
        if args.overwrite:
            print(f"  {rel_src} → {rel_dst}  (overwrite)")
        else:
            print(f"  {rel_src} → {rel_dst}  (merge,保留 {preserved} 个独有段落)")


if __name__ == "__main__":
    main()