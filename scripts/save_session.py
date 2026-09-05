#!/usr/bin/env python3
"""
⚠️  已废弃 (deprecated 2026-09-04)

把一份陪练对话 + 评估报告归档到 sessions/,加 frontmatter,
并在 notes/T11-冒烟测试.md 追加一行 L2 记录。

用法:
    python scripts/save_session.py \\
        --transcript /path/to/dialogue.md \\
        --assessment /path/to/report.html \\
        --persona vec-08 \\
        --date 2026-08-22 \\
        --duration "45min" \\
        --assessor "github-copilot(claude-sonnet-4-5)" \\
        --notes "L2 冒烟测试"

可选项:
    --name <stem>      自定义文件名前缀(默认 <persona>-<date>-session-N)
    --dry-run          只打印将做的动作,不真改文件
    --no-frontmatter   不向 transcript 注入 YAML frontmatter
    --no-t11-update    不追加 T11 记录
    --key-findings "..."  摘要这次判定的关键发现(进 frontmatter)

退出码:
    0  成功
    2  输入文件不存在或缺必填参数
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "sessions"
TRANSCRIPTS_DIR = SESSIONS_DIR / "transcripts"
PRACTICE_LOGS_DIR = PROJECT_ROOT / "practice-logs"
# 历史:sessions/assessments/ 在 2026-08-23 之前是 pcc-assessor 报告的默认落点,
# 但已被 practice-logs/ 取代 — practice-logs/ 是权威详细报告的唯一位置。
ASSESSMENTS_DIR = PRACTICE_LOGS_DIR
T11_PATH = PROJECT_ROOT / "notes" / "T11-冒烟测试.md"

# T11 表格的列定义(L2 跑分记录区);新增 row 严格对齐
T11_COLUMNS = ["| 日期 ", " | Persona ", " | 时长 ", " | Assessor ", " | 关键发现 ", " | 归档路径 ", " | 状态 |"]


def next_session_index(persona: str, date: str) -> int:
    """扫一遍 transcripts/,找同名 <persona>-<date>-session-N 的最大 N,返回 N+1。"""
    pat = re.compile(rf"^{re.escape(persona)}-{re.escape(date)}-session-(\d+)\.(md|txt)$")
    max_n = 0
    for f in TRANSCRIPTS_DIR.iterdir():
        m = pat.match(f.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def canonical_name(persona: str, date: str, override: str | None) -> tuple[str, str]:
    """返回 (transcript 文件名 stem, assessment 文件名 stem)。两者同名,扩展名不同。"""
    if override:
        return override, override
    n = next_session_index(persona, date)
    stem = f"{persona}-{date}-session-{n:02d}"
    return stem, stem


FRONTMATTER_TEMPLATE = """---
session_id: {session_id}
date: {date}
persona: {persona}
coach: {coach}
duration: {duration}
assessor_model: {assessor_model}
assessor_version: {assessor_version}
key_findings: {key_findings}
---

"""


def inject_frontmatter(
    transcript: Path,
    dst: Path,
    *,
    session_id: str,
    date: str,
    persona: str,
    coach: str,
    duration: str,
    assessor_model: str,
    assessor_version: str,
    key_findings: str,
) -> None:
    """在 transcript 顶部插入 frontmatter(如果已有则覆盖)。"""
    body = transcript.read_text(encoding="utf-8")
    # 去掉可能已存在的 frontmatter(避免重复堆叠)
    body = re.sub(r"^---\n.*?\n---\n", "", body, count=1, flags=re.DOTALL)
    fm = FRONTMATTER_TEMPLATE.format(
        session_id=session_id,
        date=date,
        persona=persona,
        coach=coach,
        duration=duration,
        assessor_model=assessor_model,
        assessor_version=assessor_version,
        key_findings=key_findings,
    )
    dst.write_text(fm + body, encoding="utf-8")


T11_SECTION_HEADER = "\n## L2 跑分记录(自动维护)\n\n"
T11_TABLE_HEADER = (
    "| 日期 | Persona | 时长 | Assessor | 关键发现 | 归档路径 | 状态 |\n"
    "|---|---|---|---|---|---|---|\n"
)


def append_t11_row(
    *,
    date: str,
    persona: str,
    duration: str,
    assessor: str,
    key_findings: str,
    archive_path: str,
) -> None:
    """在 T11 末尾的 'L2 跑分记录' 表格里追加一行。无该 section 则创建。"""
    text = T11_PATH.read_text(encoding="utf-8")
    row = f"| {date} | {persona} | {duration} | {assessor} | {key_findings} | {archive_path} | ✅ |\n"

    if T11_SECTION_HEADER.strip() not in text:
        # 追加整段
        if not text.endswith("\n"):
            text += "\n"
        text += T11_SECTION_HEADER + T11_TABLE_HEADER + row
        T11_PATH.write_text(text, encoding="utf-8")
        return

    # 找到表格头位置,在最后一行表格后追加
    header_pos = text.index(T11_SECTION_HEADER.strip())
    after_header = text.index(T11_TABLE_HEADER, header_pos) + len(T11_TABLE_HEADER)
    # 找下一个非表格行(空行 / ## / --- / 普通段落)前的位置
    tail = text[after_header:]
    lines = tail.split("\n")
    insert_at_line = 0
    for i, line in enumerate(lines):
        if line.startswith("|") and line.count("|") >= 6:
            insert_at_line = i + 1
        else:
            break
    lines.insert(insert_at_line, row.rstrip("\n"))
    new_text = text[:after_header] + "\n".join(lines)
    T11_PATH.write_text(new_text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--transcript", required=True, type=Path, help="源对话逐字稿")
    p.add_argument("--assessment", required=True, type=Path, help="源评估报告(HTML/MD)")
    p.add_argument("--persona", required=True, help="如 vec-08")
    p.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD(默认今天)")
    p.add_argument("--coach", default="教练本人", help="教练名")
    p.add_argument("--duration", default="45min", help="会话时长")
    p.add_argument("--assessor", default="未指定", help="assessor 标识,如 'github-copilot' / 'claude-code'")
    p.add_argument("--assessor-version", default="未指定", help="commit hash 或版本")
    p.add_argument("--key-findings", default="", help="关键发现摘要")
    p.add_argument("--name", help="自定义文件 stem(默认 <persona>-<date>-session-NN)")
    p.add_argument("--notes", default="", help="附加备注(仅打印,不写入)")
    p.add_argument("--no-frontmatter", action="store_true")
    p.add_argument("--no-t11-update", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.transcript.exists():
        print(f"error: transcript 不存在: {args.transcript}", file=sys.stderr)
        sys.exit(2)
    if not args.assessment.exists():
        print(f"error: assessment 不存在: {args.assessment}", file=sys.stderr)
        sys.exit(2)

    stem_t, stem_a = canonical_name(args.persona, args.date, args.name)
    transcript_ext = args.transcript.suffix or ".md"
    assessment_ext = args.assessment.suffix or ".html"
    dst_transcript = TRANSCRIPTS_DIR / f"{stem_t}{transcript_ext}"
    dst_assessment = ASSESSMENTS_DIR / f"{stem_a}{assessment_ext}"

    print(f"=== save_session {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"transcript: {args.transcript}")
    print(f"  → {dst_transcript.relative_to(PROJECT_ROOT)}")
    print(f"assessment: {args.assessment}")
    print(f"  → {dst_assessment.relative_to(PROJECT_ROOT)}")
    if args.notes:
        print(f"notes: {args.notes}")

    if args.dry_run:
        return

    # 1. 复制(永不删除源)
    shutil.copy2(args.transcript, dst_transcript)
    shutil.copy2(args.assessment, dst_assessment)

    # 2. 注入 frontmatter
    if not args.no_frontmatter:
        inject_frontmatter(
            args.transcript,
            dst_transcript,
            session_id=stem_t,
            date=args.date,
            persona=args.persona,
            coach=args.coach,
            duration=args.duration,
            assessor_model=args.assessor,
            assessor_version=args.assessor_version,
            key_findings=args.key_findings,
        )

    # 3. 更新 T11
    if not args.no_t11_update:
        archive_path = (
            f"[transcripts/{dst_transcript.name}](../sessions/transcripts/{dst_transcript.name}) · "
            f"[practice-logs/{dst_assessment.name}](../practice-logs/{dst_assessment.name})"
        )
        append_t11_row(
            date=args.date,
            persona=args.persona,
            duration=args.duration,
            assessor=args.assessor,
            key_findings=args.key_findings or "—",
            archive_path=archive_path,
        )

    print("\n✅ 完成。下一步:把这次的关键发现写到 progress/校准记录-<persona>-<date>.md")


if __name__ == "__main__":
    main()
