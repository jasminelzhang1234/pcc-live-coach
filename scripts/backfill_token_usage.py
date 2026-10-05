#!/usr/bin/env python3
"""backfill_token_usage.py — 从 jsonl 反向补齐 token-usage.csv 缺失的 session。

读取 ~/.claude/projects/.../<uuid>.jsonl,
按 (session_id, model) 聚合 token 用量 + 估算费用,
从首条 user 提示反推 agent 名(pcc-coachee / pcc-assessor / pcc-tracker / pcc-second-judge-deepseek)
+ persona(vec-NN / voc-NN),
写入 progress/token-usage-backfilled-{date}.csv。

跟现有 token-usage.csv 不冲突(独立文件),原文件不动。
后续 gen_spending_report.py 会同时读两份并去重。

调用:
  python3 scripts/backfill_token_usage.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# 复用 calc_token_cost.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from calc_token_cost import calc_session_cost  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_ROOT = Path.home() / ".claude" / "projects"
PROJECT_DIR_SUFFIX = "PCC-Live-Coach"  # Claude 把项目路径编码成 -Users-...-PCC-Live-Coach

OUT_CSV = ROOT / "progress" / f"token-usage-backfilled-{date.today().isoformat()}.csv"


def find_projects_dir() -> Path | None:
    """Glob 匹配 ~/.claude/projects/ 下的 PCC-Live-Coach 项目目录。

    Claude Code 把项目绝对路径编码成目录名(`.`/`(`/空格 → `-`),
    同一项目在不同机器/不同挂载点下名字会变(OneDrive vs 云同步、
    用户名差异),硬编码整段路径不可移植。改用后缀 glob,
    多匹配时取最近修改的。
    """
    if not PROJECTS_ROOT.exists():
        return None
    matches = sorted(
        (p for p in PROJECTS_ROOT.iterdir()
         if p.is_dir() and p.name.endswith(PROJECT_DIR_SUFFIX)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None

CSV_HEADER = [
    "timestamp", "session_id", "agent", "model",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "total_tokens", "estimated_cost_usd",
    "first_user_prompt", "detected_persona",
]

# 跟 agent 关键词映射(prompt 文本 → pcc-* agent)
AGENT_PATTERNS = [
    (r"\bpcc-second-judge-deepseek\b", "pcc-second-judge-deepseek"),
    (r"\bpcc-assessor\b", "pcc-assessor"),
    (r"\bpcc-tracker\b", "pcc-tracker"),
    (r"\bpcc-coachee\b", "pcc-coachee"),
    (r"三方校准|校准\s*评估|second[-_ ]?judge", "pcc-second-judge-deepseek"),
    (r"assessor|评估(?:一下|一下对话|这|对话)?|评分|打分", "pcc-assessor"),
    (r"tracker|追踪|趋势图|trending[-_ ]?chart|analyze", "pcc-tracker"),
    (r"coachee|陪练|扮演客户|persona", "pcc-coachee"),
]

# persona 关键词(prompt 文本 → vec-NN / voc-NN / real-*)
# 不用 \b,因为 CJK 字符是 word char,会破坏 word boundary
PERSONA_PATTERNS = [
    (r"vec[\s\-_]*?(\d{1,2})(?!\d)", "vec"),
    (r"voc[\s\-_]*?(\d{1,2})(?!\d)", "voc"),
    (r"ved[\s\-_]*?(\d{1,2})(?!\d)", "vec"),   # 09-18 那次 typo VED→vec
    (r"real[\s\-_]*?client[\s\-_]*?([a-z_]+)", "real"),
]


def detect_agent(prompt: str) -> str:
    if not prompt:
        return ""
    for pat, agent in AGENT_PATTERNS:
        if re.search(pat, prompt, re.I):
            return agent
    return ""


def detect_persona(prompt: str) -> str:
    if not prompt:
        return ""
    for pat, prefix in PERSONA_PATTERNS:
        m = re.search(pat, prompt, re.I)
        if m:
            return f"{prefix}-{m.group(1).lower()}"
    return ""


def get_first_user_prompt(jsonl_path: Path) -> str:
    """Get the first human-typed user prompt text (skip tool_result / queue-op)."""
    with open(jsonl_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "user":
                continue
            msg = d.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                texts = []
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        texts.append(c.get("text", ""))
                text = " ".join(texts)
            else:
                text = str(content)
            # 跳过 tool_result-only 行
            if text and "tool_use_id" not in str(content)[:200]:
                return text
    return ""


def get_session_start(jsonl_path: Path) -> str:
    """First timestamp from jsonl (user message typically)."""
    with open(jsonl_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("timestamp", "")
            if ts:
                return ts
    return ""


# 模块加载时解析一次,后续 main() 直接复用
PROJECTS_DIR = find_projects_dir()


def main() -> int:
    if PROJECTS_DIR is None:
        print(
            f"❌ PCC project dir not found under {PROJECTS_ROOT} "
            f"(suffix={PROJECT_DIR_SUFFIX!r});请确认 ~/.claude/projects/ 存在且至少有一个子目录以 'PCC-Live-Coach' 结尾",
            file=sys.stderr,
        )
        return 1

    jsonl_files = sorted(PROJECTS_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"❌ no jsonl files in {PROJECTS_DIR}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for jf in jsonl_files:
        session_id = jf.stem
        try:
            cost = calc_session_cost(jf)
        except Exception as e:
            print(f"⚠️ {session_id[:8]}: calc failed: {e}", file=sys.stderr)
            continue

        if not cost["buckets"]:
            continue

        prompt = get_first_user_prompt(jf)
        agent = detect_agent(prompt)
        persona = detect_persona(prompt)
        start = get_session_start(jf)

        for model, b in sorted(cost["buckets"].items()):
            rows.append({
                "timestamp": start,
                "session_id": session_id,
                "agent": agent,
                "model": model,
                "input_tokens": b["input"],
                "output_tokens": b["output"],
                "cache_read_tokens": b["cache_read"],
                "cache_write_tokens": b["cache_write"],
                "total_tokens": b["input"] + b["output"] + b["cache_read"] + b["cache_write"],
                "estimated_cost_usd": b["cost_usd"],
                "first_user_prompt": prompt[:200].replace("\n", " "),
                "detected_persona": persona,
            })

    # write
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    os.sync()

    # 统计
    total_cost = sum(r["estimated_cost_usd"] for r in rows)
    total_tokens = sum(r["total_tokens"] for r in rows)
    n_pcc = sum(1 for r in rows if r["agent"].startswith("pcc-"))
    print(f"✅ {OUT_CSV}")
    print(f"   {len(jsonl_files)} 个 jsonl · {len(rows)} 行 · PCC 标识 {n_pcc}")
    print(f"   总 tokens {total_tokens:,} · 总费用 ${total_cost:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())