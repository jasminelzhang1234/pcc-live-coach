#!/usr/bin/env python3
"""
单 session token 用量 + 估算费用计算。

被两个调用方使用:
  - scripts/hook_token_usage.py (Stop hook 落账)
  - scripts/gen_token_dashboard.py / scripts/gen_spending_report.py (HTML 报告生成)

定价表(USD per million tokens,2026-08-26 收集):

  MiniMax-M3 (默认,当前用户使用):
    input          $3.00   ← MiniMax 公开 API 价(https://MiniMax.com/pricing)
    output        $15.00   ← MiniMax 公开 API 价
    cache_read     $0.30   ← MiniMax 公开 API 页未列 cache 价,参照 Sonnet 4.5
                              (底层都是 Anthropic prompt caching,定价一致)
    cache_write    $3.75   ← 同上

  其他模型(留作扩展):
    claude-sonnet-4-5 / haiku-4-5 / opus-4-5 / deepseek-v4-flash

模型 id 前缀匹配(兼容带日期后缀):
  claude-sonnet-4-5-20250929  →  claude-sonnet-4-5
  claude-haiku-4-5-20251001   →  claude-haiku-4-5
  MiniMax-M3.0                →  MiniMax-M3

CLI 用法:
  python3 scripts/calc_token_cost.py <session-uuid-or-jsonl-path>
  python3 scripts/calc_token_cost.py 26096f98-034a-4bb8-bc37-ab64a2f0bc0e

环境变量:
  PCC_PROJECTS_DIR  若 ~/.claude/projects/.../ 路径不对,覆盖用
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 各模型定价常量(USD per million tokens)— 价格变动时改这里
# MiniMax-M3 是当前 Claude Code 实际跑的模型,价格来源:
#   input/output: MiniMax 公开 API 定价页(2026-08-26 抓到)
#   cache_read/write: MiniMax 公开页未列,参照 Sonnet 4.5(底层 Anthropic prompt
#   caching 机制相同,推断定价一致);若实际 cache 价,改这里即可
_MINIMAX_M3 = {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75}

# 备用(其他模型,目前未在 PCC 工作区出现)
_SONNET_45 = {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75}
_HAIKU_45  = {"input": 1.0, "output": 5.0,  "cache_read": 0.10, "cache_write": 1.25}
_OPUS_45   = {"input": 15.0,"output": 75.0, "cache_read": 1.50, "cache_write": 18.75}
_DEEPSEEK  = {"input": 0.27,"output": 1.10, "cache_read": 0.0,  "cache_write": 0.0}

MODEL_PRICING: dict[str, dict[str, float]] = {
    "MiniMax-M3":        _MINIMAX_M3,   # ← 当前及未来长期使用
    "claude-sonnet-4-5": _SONNET_45,
    "claude-haiku-4-5":  _HAIKU_45,
    "claude-opus-4-5":   _OPUS_45,
    "deepseek-v4-flash": _DEEPSEEK,
}


def _lookup_pricing(model: str) -> tuple[dict[str, float] | None, str | None]:
    """前缀匹配定价表。返回 (pricing_dict, matched_prefix) 或 (None, None)。"""
    for prefix, pricing in MODEL_PRICING.items():
        if model.startswith(prefix):
            return pricing, prefix
    return None, None


def aggregate_session_usage(jsonl_path: Path) -> dict[str, dict[str, int]]:
    """聚合 jsonl 里所有 assistant 行的 usage,按 model 分桶。

    返回 {model: {input, output, cache_read, cache_write, n_calls}}
    """
    buckets: dict[str, dict[str, int]] = {}
    with open(jsonl_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message", {})
            model = msg.get("model", "unknown")
            u = msg.get("usage")
            if not u:
                continue
            b = buckets.setdefault(model, {
                "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "n_calls": 0
            })
            b["input"]      += u.get("input_tokens", 0)
            b["output"]     += u.get("output_tokens", 0)
            b["cache_read"] += u.get("cache_read_input_tokens", 0)
            b["cache_write"]+= u.get("cache_creation_input_tokens", 0)
            b["n_calls"]    += 1
    return buckets


def calc_session_cost(jsonl_path: Path) -> dict:
    """算单 session 的总费用。

    返回:
      {
        "buckets": {model: {tokens..., cost_usd, matched_pricing_prefix}},
        "total_tokens": int,
        "total_cost_usd": float,
        "unmatched_models": [model, ...]  # 定价表里没有的
      }
    """
    buckets = aggregate_session_usage(jsonl_path)
    total_tokens = 0
    total_cost = 0.0
    unmatched: list[str] = []

    for model, b in buckets.items():
        pricing, prefix = _lookup_pricing(model)
        if pricing is None:
            unmatched.append(model)
            b["cost_usd"] = 0.0
            b["matched_pricing_prefix"] = None
        else:
            b["cost_usd"] = round(
                b["input"]      /1e6 * pricing["input"] +
                b["output"]     /1e6 * pricing["output"] +
                b["cache_read"] /1e6 * pricing["cache_read"] +
                b["cache_write"]/1e6 * pricing["cache_write"], 6)
            b["matched_pricing_prefix"] = prefix
            total_cost += b["cost_usd"]
        total_tokens += b["input"] + b["output"] + b["cache_read"] + b["cache_write"]

    return {
        "buckets": buckets,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "unmatched_models": unmatched,
    }


def resolve_jsonl_path(arg: str, projects_dir: Path | None = None) -> Path:
    """把 CLI 参数(可能是 uuid 或绝对路径)解析成 jsonl Path。"""
    p = Path(arg)
    if p.is_file():
        return p
    if projects_dir is None:
        projects_dir = Path.home() / ".claude" / "projects"
    matches = sorted(projects_dir.rglob(f"*{arg}*.jsonl"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"⚠️ 多个匹配 {arg},取第一个: {[m.name for m in matches[:3]]}", file=sys.stderr)
        return matches[0]
    raise FileNotFoundError(f"找不到 jsonl: {arg} (在 {projects_dir} 下)")


def format_human(cost: dict) -> str:
    """把 cost dict 格式化成人类可读的字符串。"""
    lines = []
    lines.append("📊 Session token usage:")
    lines.append(f"   total_tokens:   {cost['total_tokens']:,}")
    lines.append(f"   total_cost_usd: ${cost['total_cost_usd']:.4f}")
    lines.append("")
    lines.append("   By model:")
    for model, b in sorted(cost["buckets"].items()):
        prefix = b.get("matched_pricing_prefix") or "(unmatched, $0)"
        total = b["input"]+b["output"]+b["cache_read"]+b["cache_write"]
        lines.append(f"   - {model} [{prefix}]: {b['n_calls']} calls, "
                     f"{total:,} tokens, ${b['cost_usd']:.4f}")
    if cost["unmatched_models"]:
        lines.append("")
        lines.append("   ⚠️ Unmatched models (在 jsonl 里但不在定价表):")
        for m in cost["unmatched_models"]:
            lines.append(f"     - {m}")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 scripts/calc_token_cost.py <session-uuid-or-jsonl-path>", file=sys.stderr)
        return 1
    try:
        jsonl = resolve_jsonl_path(sys.argv[1])
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    cost = calc_session_cost(jsonl)
    print(format_human(cost))
    return 0


if __name__ == "__main__":
    sys.exit(main())
