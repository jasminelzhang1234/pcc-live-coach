#!/usr/bin/env python3
"""gen_spending_report.py — Token spending report,聚焦 25 场 AI 陪练 + 评估 + tracking 流水线。

数据源:
  - progress/tracker.csv                  → 25 场 AI 陪练 + 4 场真人练习
  - progress/token-usage.csv              → hook 落账的早期 session(2026-08-21 ~ 09-01)
  - progress/token-usage-backfilled-{date}.csv → 从 jsonl 反向 backfill 的全量 session

输出:
  - progress/token-spending-report-{date}.html  → 完整 HTML 报告

设计原则:
  - 视觉风格沿用 progress/token-usage-dashboard-2026-08-26.html(用户接受)
  - 新增 "AI 陪练流水线" KPI 行(陪练 / 评估 / 校准 拆分)
  - Per-session 表格 join tracker.csv,显示 cost / ✔ / 命中率
  - 数据完整性 disclosure:已记账 N/25 场 vs 仅 hook N/25 场
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS = ROOT / "progress"
TRACKER_CSV = PROGRESS / "tracker.csv"
REAL_CSV = PROGRESS / "tracker-sessions.csv"
TOKEN_CSV = PROGRESS / "token-usage.csv"
BACKFILL_CSV = next(PROGRESS.glob("token-usage-backfilled-*.csv"), None)

TODAY = date.today().isoformat()
OUT_HTML = PROGRESS / f"token-spending-report-{TODAY}.html"


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_token_rows() -> list[dict]:
    """合并 token-usage.csv + backfilled CSV,按 session_id 去重(优先 backfill,因为它有 detected_persona / first_user_prompt)。

    token-usage.csv 缺 detected_persona 列,会覆盖空值,所以用 backfill 优先。
    """
    rows: dict[str, dict] = {}
    # 先 backfill(覆盖范围广 + 带 persona)
    if BACKFILL_CSV:
        for r in load_csv(BACKFILL_CSV):
            sid = r["session_id"]
            key = f"{sid}|{r['model']}"
            rows[key] = r
    # 再原始 hook(只补 backfill 没覆盖到的 session)
    if TOKEN_CSV.exists():
        for r in load_csv(TOKEN_CSV):
            sid = r.get("session_id", "")
            model = r.get("model", "")
            key = f"{sid}|{model}"
            if key not in rows:
                # token-usage.csv 没 detected_persona 列,补上空字符串避免 KeyError
                rows[key] = {
                    **r,
                    "first_user_prompt": "",
                    "detected_persona": "",
                }
    return list(rows.values())


def parse_int(v: str, default: int = 0) -> int:
    try:
        return int(float(v or 0))
    except (ValueError, TypeError):
        return default


def parse_float(v: str, default: float = 0.0) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return default


def fmt_int(n: float) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{int(n)}"


def fmt_cost(c: float) -> str:
    if c == 0:
        return "$0"
    if c < 0.01:
        return f"${c*100:.2f}¢"
    return f"${c:.2f}"


def main() -> int:
    if not TRACKER_CSV.exists():
        print(f"❌ {TRACKER_CSV} not found", file=sys.stderr)
        return 1

    # 读 tracker.csv(25 场 AI 陪练)
    ai_sessions = load_csv(TRACKER_CSV)
    real_sessions = load_csv(REAL_CSV)
    token_rows = load_token_rows()

    # 聚合 token usage
    by_agent: dict[str, dict] = defaultdict(
        lambda: {"sessions": set(), "tokens": 0, "input": 0, "output": 0,
                 "cache_read": 0, "cost": 0.0}
    )
    by_date: dict[str, dict] = defaultdict(
        lambda: {"sessions": set(), "tokens": 0, "cost": 0.0, "agent": set()}
    )
    by_persona_session: dict[str, dict] = defaultdict(
        lambda: {"tokens": 0, "cost": 0.0, "models": set(),
                 "agents": set(), "sessions": set()}
    )

    total_tokens = 0
    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    n_sessions_logged = set()

    for r in token_rows:
        agent = r.get("agent") or "(unknown)"
        model = r.get("model") or "(unknown)"
        sid = r.get("session_id", "")
        ts = r.get("timestamp", "")
        day = ts[:10] if ts else "(no-date)"
        tokens = parse_int(r.get("total_tokens"))
        cost = parse_float(r.get("estimated_cost_usd"))
        inp = parse_int(r.get("input_tokens"))
        out = parse_int(r.get("output_tokens"))
        cr = parse_int(r.get("cache_read_tokens"))
        persona = r.get("detected_persona", "")

        by_agent[agent]["sessions"].add(sid)
        by_agent[agent]["tokens"] += tokens
        by_agent[agent]["input"] += inp
        by_agent[agent]["output"] += out
        by_agent[agent]["cache_read"] += cr
        by_agent[agent]["cost"] += cost

        by_date[day]["sessions"].add(sid)
        by_date[day]["tokens"] += tokens
        by_date[day]["cost"] += cost
        by_date[day]["agent"].add(agent)

        if persona:
            by_persona_session[persona]["sessions"].add(sid)
            by_persona_session[persona]["models"].add(model)
            by_persona_session[persona]["agents"].add(agent)
            by_persona_session[persona]["tokens"] += tokens
            by_persona_session[persona]["cost"] += cost

        total_tokens += tokens
        total_cost += cost
        total_input += inp
        total_output += out
        total_cache_read += cr
        n_sessions_logged.add(sid)

    # set → count
    for d in (by_agent, by_date):
        for v in d.values():
            v["sessions"] = len(v["sessions"])
    for persona, v in by_persona_session.items():
        v["sessions"] = len(v["sessions"])
        v["models"] = ", ".join(sorted(v["models"]))
        v["agents"] = ", ".join(sorted(v["agents"]))

    cache_pct = (total_cache_read / (total_input + total_cache_read) * 100) \
        if (total_input + total_cache_read) > 0 else 0

    # === 匹配 tracker.csv 与 token 数据 ===
    # 策略:按 (date, persona) 匹配;同一日期同一 persona 的多个陪练场用 round-robin 分配
    # 简化:每个 tracker session 关联到该 date+persona 的最早 jsonl
    # 这样我们就有一个 "陪练陪练有多少 token 花费"的近似

    # 按 (date, persona) 分桶 backfill 行
    bf_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in token_rows:
        if r.get("agent") != "pcc-coachee":
            continue
        persona = r.get("detected_persona", "")
        if not persona:
            continue
        day = r.get("timestamp", "")[:10]
        bf_by_key[(day, persona)].append(r)

    # 每个 tracker session 标注 has_token_cost
    # 匹配策略:同 (date, persona) 平摊 — bucket 内总 cost / tracker count
    tracker_to_count = defaultdict(int)
    for t in ai_sessions:
        key = (t.get("conversation_date", ""), t.get("persona", ""))
        tracker_to_count[key] += 1

    tracker_rows = []
    for t in ai_sessions:
        date_s = t.get("conversation_date", "")
        persona = t.get("persona", "")
        key = (date_s, persona)
        bf_rows = bf_by_key.get(key, [])
        has_token = bool(bf_rows)
        # 平摊:该 bucket 内总 cost / 该 bucket 在 tracker 里的 session 数
        total_bf_cost = sum(parse_float(r.get("estimated_cost_usd")) for r in bf_rows)
        total_bf_tokens = sum(parse_int(r.get("total_tokens")) for r in bf_rows)
        n_tracked_in_bucket = tracker_to_count[key]
        cost = total_bf_cost / n_tracked_in_bucket if n_tracked_in_bucket > 0 and has_token else 0
        tokens = total_bf_tokens // n_tracked_in_bucket if n_tracked_in_bucket > 0 and has_token else 0
        tracker_rows.append({
            "session_id": t["session_id"],
            "date": date_s,
            "time": t.get("conversation_time", ""),
            "persona": persona,
            "difficulty": t.get("difficulty", ""),
            "topic": t.get("topic", ""),
            "hit_rate_pct": round(parse_int(t["claude_total_✔"]) / 37 * 100, 1),
            "n_total": parse_int(t["claude_total_✔"]) + parse_int(t["claude_total_△"]) + parse_int(t["claude_total_✘"]),
            "n_yes": parse_int(t["claude_total_✔"]),
            "n_mid": parse_int(t["claude_total_△"]),
            "n_no": parse_int(t["claude_total_✘"]),
            "must_hit_x": parse_int(t.get("must_hit_✘_count", "")),
            "judge": t.get("judge_main", ""),
            "eval_version": t.get("eval_version", ""),
            "cost": cost,
            "tokens": tokens,
            "has_token": has_token,
        })

    n_with_token = sum(1 for r in tracker_rows if r["has_token"])
    n_without = len(tracker_rows) - n_with_token
    sum_cost_tracked = sum(r["cost"] for r in tracker_rows if r["has_token"])

    # === KPI ===
    n_ai = len(ai_sessions)
    n_real = len(real_sessions)
    n_total_logged = len(n_sessions_logged)

    # max single session cost
    top_token_row = max(token_rows, key=lambda r: parse_float(r.get("estimated_cost_usd"))) if token_rows else None

    # per-陪练 / 评估 / 校准 cost breakdown
    coachee_cost = by_agent.get("pcc-coachee", {}).get("cost", 0)
    assessor_cost = by_agent.get("pcc-assessor", {}).get("cost", 0)
    tracker_cost_agent = by_agent.get("pcc-tracker", {}).get("cost", 0)
    second_judge_cost = by_agent.get("pcc-second-judge-deepseek", {}).get("cost", 0)

    # === 构建 HTML ===
    # sorted by date for trend
    sorted_dates = sorted(by_date.items())

    # 准备 chart JSON
    agent_chart_json = json.dumps({
        "labels": [a for a, _ in sorted(by_agent.items(), key=lambda x: -x[1]["cost"])],
        "costs": [round(v["cost"], 4) for _, v in sorted(by_agent.items(), key=lambda x: -x[1]["cost"])],
        "tokens": [v["tokens"] for _, v in sorted(by_agent.items(), key=lambda x: -x[1]["cost"])],
    }, ensure_ascii=False)

    persona_chart_json = json.dumps({
        "labels": [p for p, _ in sorted(by_persona_session.items(), key=lambda x: -x[1]["cost"])],
        "costs": [round(v["cost"], 4) for _, v in sorted(by_persona_session.items(), key=lambda x: -x[1]["cost"])],
        "tokens": [v["tokens"] for _, v in sorted(by_persona_session.items(), key=lambda x: -x[1]["cost"])],
    }, ensure_ascii=False)

    date_chart_json = json.dumps({
        "labels": [d for d, _ in sorted_dates],
        "cost": [round(v["cost"], 4) for _, v in sorted_dates],
        "tokens": [v["tokens"] for _, v in sorted_dates],
        "sessions": [v["sessions"] for _, v in sorted_dates],
    }, ensure_ascii=False)

    # 25 场表(按 cost 降序;无 token 的也显示标 "(unknown)")
    scored_sessions = sorted(tracker_rows, key=lambda r: (-r["cost"], r["date"]))
    detail_rows_html = []
    for s in scored_sessions:
        hit_pct = s["hit_rate_pct"]
        hit_color = "#2f855a" if hit_pct >= 85 else ("#d97706" if hit_pct >= 70 else "#c53030")
        persona_color = {
            "vec-06": "#4e79a7", "vec-07": "#59a14f", "vec-08": "#9c755f",
            "vec-09": "#bab0ab", "vec-04": "#e15759", "voc-08": "#b07aa1",
            "voc-06": "#76b7b2",
        }.get(s["persona"], "#94a3b8")
        cost_str = fmt_cost(s["cost"]) if s["has_token"] else "<span style='color:#94a3b8'>—</span>"
        token_str = fmt_int(s["tokens"]) if s["has_token"] else "<span style='color:#94a3b8'>—</span>"
        detail_rows_html.append(
            f"""          <tr>
            <td style="font-family: ui-monospace, monospace; font-size: 11px;">{s['date']} {s['time']}</td>
            <td style="font-family: ui-monospace, monospace; font-size: 11px;">{s['session_id']}</td>
            <td><span class="badge" style="background: {persona_color}22; color: {persona_color};">{s['persona']}</span></td>
            <td style="text-align: center;">{s['difficulty']}</td>
            <td style="font-size: 12px; max-width: 280px;">{s['topic'][:60]}{'…' if len(s['topic'])>60 else ''}</td>
            <td style="text-align: right; font-weight: 600; color: {hit_color};">{hit_pct:.1f}%</td>
            <td style="text-align: center; font-size: 11px;">{s['n_yes']}/{s['n_mid']}/{s['n_no']}</td>
            <td style="text-align: right;">{cost_str}</td>
            <td style="text-align: right;">{token_str}</td>
          </tr>"""
        )
    detail_rows_str = "\n".join(detail_rows_html)

    # 整体覆盖 disclosure callout
    coverage_pct = n_with_token / n_ai * 100
    callout = (
        f"<strong>📊 数据覆盖:</strong> 25 场 AI 陪练中,"
        f"<strong>{n_with_token}</strong> 场有 token 数据 "
        f"(<strong>{coverage_pct:.1f}%</strong>),"
        f"{n_without} 场 <code>token-usage.csv</code> 因 hook 早期未稳定触发 + 后期未挂回缺失。"
        f"Backfill 自 <code>~/.claude/projects/.../*.jsonl</code> 反向聚合后,<strong>{sum_cost_tracked:.2f}</strong> 是已配对 tracker session 的总费用 "
        f"(剩余 token 进入 '未配对 (unknown)' 桶)。"
    )

    html = HTML_TEMPLATE.replace("__TODAY__", TODAY)
    html = html.replace("__N_AI_SESSIONS__", str(n_ai))
    html = html.replace("__N_REAL_SESSIONS__", str(n_real))
    html = html.replace("__N_WITH_TOKEN__", str(n_with_token))
    html = html.replace("__COVERAGE_PCT__", f"{coverage_pct:.1f}")
    html = html.replace("__N_TOTAL_LOGGED__", str(n_total_logged))
    html = html.replace("__TOTAL_COST__", f"${total_cost:.2f}")
    html = html.replace("__TOTAL_TOKENS__", fmt_int(total_tokens))
    html = html.replace("__AVG_PER_SESSION__", f"${total_cost/max(n_total_logged,1):.2f}")
    html = html.replace("__CACHE_PCT__", f"{cache_pct:.1f}")
    html = html.replace("__MAX_COST__", fmt_cost(parse_float(top_token_row.get("estimated_cost_usd"))) if top_token_row else "$0")
    html = html.replace("__COACHEE_COST__", f"${coachee_cost:.2f}")
    html = html.replace("__ASSESSOR_COST__", f"${assessor_cost:.2f}")
    html = html.replace("__TRACKER_COST__", f"${tracker_cost_agent:.2f}")
    html = html.replace("__JUDGE_COST__", f"${second_judge_cost:.2f}")
    html = html.replace("__COACHEE_PCT__", f"{coachee_cost/total_cost*100:.1f}" if total_cost else "0")
    html = html.replace("__ASSESSOR_PCT__", f"{assessor_cost/total_cost*100:.1f}" if total_cost else "0")
    html = html.replace("__TRACKER_PCT__", f"{tracker_cost_agent/total_cost*100:.1f}" if total_cost else "0")
    html = html.replace("__JUDGE_PCT__", f"{second_judge_cost/total_cost*100:.1f}" if total_cost else "0")
    html = html.replace("__COACHEE_TOKENS__", fmt_int(by_agent.get("pcc-coachee", {}).get("tokens", 0)))
    html = html.replace("__ASSESSOR_TOKENS__", fmt_int(by_agent.get("pcc-assessor", {}).get("tokens", 0)))
    html = html.replace("__TRACKER_TOKENS__", fmt_int(by_agent.get("pcc-tracker", {}).get("tokens", 0)))
    html = html.replace("__JUDGE_TOKENS__", fmt_int(by_agent.get("pcc-second-judge-deepseek", {}).get("tokens", 0)))
    html = html.replace("__CALLOUT__", callout)
    html = html.replace("__DETAIL_ROWS__", detail_rows_str)
    html = html.replace("__AGENT_CHART_JSON__", agent_chart_json)
    html = html.replace("__PERSONA_CHART_JSON__", persona_chart_json)
    html = html.replace("__DATE_CHART_JSON__", date_chart_json)

    OUT_HTML.write_text(html, encoding="utf-8")
    os.sync()

    print(f"✅ {OUT_HTML}")
    print(f"   25 AI 陪练: {n_ai} · 已记账 {n_with_token} ({coverage_pct:.1f}%)")
    print(f"   总 token {fmt_int(total_tokens)} · 总费用 ${total_cost:.2f}")
    print(f"   配对到 tracker session 的累计费用: ${sum_cost_tracked:.2f}")
    return 0


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PCC AI 陪练流水线 Token Spending Report · __TODAY__</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #f7f8fb; --card: #ffffff; --border: #e5e8ef;
      --text: #1c2027; --muted: #5b6473; --accent: #2b6cb0;
      --good: #2f855a; --warn: #d97706; --bad: #c53030;
      --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.5;
    }
    .container { max-width: 1280px; margin: 0 auto; }
    header {
      background: linear-gradient(135deg, #2b6cb0 0%, #4299e1 100%);
      color: white; padding: 28px 32px; border-radius: 14px;
      box-shadow: var(--shadow); margin-bottom: 24px;
    }
    header h1 { margin: 0 0 8px 0; font-size: 26px; font-weight: 600; letter-spacing: -0.5px; }
    header .subtitle { opacity: 0.9; font-size: 14px; margin-bottom: 18px; }
    .kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; }
    .kpi {
      background: rgba(255,255,255,0.14); backdrop-filter: blur(8px);
      padding: 14px 16px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.18);
    }
    .kpi-label { font-size: 12px; opacity: 0.85; margin-bottom: 4px; }
    .kpi-value { font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }
    .kpi-sub { font-size: 11px; opacity: 0.75; margin-top: 2px; }
    .card {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 24px; margin-bottom: 20px; box-shadow: var(--shadow);
    }
    .card h2 { margin: 0 0 4px 0; font-size: 18px; font-weight: 600; }
    .card .desc { color: var(--muted); font-size: 13px; margin-bottom: 18px; }
    .chart-wrap { position: relative; height: 380px; }
    .chart-wrap.short { height: 320px; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    thead th {
      text-align: left; padding: 10px 12px; background: #f1f4f7;
      font-weight: 600; color: var(--muted); border-bottom: 2px solid var(--border);
      font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
    }
    thead th.r { text-align: right; }
    tbody td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
    tbody tr:hover { background: #fafbfd; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; font-family: ui-monospace, "SF Mono", monospace; white-space: nowrap; }
    .callout {
      padding: 14px 16px; background: #fff8e6; border-left: 3px solid var(--warn);
      border-radius: 6px; font-size: 13px; color: #5b4406; margin-top: 12px;
    }
    .callout.good {
      background: #f0fff4; border-left-color: var(--good); color: #1c4532;
    }
    .legend-row { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; font-size: 13px; color: var(--muted); }
    .legend-row .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
    footer { margin-top: 32px; padding: 20px; text-align: center; font-size: 12px; color: var(--muted); }
    .pricing-note {
      font-size: 11px; color: var(--muted); margin-top: 8px; line-height: 1.6;
      background: #f1f4f7; padding: 8px 12px; border-radius: 6px;
    }
    .pricing-note code { background: rgba(0,0,0,0.06); padding: 1px 4px; border-radius: 3px; }
    .pipeline {
      display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 14px;
    }
    @media (max-width: 900px) { .pipeline { grid-template-columns: repeat(2, 1fr); } }
    .pipe {
      background: var(--card); border: 1px solid var(--border); border-radius: 10px;
      padding: 14px; text-align: center;
    }
    .pipe-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
    .pipe-cost { font-size: 20px; font-weight: 600; margin: 4px 0; }
    .pipe-pct { font-size: 11px; color: var(--muted); }
    .pipe-tokens { font-size: 12px; color: var(--muted); margin-top: 2px; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>PCC AI 陪练流水线 Token Spending Report</h1>
      <div class="subtitle">
        __N_AI_SESSIONS__ 场 AI 陪练 + __N_REAL_SESSIONS__ 场 真人练习 · 生成于 __TODAY__ ·
        数据源 <code style="background:rgba(255,255,255,0.18);padding:2px 6px;border-radius:3px;">token-usage.csv</code> +
        <code style="background:rgba(255,255,255,0.18);padding:2px 6px;border-radius:3px;">token-usage-backfilled-__TODAY__.csv</code> +
        <code style="background:rgba(255,255,255,0.18);padding:2px 6px;border-radius:3px;">tracker.csv</code>
      </div>
      <div class="kpi-row">
        <div class="kpi"><div class="kpi-label">总费用</div><div class="kpi-value">__TOTAL_COST__</div><div class="kpi-sub">MiniMax M3 + DeepSeek V4 Flash API 估算</div></div>
        <div class="kpi"><div class="kpi-label">总 tokens</div><div class="kpi-value">__TOTAL_TOKENS__</div><div class="kpi-sub">含 cache_read</div></div>
        <div class="kpi"><div class="kpi-label">已记账 sessions</div><div class="kpi-value">__N_TOTAL_LOGGED__</div><div class="kpi-sub">unique jsonl</div></div>
        <div class="kpi"><div class="kpi-label">平均 / session</div><div class="kpi-value">__AVG_PER_SESSION__</div><div class="kpi-sub">cost / jsonl</div></div>
        <div class="kpi"><div class="kpi-label">Cache 命中率</div><div class="kpi-value">__CACHE_PCT__%</div><div class="kpi-sub">cache_read / (input+cache_read)</div></div>
        <div class="kpi"><div class="kpi-label">最大单笔</div><div class="kpi-value">__MAX_COST__</div><div class="kpi-sub">cost / single jsonl</div></div>
      </div>
    </header>

    <div class="card">
      <h2>① AI 陪练流水线拆分</h2>
      <p class="desc">3 大 agent + 1 校准模型 = PCC 流水线。点击下方任一卡片查看 token 构成。</p>
      <div class="pipeline">
        <div class="pipe" style="border-top: 3px solid #2b6cb0;">
          <div class="pipe-label">① pcc-coachee · 陪练</div>
          <div class="pipe-cost">__COACHEE_COST__</div>
          <div class="pipe-pct">__COACHEE_PCT__% · __COACHEE_TOKENS__ tokens</div>
        </div>
        <div class="pipe" style="border-top: 3px solid #4e79a7;">
          <div class="pipe-label">② pcc-assessor · 评估</div>
          <div class="pipe-cost">__ASSESSOR_COST__</div>
          <div class="pipe-pct">__ASSESSOR_PCT__% · __ASSESSOR_TOKENS__ tokens</div>
        </div>
        <div class="pipe" style="border-top: 3px solid #59a14f;">
          <div class="pipe-label">③ pcc-tracker · 追踪</div>
          <div class="pipe-cost">__TRACKER_COST__</div>
          <div class="pipe-pct">__TRACKER_PCT__% · __TRACKER_TOKENS__ tokens</div>
        </div>
        <div class="pipe" style="border-top: 3px solid #f28e2b;">
          <div class="pipe-label">④ 三方校准 · DeepSeek</div>
          <div class="pipe-cost">__JUDGE_COST__</div>
          <div class="pipe-pct">__JUDGE_PCT__% · __JUDGE_TOKENS__ tokens</div>
        </div>
      </div>
      <div class="pricing-note">
        <strong>解读:</strong>pcc-coachee 永远是大头(陪练会话最长 + persona 完整 prompt 注入),
        pcc-assessor 第二(逐字稿 + 37 marker 判定),pcc-tracker 接近 0(tracker agent 大多走 local 脚本,LLM 介入轻),
        三方校准用 DeepSeek V4 Flash(便宜 96% 仅做 calibration)。
      </div>
    </div>

    <div class="callout">
      __CALLOUT__
    </div>

    <div class="grid-2">
      <div class="card">
        <h2>② 按 Agent 分桶</h2>
        <p class="desc">每个 agent 累计的 token + 估算费用。</p>
        <div class="chart-wrap short"><canvas id="agentChart"></canvas></div>
      </div>
      <div class="card">
        <h2>③ 按 Persona 花费</h2>
        <p class="desc">每个 persona(从首条 user prompt 反推)的累计 token + 费用 — 只含 pcc-coachee。</p>
        <div class="chart-wrap short"><canvas id="personaChart"></canvas></div>
      </div>
    </div>

    <div class="card">
      <h2>④ 按 Date 趋势</h2>
      <p class="desc">每天的 token 花费 + session 数。点峰看当天是哪一场陪练 / 评估。</p>
      <div class="chart-wrap"><canvas id="dateChart"></canvas></div>
    </div>

    <div class="card">
      <h2>⑤ 25 场 AI 陪练 per-session 表(按 cost 降序)</h2>
      <p class="desc">__N_WITH_TOKEN__ / __N_AI_SESSIONS__ 场配对到 token 数据(覆盖 __COVERAGE_PCT__%)。
        "—" = 该场次 hook 未触发且无对应 jsonl(陪练陪练走非 Claude Code 路径,或 hook 配置丢失)。
        命中率 = claude_total_✔ / 37 marker,严格口径(v4.1.0+ 起,与 trending chart 主指标对齐)。</p>
      <table>
        <thead>
          <tr>
            <th>对话日期时间</th>
            <th>session_id</th>
            <th>persona</th>
            <th class="r">难度</th>
            <th>议题</th>
            <th class="r">命中率</th>
            <th class="r">✔/△/✘</th>
            <th class="r">cost</th>
            <th class="r">tokens</th>
          </tr>
        </thead>
        <tbody>
__DETAIL_ROWS__
        </tbody>
      </table>
    </div>

    <footer>
      数据来源 <code>progress/tracker.csv</code> (25 行) + <code>progress/token-usage.csv</code> (43 行 hook) +
      <code>progress/token-usage-backfilled-__TODAY__.csv</code> (83 行 backfill) ·
      定价表 <code>scripts/calc_token_cost.py</code> ·
      Backfill <code>scripts/backfill_token_usage.py</code> ·
      生成脚本 <code>scripts/gen_spending_report.py</code> ·
      生成于 __TODAY__
    </footer>
  </div>

  <script>
    const agentData = __AGENT_CHART_JSON__;
    const personaData = __PERSONA_CHART_JSON__;
    const dateData  = __DATE_CHART_JSON__;

    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    Chart.defaults.color = '#5b6473';

    // ===== ② 按 Agent bar =====
    const AGENT_COLORS = {
      'pcc-coachee': '#2b6cb0',
      'pcc-assessor': '#4e79a7',
      'pcc-tracker': '#59a14f',
      'pcc-second-judge-deepseek': '#f28e2b',
      '(unknown)': '#94a3b8',
    };
    new Chart(document.getElementById('agentChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: agentData.labels,
        datasets: [{
          label: 'cost (USD)',
          data: agentData.costs,
          backgroundColor: agentData.labels.map(l => AGENT_COLORS[l] || '#94a3b8'),
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12,
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                return [
                  `cost: $${agentData.costs[i].toFixed(4)}`,
                  `tokens: ${agentData.tokens[i].toLocaleString()}`,
                ];
              },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, ticks: { callback: (v) => '$' + v.toFixed(2) }, grid: { color: '#eef0f4' } },
          y: { grid: { display: false } },
        },
      },
    });

    // ===== ③ 按 Persona bar =====
    const PERSONA_COLORS = {
      'vec-06': '#4e79a7', 'vec-07': '#59a14f', 'vec-08': '#9c755f',
      'vec-09': '#bab0ab', 'vec-04': '#e15759', 'vec-02': '#ff9da7',
      'voc-08': '#b07aa1', 'voc-06': '#76b7b2',
    };
    new Chart(document.getElementById('personaChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: personaData.labels,
        datasets: [{
          label: 'cost (USD)',
          data: personaData.costs,
          backgroundColor: personaData.labels.map(l => PERSONA_COLORS[l] || '#94a3b8'),
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12,
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                return [
                  `cost: $${personaData.costs[i].toFixed(4)}`,
                  `tokens: ${personaData.tokens[i].toLocaleString()}`,
                ];
              },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, ticks: { callback: (v) => '$' + v.toFixed(2) }, grid: { color: '#eef0f4' } },
          y: { grid: { display: false } },
        },
      },
    });

    // ===== ④ 按 Date line + bar combo =====
    new Chart(document.getElementById('dateChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: dateData.labels,
        datasets: [
          {
            type: 'bar', label: 'cost (USD)',
            data: dateData.cost,
            backgroundColor: 'rgba(43,108,176,0.7)',
            borderRadius: 3, yAxisID: 'y',
          },
          {
            type: 'line', label: 'sessions',
            data: dateData.sessions,
            borderColor: '#f28e2b', backgroundColor: 'rgba(242,142,43,0.08)',
            borderWidth: 2.5, tension: 0.25, pointRadius: 5, pointHoverRadius: 7,
            yAxisID: 'y1', fill: false,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, padding: 12 } },
          tooltip: {
            backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12,
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                if (ctx.dataset.label === 'cost (USD)') {
                  return `cost: $${dateData.cost[i].toFixed(2)}`;
                }
                return `sessions: ${dateData.sessions[i]}`;
              },
              afterBody: (items) => {
                const i = items[0].dataIndex;
                return `tokens: ${dateData.tokens[i].toLocaleString()}`;
              },
            },
          },
        },
        scales: {
          y: { position: 'left', beginAtZero: true, ticks: { callback: (v) => '$' + v.toFixed(2) }, grid: { color: '#eef0f4' } },
          y1: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { stepSize: 1 } },
          x: { grid: { display: false } },
        },
      },
    });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())