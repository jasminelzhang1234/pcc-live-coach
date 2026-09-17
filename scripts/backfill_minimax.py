#!/usr/bin/env python3
"""
一次性脚本: 把历史所有 Claude Code session jsonl 补录到 observability/token-usage.csv。

场景:Stop hook 是新装的,历史 session 都没自动入账。
     此脚本遍历 ~/.claude/projects/<workspace-hash>/*.jsonl,按 hook 同等逻辑
     算 cost + 写 csv。

行为:
  - 已记录的 session_id 跳过(可重跑)
  - agent 字段从 transcript_path 或 jsonl 内容反推(同 hook 逻辑)
  - 模型按 message.model 字段统计,默认 MiniMax-M3
  - 写在 observability/token-usage.csv

用法:
  python3 scripts/backfill_minimax.py
  python3 scripts/backfill_minimax.py --dry-run   # 只打印不入账
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_CSV = ROOT / "observability" / "token-usage.csv"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
WORKSPACE_HASH_DIR = next(
    (p for p in PROJECTS_DIR.iterdir() if "PCC-Live-Coach" in p.name),
    PROJECTS_DIR,  # fallback
)

# 复用 calc_token_cost.py + hook_token_usage.py 逻辑
sys.path.insert(0, str(Path(__file__).resolve().parent))
from calc_token_cost import calc_session_cost  # noqa: E402
from hook_token_usage import (  # noqa: E402
    detect_agent_from_jsonl, is_already_recorded, write_csv_row, CSV_HEADER,
)


def existing_minimax_session_ids(csv_path: Path) -> set[str]:
    """返回 csv 里 MiniMax-M3 / 任意 model 的 session_id 集合(本脚本只关心 MiniMax)。"""
    if not csv_path.exists():
        return set()
    ids = set()
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            # 任何 model 都算(避免重复回填 hook 写的 unknown 行)
            if row.get("model"):
                ids.add(row.get("session_id", ""))
    return ids


def find_session_jsonls(projects_dir: Path) -> list[Path]:
    """找所有 session jsonl。优先匹配 workspace-hash 目录,fallback 到所有。"""
    target = WORKSPACE_HASH_DIR if WORKSPACE_HASH_DIR.exists() else projects_dir
    return sorted(target.glob("*.jsonl"))


def extract_first_user_timestamp(jsonl_path: Path) -> str:
    """从 jsonl 里读第一条 user message 的 timestamp,作为 session 时间戳。"""
    try:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "user":
                    ts = d.get("timestamp", "")
                    return ts
    except Exception:
        pass
    # fallback: 文件 mtime
    mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime)
    return mtime.isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印要补录的 session,不实际写入")
    args = parser.parse_args()

    jsonls = find_session_jsonls(PROJECTS_DIR)
    if not jsonls:
        print(f"❌ 没找到 session jsonl(在 {WORKSPACE_HASH_DIR})", file=sys.stderr)
        return 1

    already = existing_minimax_session_ids(TOKEN_CSV)
    print(f"📋 发现 {len(jsonls)} 个 session jsonl")
    print(f"   csv 已记录 session_id: {len(already)} 个(将跳过)")
    print()

    rows_to_write: list[list] = []
    total_cost = 0.0
    total_tokens = 0

    for jpath in jsonls:
        session_id = jpath.stem  # 文件名即 uuid
        if session_id in already:
            print(f"  ⏭ {session_id[:8]}... 已记录,跳过")
            continue

        # 算 cost(同 hook 逻辑)
        cost = calc_session_cost(jpath)
        if not cost["buckets"]:
            print(f"  ⚠️ {session_id[:8]}... 无 assistant usage,跳过")
            continue

        # 跳过 0-token session(早期空跑 / 中断,免得污染 csv)
        if cost["total_tokens"] == 0:
            print(f"  ⚠️ {session_id[:8]}... 0 tokens,跳过(空跑/中断)")
            continue

        # agent 探测(jsonl 内容)
        agent = detect_agent_from_jsonl(jpath)

        # 时间戳(从第一条 user message)
        ts = extract_first_user_timestamp(jpath)
        if not ts or ts == "1970-01-01T00:00:00":
            ts = datetime.now().isoformat(timespec="seconds")

        # 按 model 分桶写一行
        n_models = len(cost["buckets"])
        for model, b in sorted(cost["buckets"].items()):
            total = b["input"] + b["output"] + b["cache_read"] + b["cache_write"]
            row = [
                ts, session_id, agent,
                model, b["input"], b["output"],
                b["cache_read"], b["cache_write"],
                total,
                b["cost_usd"],
            ]
            rows_to_write.append(row)
            total_cost += b["cost_usd"]
            total_tokens += total

        size_kb = jpath.stat().st_size // 1024
        agent_label = agent or "(unknown)"
        print(
            f"  ✅ {session_id[:8]}... [{agent_label}]: "
            f"{cost['total_tokens']:,} tokens, ${cost['total_cost_usd']:.4f} "
            f"({n_models} models, jsonl {size_kb}KB)"
        )

    print()
    if not rows_to_write:
        print("(没有新数据要写)")
        return 0

    if args.dry_run:
        print(f"🔍 DRY-RUN: 将补录 {len(rows_to_write)} 行, "
              f"总 tokens {total_tokens:,}, 总费用 ${total_cost:.4f}")
        return 0

    # 实际写入
    is_new = not TOKEN_CSV.exists()
    TOKEN_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(CSV_HEADER)
        writer.writerows(rows_to_write)

    print(f"📊 已补录 {len(rows_to_write)} 行(对应 {len(jsonls) - len(already)} 个新 session)")
    print(f"   总 tokens: {total_tokens:,}")
    print(f"   总费用:   ${total_cost:.4f}")
    print(f"   写入: {TOKEN_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
