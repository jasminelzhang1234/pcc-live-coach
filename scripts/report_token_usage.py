#!/usr/bin/env python3
"""
读 progress/token-usage.csv,生成 markdown 汇总报告。

输出:progress/token-usage-report-{YYYY-MM-DD}.md

包含:
  - 总账(总 token / 总费用 / 平均每 session)
  - 按 agent 分桶
  - 按 model 分桶
  - 按日期趋势(若 >=2 天)

用法:
  python3 scripts/report_token_usage.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_CSV = ROOT / "progress" / "token-usage.csv"


def load_rows(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    with open(csv_path) as f:
        return list(csv.DictReader(f))


def aggregate(rows: list[dict]) -> dict:
    """按 agent / model / date 聚合。"""
    by_agent: dict[str, dict] = defaultdict(
        lambda: {"sessions": set(), "tokens": 0, "cost": 0.0}
    )
    by_model: dict[str, dict] = defaultdict(
        lambda: {"rows": 0, "tokens": 0, "cost": 0.0}
    )
    by_date: dict[str, dict] = defaultdict(
        lambda: {"sessions": set(), "tokens": 0, "cost": 0.0}
    )

    for r in rows:
        agent = r.get("agent") or "(unknown)"
        model = r.get("model") or "(unknown)"
        ts = r.get("timestamp", "")
        day = ts[:10] if ts else "(no-date)"
        sid = r.get("session_id", "")
        try:
            tokens = int(r.get("total_tokens") or 0)
        except ValueError:
            tokens = 0
        try:
            cost = float(r.get("estimated_cost_usd") or 0)
        except ValueError:
            cost = 0.0

        by_agent[agent]["sessions"].add(sid)
        by_agent[agent]["tokens"] += tokens
        by_agent[agent]["cost"] += cost

        by_model[model]["rows"] += 1
        by_model[model]["tokens"] += tokens
        by_model[model]["cost"] += cost

        by_date[day]["sessions"].add(sid)
        by_date[day]["tokens"] += tokens
        by_date[day]["cost"] += cost

    # set 转 count
    for d in (by_agent, by_date):
        for v in d.values():
            v["sessions"] = len(v["sessions"])

    return {"by_agent": by_agent, "by_model": by_model, "by_date": by_date}


def render_md(rows: list[dict], agg: dict) -> str:
    if not rows:
        return "# Token Usage Report\n\n(尚无数据 — 跑几次 PCC agent 后再来)\n"

    total_tokens = sum(int(r.get("total_tokens") or 0) for r in rows)
    total_cost = sum(float(r.get("estimated_cost_usd") or 0) for r in rows)
    unique_sessions = len({r.get("session_id") for r in rows if r.get("session_id")})
    avg = total_cost / unique_sessions if unique_sessions else 0

    out: list[str] = []
    out.append(f"# Token Usage Report — {date.today().isoformat()}")
    out.append("")

    out.append("## 总账\n")
    out.append("| sessions | total_tokens | total_cost_usd | avg_cost/session |")
    out.append("|---|---|---|---|")
    out.append(f"| {unique_sessions} | {total_tokens:,} | ${total_cost:.4f} | ${avg:.4f} |")
    out.append("")

    out.append("## 按 Agent\n")
    out.append("| agent | sessions | total_tokens | cost_usd |")
    out.append("|---|---|---|---|")
    for agent, b in sorted(agg["by_agent"].items(), key=lambda x: -x[1]["cost"]):
        out.append(f"| {agent} | {b['sessions']} | {b['tokens']:,} | ${b['cost']:.4f} |")
    out.append("")

    out.append("## 按 Model\n")
    out.append("| model | rows | total_tokens | cost_usd |")
    out.append("|---|---|---|---|")
    for model, b in sorted(agg["by_model"].items(), key=lambda x: -x[1]["cost"]):
        out.append(f"| {model} | {b['rows']} | {b['tokens']:,} | ${b['cost']:.4f} |")
    out.append("")

    if len(agg["by_date"]) > 1:
        out.append("## 按日期\n")
        out.append("| date | sessions | total_tokens | cost_usd |")
        out.append("|---|---|---|---|")
        for d in sorted(agg["by_date"].keys()):
            b = agg["by_date"][d]
            out.append(f"| {d} | {b['sessions']} | {b['tokens']:,} | ${b['cost']:.4f} |")
        out.append("")

    return "\n".join(out)


def main() -> int:
    rows = load_rows(TOKEN_CSV)
    agg = aggregate(rows)
    md = render_md(rows, agg)

    out_path = ROOT / "progress" / f"token-usage-report-{date.today().isoformat()}.md"
    out_path.write_text(md, encoding="utf-8")

    total_tokens = sum(int(r.get("total_tokens") or 0) for r in rows)
    total_cost = sum(float(r.get("estimated_cost_usd") or 0) for r in rows)
    unique = len({r.get("session_id") for r in rows if r.get("session_id")})
    print(f"📊 已生成: {out_path.relative_to(ROOT)}")
    print(f"   {len(rows)} 行数据,{unique} 个 session,"
          f"总 tokens {total_tokens:,},总费用 ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
