#!/usr/bin/env python3
"""Remove vec-08-2026-08-22-01 from tracker.csv (同对话双评估的去重)。

依据 2026-08-25 决定:vec-08 s01 的两次评估保留新细读规则版本
(vec-08-2026-08-24-01),删除旧版(vec-08-2026-08-22-01)。
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "progress" / "tracker.csv"
TARGET = "vec-08-2026-08-22-01"

def main() -> int:
    with CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header = rows[0]
    data = rows[1:]

    before = len(data)
    filtered = [r for r in data if r[0] != TARGET]
    after = len(filtered)
    removed = before - after

    if removed == 0:
        print(f"未找到 {TARGET};无需改动")
        return 0

    # 校验列数一致
    cols = set(len(r) for r in filtered)
    cols.add(len(header))
    if len(cols) > 1:
        print(f"ERROR: 列数不一致 {cols}", file=sys.stderr)
        return 1

    # 写回(保持 LF 换行;csv writer 默认 LF)
    with CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerows([header] + filtered)

    print(f"✅ 已删除 {TARGET}")
    print(f"   删除前行数: {before}")
    print(f"   删除后行数: {after}")
    print(f"   减少: {removed}")
    return 0

if __name__ == "__main__":
    sys.exit(main())