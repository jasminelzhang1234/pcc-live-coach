#!/usr/bin/env python3
"""add_conversation_date_column.py — 给 tracker.csv 加 2 列。

依据 2026-08-25 决定:
  - conversation_date: 对话实际发生日期(transcript mtime 推断)
  - reeval_of: 该行是不是另一场的"重评估"(填原 session_id,否则空)

插入位置: `date` 列之后(语义相邻)。

默认覆盖映射:
  - vec-08-2026-08-24-01 → conversation_date=2026-08-22, reeval_of=vec-08-2026-08-22-01
    (同次对话用新细读规则重评,被删的旧版 session_id 仍保留引用)
  - 其他行:conversation_date=date, reeval_of=""

列数变化:88 → 90
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "progress" / "tracker.csv"

# 手动覆盖(目前只有 vec-08-2026-08-24-01 是重评估)
OVERRIDES: dict[str, dict[str, str]] = {
    "vec-08-2026-08-24-01": {
        "conversation_date": "2026-08-22",
        "reeval_of": "vec-08-2026-08-22-01",
    },
}


def main() -> int:
    with CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header = rows[0]
    data = rows[1:]

    # 幂等检查
    if "conversation_date" in header or "reeval_of" in header:
        print("ERROR: conversation_date / reeval_of 已存在,无需添加(脚本幂等保护)")
        return 1

    # 校验原 schema
    expected = 88
    if len(header) != expected:
        print(f"ERROR: 原 header 应为 {expected} 列,实际 {len(header)}", file=sys.stderr)
        return 1
    for r in data:
        if len(r) != expected:
            print(f"ERROR: 数据行 {r[0]} 列数 {len(r)} ≠ {expected}", file=sys.stderr)
            return 1

    # 找到 date 列的位置,在其后插入 2 列
    date_idx = header.index("date")
    new_header = (
        header[: date_idx + 1]
        + ["conversation_date", "reeval_of"]
        + header[date_idx + 1 :]
    )

    new_data = []
    for row in data:
        sid = row[0]
        date_val = row[date_idx]
        if sid in OVERRIDES:
            cd = OVERRIDES[sid]["conversation_date"]
            ro = OVERRIDES[sid]["reeval_of"]
        else:
            cd = date_val
            ro = ""
        new_row = row[: date_idx + 1] + [cd, ro] + row[date_idx + 1 :]
        new_data.append(new_row)

    # 校验
    assert len(new_header) == expected + 2, f"新 header 应为 {expected+2} 列,实际 {len(new_header)}"
    for r in new_data:
        assert len(r) == expected + 2, f"行 {r[0]} 新列数应为 {expected+2},实际 {len(r)}"

    # 写回(LF 换行;csv writer 默认即 LF)
    with CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(new_header)
        writer.writerows(new_data)

    print(f"✅ 已添加 conversation_date + reeval_of 两列")
    print(f"   原列数: {expected} → 新列数: {expected + 2}")
    print(f"   数据行数: {len(new_data)}")
    print(f"   覆盖映射: {OVERRIDES}")
    print(f"\n  ⚠️ 若需要回滚,运行:")
    print(f"     git checkout progress/tracker.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())