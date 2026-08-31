#!/usr/bin/env python3
"""
Generate persona -client.md files from original persona .md files.

B1 模板拆分规则:
- 教练版(原 .md):保留全部 + 加版本标注头(已有则跳过)
- 客户端版(-client.md):删除训练重点/深层议题/解锁条件/训练价值;反应规则表去 marker 标注;情绪触发点改白名单
"""
import re
from pathlib import Path

PERSONAS_DIR = Path(__file__).resolve().parent.parent / "personas"

# Section names to drop in client version (matched by prefix)
SECTIONS_TO_DROP = ["深层议题", "解锁条件", "训练价值"]

# Marker for coach header note (used to detect if already added)
COACH_HEADER_MARK = "pcc-coachee agent 启动时读"

# Marker for client header note
CLIENT_HEADER_MARK = "本文件是 pcc-coachee agent 的工作副本"

# Cues recognized as legitimate non-language signals
KEEP_CUES = [
    "停顿", "较长停顿", "长停顿", "很长的停顿", "沉默",
    "眼睛向下", "眼睛看向窗外", "看了一眼窗外",
    "清了下嗓子", "声音轻下来", "声音低下来", "声音变平",
    "声音会哑一下", "声音会哑", "声音变轻", "声音变小", "声音高起来",
    "语速放慢", "语速变慢", "语速变快",
    "眼眶会红", "眼眶发红",
    "反复说", "反复重复",
    "手指敲桌面", "不自觉搓手", "苦笑一下", "笑了一下", "苦笑",
]


def strip_meta_in_cell(cell: str) -> str:
    """Strip meta annotations from a reaction table cell, preserve quoted dialogue + non-language cues."""
    s = cell
    had_joint_close = "共同决定结束" in cell  # Detect before stripping

    # 1. Strip patterns like （5.3：「你觉得呢?」） or （8.5/8.7） - marker followed by anything
    #    Pattern: （digit.digit [optional multi-marker] [optional rest] ）
    s = re.sub(r"（\s*\d+\.\d+(?:\s*[、/]\s*\d+\.\d+)*[^\）]*）", "", s)

    # 2. Strip （陷阱...）
    s = re.sub(r"（陷阱[^\）]*）", "", s)

    # 3. Strip （深层入口）/（深层议题入口）/（深层松动）/（深层入口打开）/（深层入口...）
    s = re.sub(r"（深层[^\）]*）", "", s)

    # 4. Strip （松动）/（松动一格）/（松动N格）
    s = re.sub(r"（松动[一二三四五六七八九]?格?[^\）]*）", "", s)
    s = re.sub(r"（松动）", "", s)

    # 5. Strip （7.5 命中）/（X.X 命中）
    s = re.sub(r"（\d+\.\d+\s*命中）", "", s)

    # 6. Strip （收尾清楚）/（共同决定结束）
    s = re.sub(r"（收尾清楚）", "", s)

    # 7. Strip （惩罚分支）/（必杀技）
    s = re.sub(r"（惩罚分支）", "", s)
    s = re.sub(r"（必杀技）", "", s)

    # 8. Strip **bold** wrappers
    s = s.replace("**", "")

    # 9. Strip 7.5 命中 style at end of cell (in case not in parens)
    s = re.sub(r"\s*\d+\.\d+\s*命中\s*", " ", s)

    # 10. Strip standalone 共同决定结束 at end of cell (if not already in parens)
    s = re.sub(r"\s*共同决定结束\s*$", "", s)

    # 11. Strip bare annotation words (no parens) at end AND mid-sentence
    # Mid-sentence appearances can have leading spaces, colons, or commas
    bare_annotations = [
        "深层议题入口", "深层入口", "深层松动", "深层入口打开", "深层入口打开中",
        "松动", "松动一格", "松动二格", "松动三格",
        "收尾清楚", "共同决定结束",
    ]
    for ann in bare_annotations:
        # Strip at end of cell
        s = re.sub(rf"\s*{re.escape(ann)}\s*$", "", s)
        # Strip before end punctuation (mid-sentence occurrence before 。！？…」』)
        s = re.sub(rf"\s*{re.escape(ann)}\s*([。！？…」』])", r"\1", s)
        # Strip mid-sentence before opening quote/colon/comma
        s = re.sub(rf'\s*{re.escape(ann)}\s*([：:，「『"])', r'\1', s)

    # 12. If "共同决定结束" was the action label and got fully stripped, replace with meaningful description
    if had_joint_close and not s.strip():
        s = "教练说\"今天到这里\"或类似结束语"

    # 13. Clean up whitespace
    s = re.sub(r"\s+", " ", s).strip()

    # 14. Strip orphan leading punctuation left by mid-sentence annotation strip
    s = re.sub(r"^[：:，,「『“]+", "", s).strip()

    return s


def process_reaction_table(table_text: str) -> str:
    """Process reaction table: strip meta annotations from each cell."""
    lines = table_text.strip().split("\n")
    new_lines = []
    for line in lines:
        if not line.strip().startswith("|"):
            new_lines.append(line)
            continue
        # Split table row by | (excluding outer |)
        # Use split with no limit to handle multi-|
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        new_cells = [strip_meta_in_cell(c) if i in (0, 1) else c for i, c in enumerate(cells)]
        new_line = "| " + " | ".join(new_cells) + " |"
        new_lines.append(new_line)
    return "\n".join(new_lines)


def parse_sections(body: str) -> tuple[str, dict[str, str]]:
    """Split body into (pre_h1_with_h1, sections_dict)."""
    # Find H1
    h1_match = re.search(r"^# .+?\n", body, re.MULTILINE)
    if h1_match:
        pre_h1 = body[:h1_match.end()]
        rest = body[h1_match.end():]
    else:
        pre_h1 = ""
        rest = body

    sections = {}
    current_section = None
    current_lines = []
    for line in rest.split("\n"):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).rstrip()
            current_section = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).rstrip()
    return pre_h1, sections


def section_name_matches(name: str, prefix: str) -> bool:
    """Match section name by prefix (e.g. 深层议题 matches 深层议题 【默认绝不主动说出】)."""
    return name == prefix or name.startswith(prefix + " ") or name.startswith(prefix + "【")


def extract_cues_from_text(text: str) -> list[str]:
    """Extract cues from 情绪触发点 section by removing common filler characters first."""
    # Strip common filler characters to allow partial matching
    normalized = text.replace("会", "").replace("了", "").replace("的", "")
    found = []
    for cue in KEEP_CUES:
        if cue in normalized or cue in text:
            found.append(cue)
    return found


def derive_trigger_paragraph(original_emotional_text: str) -> str:
    """Extract trigger description by removing parenthetical cues and the cues themselves."""
    t = original_emotional_text
    # Strip parenthetical patterns
    t = re.sub(r"[（(][^）)]*[）)]", "", t)
    # Strip the cue words themselves
    cues_sorted = sorted(KEEP_CUES, key=len, reverse=True)
    for cue in cues_sorted:
        t = t.replace(cue, "")
    # Clean up
    t = re.sub(r"[，。,.\s]+", "，", t).strip("，").strip()
    return t


def build_client_white_block(cues: list[str], trigger_text: str) -> str:
    """Build 情绪触发点 section with whitelist structure."""
    cues_md = "\n".join(f"- ({cue})" for cue in cues) if cues else "- (无预设 cue,根据 persona 自定)"

    trigger_para = ""
    if trigger_text.strip():
        trigger_para = (
            f"\n**触发场景**:{trigger_text.strip()}\n\n"
            "从上面白名单里挑一两个写进去。**任何其他 `(...)` 都是违规**,即使你觉得"
            '"这很有用"也不要写(比如 `(完美 8.6)` `(深层入口)` `(建议:...)` 全部禁止)。'
        )

    return f"""**允许使用的非语言信号(白名单)**——下面这些是你**唯一可以**放进 `(...)` 的内容:

{cues_md}
{trigger_para}

**严禁**写以下元描述(写了 = 违规):
- 评价:`(教科书级)` `(这很好)` `(完美)`
- 标记分析:`(8.6 闭环)` `(深层入口)` `(松动)`
- 教练指导:`(the maintainer,...)` `(建议:...)` `(继续)`
- 自我描述:`(我在测试教练)` `(我进入了觉察)`
"""


def generate_client(original_text: str, persona_id: str) -> str:
    """Generate -client.md content from original .md content."""
    # Parse frontmatter
    m = re.match(r"^(---.*?---\n)", original_text, re.DOTALL)
    if not m:
        raise ValueError(f"No frontmatter in {persona_id}")
    frontmatter = m.group(1)
    body = original_text[m.end():]

    # Strip any existing coach header note (from previous script run or manual edit)
    body = re.sub(
        r"\n>\s*📋\s*\*\*教练版\*\*[^\n]*(?:\n>[^\n]*)*\n",
        "\n",
        body,
    )
    body = re.sub(
        r"\n>\s*本文件是 pcc-coachee agent 的工作副本[^\n]*(?:\n>[^\n]*)*\n",
        "\n",
        body,
    )

    # Strip 训练重点 from frontmatter
    new_frontmatter = re.sub(r"^训练重点\s*:.*?\n", "", frontmatter, flags=re.MULTILINE)
    # Add 版本: client (only if not already set)
    if "版本:" not in new_frontmatter and "版本:" not in new_frontmatter:
        new_frontmatter = new_frontmatter.rstrip("\n") + "\n版本: client\n"
    elif re.search(r"版本:\s*coach", new_frontmatter):
        new_frontmatter = re.sub(r"版本:\s*coach", "版本: client", new_frontmatter)

    # Parse sections (preserve H1)
    pre_h1, sections = parse_sections(body)

    # Drop sections not in client version (by prefix)
    sections_to_remove = []
    for sec_name in sections:
        for prefix in SECTIONS_TO_DROP:
            if section_name_matches(sec_name, prefix):
                sections_to_remove.append(sec_name)
                break
    for sec_name in sections_to_remove:
        del sections[sec_name]

    # Process 反应规则表
    if "反应规则表" in sections:
        sections["反应规则表"] = process_reaction_table(sections["反应规则表"])

    # Process 情绪触发点 → whitelist structure
    if "情绪触发点" in sections:
        original = sections["情绪触发点"]
        cues = extract_cues_from_text(original)
        trigger = derive_trigger_paragraph(original)
        sections["情绪触发点"] = build_client_white_block(cues, trigger)

    # Reassemble body
    new_body_parts = [pre_h1.rstrip()]
    for name, content in sections.items():
        new_body_parts.append(f"## {name}\n\n{content}")
    new_body = "\n\n".join(new_body_parts)

    # Inject header note after H1
    first_h = re.search(r"^# .+\n", new_body, re.MULTILINE)
    if first_h and CLIENT_HEADER_MARK not in new_body:
        header_note = (
            "\n> 本文件是 pcc-coachee agent 的工作副本。\n"
            "> 不含：训练重点 / 深层议题 / 解锁条件 / 训练价值 / 反应表中的 marker 标注与陷阱提示。\n"
            f"> 教练复盘请用 [{persona_id}.md]({persona_id}.md)。\n"
        )
        insert_pos = first_h.end()
        new_body = new_body[:insert_pos] + header_note + new_body[insert_pos:]

    return new_frontmatter + "\n" + new_body


def add_coach_header(original_text: str, persona_id: str) -> str:
    """Add a header note to the original (now coach version) file. Skip if already present."""
    m = re.match(r"^(---.*?---\n)", original_text, re.DOTALL)
    if not m:
        return original_text
    frontmatter = m.group(1)
    body = original_text[m.end():]

    # Fix misplaced 版本: coach (after frontmatter) by removing it from body
    body = re.sub(r"^版本:\s*coach\s*\n+", "", body, flags=re.MULTILINE)
    body = re.sub(r"^版本:\s*client\s*\n+", "", body, flags=re.MULTILINE)

    # Add 版本: coach INSIDE frontmatter (before closing ---)
    if "版本:" not in frontmatter:
        # Remove trailing newline and ---, insert 版本 line, then ---
        inner = frontmatter.rstrip("\n").rstrip()
        if inner.endswith("---"):
            inner = inner[:-3].rstrip()
        frontmatter = inner + "\n版本: coach\n---\n"

    # Skip if header note already present
    if COACH_HEADER_MARK in body:
        return frontmatter + body

    # Insert header note after first H1
    first_h = re.search(r"^# .+\n", body, re.MULTILINE)
    if first_h:
        header_note = (
            "\n> 📋 **教练版**(含 PCC markers / 解锁条件 / 训练价值 / 反应表标注)。  \n"
            "> pcc-coachee agent 启动时读 "
            f"[{persona_id}-client.md]({persona_id}-client.md)——那份去掉了 markers 和教学标注,避免污染陪练输入。  \n"
            "> 陪练结束后,教练可打开本文件复盘。\n"
        )
        insert_pos = first_h.end()
        body = body[:insert_pos] + header_note + body[insert_pos:]
    return frontmatter + body


def main():
    persona_files = sorted(PERSONAS_DIR.glob("[vV]*-*.md"))
    # Filter to actual persona files (exclude -client.md, README, _template)
    persona_files = [
        p for p in persona_files
        if not p.name.endswith("-client.md")
        and p.name != "README.md"
        and p.name != "_template.md"
    ]
    print(f"Found {len(persona_files)} persona files")

    for p in persona_files:
        persona_id = p.stem  # e.g. "vec-08"
        client_path = PERSONAS_DIR / f"{persona_id}-client.md"

        # Read original
        original = p.read_text(encoding="utf-8")

        # Generate client version (overwrites if exists)
        client_content = generate_client(original, persona_id)
        client_path.write_text(client_content, encoding="utf-8")
        print(f"[OK] wrote {client_path.name}")

        # Add coach version header to original (idempotent + fixes prior duplicates)
        new_original = add_coach_header(original, persona_id)
        # Dedupe coach header notes in body (in case previous runs left duplicates)
        new_original = dedupe_coach_headers(new_original)
        if new_original != original:
            p.write_text(new_original, encoding="utf-8")
            print(f"[OK] updated header on {p.name}")


def dedupe_coach_headers(text: str) -> str:
    """Remove duplicate coach header notes (only keep first)."""
    pattern = r"(?:>\s*📋\s*\*\*教练版\*\*[^\n]*\n(?:>[^\n]*\n){0,3})"
    matches = list(re.finditer(pattern, text))
    if len(matches) > 1:
        # Keep first, remove rest
        result = text
        for m in reversed(matches[1:]):
            result = result[:m.start()] + result[m.end():]
        return result
    return text


if __name__ == "__main__":
    main()
