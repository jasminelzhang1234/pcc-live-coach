#!/usr/bin/env python3
"""
一次性脚本: 把历史 8 场 DeepSeek 评估补录到 observability/token-usage.csv。

历史是手动流程(复制粘贴到 chat.deepseek.com),没有真实 token 记录。
这里用文件大小估算(中英混合 ~4 字符/token)。

input_tokens = (template + prompt 文件) char count / 4
output_tokens = 估算常数 3000(37 markers + 11 obs + reason + evidence + confidence)

每个 session 写一行:
  agent=pcc-second-judge-deepseek, model=deepseek-v4-flash

去重: csv 里已有该 session_id 的 deepseek 行则跳过(可重跑)。

用法:
  python3 scripts/backfill_deepseek.py
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_CSV = ROOT / "observability" / "token-usage.csv"
TEMPLATE = ROOT / "progress" / "prompts" / "second-judge-deepseek-template.md"
PROMPTS_DIR = ROOT / "progress" / "prompts"

CSV_HEADER = [
    "timestamp", "session_id", "agent",
    "model", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "total_tokens",
    "estimated_cost_usd",
]

# DeepSeek V4 Flash 定价(USD per MTok,无 cache)
DEEPSEEK_PRICING = {"input": 0.27, "output": 1.10}

# 输出 token 估算常数(37 markers + 11 obs + reason + evidence + confidence 的 JSON)
OUTPUT_TOKEN_ESTIMATE = 3000


def existing_session_ids(csv_path: Path, model_filter: str) -> set[str]:
    """返回 csv 里已记录的 (model=model_filter) 的 session_id 集合。"""
    if not csv_path.exists():
        return set()
    ids = set()
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if row.get("model") == model_filter:
                ids.add(row.get("session_id", ""))
    return ids


def find_deepseek_prompts(prompts_dir: Path) -> list[Path]:
    """找出所有 deepseek-v4-flash-vec*.md 文件。"""
    return sorted(prompts_dir.glob("deepseek-v4-flash-vec*.md"))


def extract_session_id_and_date(prompt_path: Path) -> tuple[str, str]:
    """从文件名提取 session_id 和 date。

    文件名格式:
      deepseek-v4-flash-vec01-session01-2026-08-24.md  →  vec01-deepseek-01-2026-08-24
      deepseek-v4-flash-vec02-2026-08-23.md             →  vec02-deepseek-01-2026-08-23 (s01 默认)
      deepseek-v4-flash-vec06-session02-2026-08-23.md   →  vec06-deepseek-02-2026-08-23

    日期 fallback:文件名没日期时,用文件 mtime(ISO 格式)。
    """
    name = prompt_path.stem
    # 优先匹配完整格式: vec + session + date
    m = re.match(r"deepseek-v4-flash-(vec\d+)-session(\d+)-(\d{4}-\d{2}-\d{2})", name)
    if m:
        vec_id = m.group(1)
        sess = m.group(2)
        date_str = m.group(3)
        return f"{vec_id}-deepseek-{sess}-{date_str}", date_str
    # fallback: vec + date(没 session 编号 → 默认 01)
    m = re.match(r"deepseek-v4-flash-(vec\d+)-(\d{4}-\d{2}-\d{2})", name)
    if m:
        vec_id = m.group(1)
        date_str = m.group(2)
        return f"{vec_id}-deepseek-01-{date_str}", date_str
    # 最后 fallback: 用文件 mtime, session_id 用 vec 编号
    m = re.match(r"deepseek-v4-flash-(vec\d+)", name)
    if m:
        vec_id = m.group(1)
        mtime = datetime.fromtimestamp(prompt_path.stat().st_mtime).date()
        date_str = mtime.isoformat()
        return f"{vec_id}-deepseek-01-{date_str}", date_str
    return name, datetime.fromtimestamp(prompt_path.stat().st_mtime).date().isoformat()


def main() -> int:
    if not TEMPLATE.exists():
        print(f"❌ 找不到模板 {TEMPLATE}", file=sys.stderr)
        return 1

    template_chars = len(TEMPLATE.read_text(encoding="utf-8"))
    template_input = template_chars // 4

    prompt_files = find_deepseek_prompts(PROMPTS_DIR)
    if not prompt_files:
        print(f"⚠️ 没找到 deepseek prompt 文件", file=sys.stderr)
        return 0

    already = existing_session_ids(TOKEN_CSV, "deepseek-v4-flash")

    rows_to_write: list[list] = []
    total_cost = 0.0

    print(f"📋 发现 {len(prompt_files)} 个 deepseek prompt 文件")
    print(f"   模板字符: {template_chars} (~{template_input} tokens)")
    print(f"   输出估算: ~{OUTPUT_TOKEN_ESTIMATE} tokens/场")
    print(f"   已记录: {len(already)} 场(将跳过)")
    print()

    for pf in prompt_files:
        session_id, date_str = extract_session_id_and_date(pf)
        if session_id in already:
            print(f"  ⏭ {pf.name}: 已记录")
            continue

        pf_chars = len(pf.read_text(encoding="utf-8"))
        input_tokens = template_input + (pf_chars // 4)
        output_tokens = OUTPUT_TOKEN_ESTIMATE

        cost = round(
            input_tokens / 1e6 * DEEPSEEK_PRICING["input"] +
            output_tokens / 1e6 * DEEPSEEK_PRICING["output"], 6
        )
        total_cost += cost

        row = [
            f"{date_str}T12:00:00+00:00",  # 粗估时间,正午
            session_id,
            "pcc-second-judge-deepseek",
            "deepseek-v4-flash",
            input_tokens,
            output_tokens,
            0, 0,  # 无 cache 数据
            input_tokens + output_tokens,
            cost,
        ]
        rows_to_write.append(row)
        print(f"  ✅ {pf.name}: input={input_tokens}, output={output_tokens}, ${cost:.4f}")

    if not rows_to_write:
        print("\n(没有新数据要写)")
        return 0

    # 写 csv
    is_new = not TOKEN_CSV.exists()
    TOKEN_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(CSV_HEADER)
        writer.writerows(rows_to_write)

    print(f"\n📊 已补录 {len(rows_to_write)} 场,总费用估算 ${total_cost:.4f}")
    print(f"   写入: {TOKEN_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
