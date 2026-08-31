#!/usr/bin/env python3
"""add_conversation_time_column.py — 给 tracker.csv 加第 3 列。

依据 2026-08-25 决定:
  - conversation_time: 对话实际发生时间(HH:MM 格式,24h)
  - 缺失/未知则留空

插入位置: `conversation_date` 列之后(语义相邻,3 列成组)。

时间来源:transcript 文件 mtime(精确到分钟);无 transcript 的行估空。

列数变化:90 → 91
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "progress" / "tracker.csv"

# 时间映射(HH:MM 格式)
# 数据来源:
#   - 大多数:transcript 文件 mtime
#   - vec-08-2026-08-22-02:session_id=08-22 但 transcript mtime=08-23 08:41(次日补写);
#     eval file mtime=08-22 22:27 → 推断对话在 08-22 傍晚 ≈ 21:00
#   - vec-08-2026-08-24-01:是 vec-08-2026-08-22-01 的重评估,
#     conversation_time 填原始对话时间 10:17(不是 08-24 重评时间 11:30)
TIMES: dict[str, str] = {
    "vec-08-2026-08-24-01": "10:17",  # reeval of vec-08 s01 (对话实际 08-22 10:17)
    "vec-06-2026-08-22-01": "15:55",
    "vec-08-2026-08-22-02": "21:00",  # 估(eval 22:27 同日)
    "vec-07-2026-08-23-01": "10:55",
    "vec-02-2026-08-23-01": "15:01",
    "vec-06-2026-08-23-02": "19:12",
    "vec-07-2026-08-23-02": "20:45",
    "vec-01-2026-08-24-01": "16:05",
    "vec-02-2026-08-25-01": "15:06",
}


def main() -> int:
    with CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header = rows[0]
    data = rows[1:]

    # 幂等检查
    if "conversation_time" in header:
        print("ERROR: conversation_time 列已存在,无需添加(脚本幂等保护)")
        return 1

    # 校验原 schema
    expected = 90
    if len(header) != expected:
        print(f"ERROR: 原 header 应为 {expected} 列,实际 {len(header)}", file=sys.stderr)
        return 1
    for r in data:
        if len(r) != expected:
            print(f"ERROR: 数据行 {r[0]} 列数 {len(r)} ≠ {expected}", file=sys.stderr)
            return 1

    # 找到 conversation_date 列位置,在其后插入 conversation_time
    cd_idx = header.index("conversation_date")
    new_header = (
        header[: cd_idx + 1]
        + ["conversation_time"]
        + header[cd_idx + 1 :]
    )

    new_data = []
    for row in data:
        sid = row[0]
        t = TIMES.get(sid, "")
        new_row = row[: cd_idx + 1] + [t] + row[cd_idx + 1 :]
        new_data.append(new_row)

    # 校验
    assert len(new_header) == expected + 1, f"新 header 应为 {expected+1} 列,实际 {len(new_header)}"
    for r in new_data:
        assert len(r) == expected + 1, f"行 {r[0]} 新列数应为 {expected+1},实际 {len(r)}"

    # 校验 9 行都填了时间(防止遗漏)
    missing = [r[0] for r in new_data if not r[cd_idx + 1]]
    if missing:
        print(f"WARNING: 以下行 conversation_time 未填(将留空):{missing}", file=sys.stderr)

    # 写回(LF 换行;csv writer 默认即 LF)
    with CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(new_header)
        writer.writerows(new_data)

    print(f"✅ 已添加 conversation_time 列")
    print(f"   原列数: {expected} → 新列数: {expected + 1}")
    print(f"   数据行数: {len(new_data)}")
    print(f"   时间映射(共 {len(TIMES)} 条):")
    for sid, t in TIMES.items():
        print(f"     {sid:32s} → {t}")
    print(f"\n  ⚠️ 若需要回滚,运行:")
    print(f"     git checkout progress/tracker.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())