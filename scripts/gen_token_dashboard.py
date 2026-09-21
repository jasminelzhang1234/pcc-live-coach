#!/usr/bin/env python3
"""gen_token_dashboard.py — 从 token-usage.csv 自动生成 token 用量 dashboard HTML。

读取 observability/token-usage.csv,按 (timestamp, agent) 排序,
输出 observability/token-usage-dashboard-{date}.html。

视觉风格沿用 trending-chart-2026-08-26.html(用户接受):
- 蓝色 header + KPI 卡片
- Chart.js + chartjs-plugin-annotation
- 同一套 CSS 自定义属性 (--accent / --good / --warn / --bad)
- 中文字体栈

调色板:沿用 trending-chart 已接受的 palette(#2b6cb0 / #4e79a7 / #f28e2b 等),
       不重新跑 dataviz validator(已被项目视觉验收)。

调用:
  python3 scripts/gen_token_dashboard.py
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "observability" / "token-usage.csv"
PROGRESS = ROOT / "observability"

# 沿用 trending-chart palette
AGENT_COLORS = {
    "pcc-coachee":               "#2b6cb0",  # 蓝
    "pcc-assessor":              "#4e79a7",  # 蓝灰
    "pcc-tracker":               "#59a14f",  # 绿
    "pcc-second-judge-deepseek": "#f28e2b",  # 橙
}
DEFAULT_COLOR = "#94a3b8"  # slate-400 (合法 hex,可加 cc/88 透明度)

MODEL_COLORS = {
    "MiniMax-M3":      "#2b6cb0",  # 主蓝(MiniMax Sonnet 4.5)
    "deepseek-v4-flash": "#f28e2b",  # 橙
}

AGENT_LABEL = {
    "pcc-coachee":               "pcc-coachee (陪练)",
    "pcc-assessor":              "pcc-assessor (评估)",
    "pcc-tracker":               "pcc-tracker (追踪)",
    "pcc-second-judge-deepseek": "pcc-second-judge-deepseek (三方校准)",
}


def load_rows() -> list[dict]:
    """读 observability/token-usage.csv + progress/token-usage.csv + progress/token-usage-backfilled-*.csv,
    按 (session_id, model) 去重(backfill 优先,因为它带 persona 元数据;其次 progress/;最后 observability/)。

    返回行列表(数字字段已转 int/float)。
    """
    candidates = [
        ROOT / "observability" / "token-usage.csv",
        ROOT / "progress" / "token-usage.csv",
    ]
    # backfill 文件(glob 最新)
    backfill_glob = sorted((ROOT / "progress").glob("token-usage-backfilled-*.csv"))
    candidates.extend(backfill_glob)

    merged: dict[str, dict] = {}
    for csv_path in candidates:
        if not csv_path.exists():
            continue
        with csv_path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    sid = r.get("session_id", "")
                    model = r.get("model", "")
                    key = f"{sid}|{model}"
                    merged[key] = {
                        "timestamp": r["timestamp"],
                        "session_id": sid,
                        "agent": r.get("agent", ""),
                        "model": model,
                        "input_tokens": int(r.get("input_tokens", 0) or 0),
                        "output_tokens": int(r.get("output_tokens", 0) or 0),
                        "cache_read_tokens": int(r.get("cache_read_tokens", 0) or 0),
                        "cache_write_tokens": int(r.get("cache_write_tokens", 0) or 0),
                        "total_tokens": int(r.get("total_tokens", 0) or 0),
                        "cost_usd": float(r.get("estimated_cost_usd", 0) or 0),
                    }
                except (ValueError, KeyError):
                    continue
    return list(merged.values())


def aggregate(rows: list[dict]) -> dict:
    """按 agent / model / date 聚合。"""
    by_agent: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_date: dict[str, dict] = {}
    sessions: set[str] = set()
    total_cost = 0.0
    total_tokens = 0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0

    for r in rows:
        agent = r["agent"] or "(unknown)"
        model = r["model"] or "(unknown)"
        date = r["timestamp"][:10] if r["timestamp"] else "(no-date)"
        sid = r["session_id"]

        for bucket, key in [(by_agent, agent), (by_model, model), (by_date, date)]:
            b = bucket.setdefault(key, {
                "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                "total": 0, "cost": 0.0, "sessions": set()
            })
            b["input"] += r["input_tokens"]
            b["output"] += r["output_tokens"]
            b["cache_read"] += r["cache_read_tokens"]
            b["cache_write"] += r["cache_write_tokens"]
            b["total"] += r["total_tokens"]
            b["cost"] += r["cost_usd"]
            b["sessions"].add(sid)

        sessions.add(sid)
        total_cost += r["cost_usd"]
        total_tokens += r["total_tokens"]
        total_input += r["input_tokens"]
        total_output += r["output_tokens"]
        total_cache_read += r["cache_read_tokens"]
        total_cache_write += r["cache_write_tokens"]

    # set → count
    for bucket in (by_agent, by_model, by_date):
        for v in bucket.values():
            v["sessions"] = len(v["sessions"])

    return {
        "by_agent": by_agent,
        "by_model": by_model,
        "by_date": by_date,
        "kpi": {
            "rows": len(rows),
            "sessions": len(sessions),
            "total_tokens": total_tokens,
            "total_input": total_input,
            "total_output": total_output,
            "total_cache_read": total_cache_read,
            "total_cache_write": total_cache_write,
            "total_cost_usd": total_cost,
            "avg_cost_per_session": total_cost / len(sessions) if sessions else 0,
            "cache_hit_pct": (total_cache_read / (total_input + total_cache_read) * 100)
                              if (total_input + total_cache_read) > 0 else 0,
        },
    }


def build_agent_chart_data(by_agent: dict) -> tuple[list[str], list[dict], list[str], list[float]]:
    """按 agent 维度构造 chart 数据:横向 bar(token 分 input/output/cache) + cost 标注。"""
    keys = sorted(by_agent.keys(), key=lambda k: -by_agent[k]["cost"])
    labels = [AGENT_LABEL.get(k, k) for k in keys]
    colors = [AGENT_COLORS.get(k, DEFAULT_COLOR) for k in keys]

    datasets = [
        {
            "label": "input",
            "data": [by_agent[k]["input"] for k in keys],
            "backgroundColor": colors,
        },
        {
            "label": "cache_read",
            "data": [by_agent[k]["cache_read"] for k in keys],
            "backgroundColor": [c + "cc" for c in colors],  # 加透明度
        },
        {
            "label": "output",
            "data": [by_agent[k]["output"] for k in keys],
            "backgroundColor": [c + "88" for c in colors],
        },
    ]
    costs = [round(by_agent[k]["cost"], 4) for k in keys]
    return labels, datasets, keys, costs


def build_date_chart_data(by_date: dict) -> tuple[list[str], dict]:
    """按 date 维度构造 line chart 数据:input/output/cache_read/cache_write 四条线。"""
    keys = sorted(by_date.keys())
    return keys, {
        "input":       [by_date[k]["input"]       for k in keys],
        "output":      [by_date[k]["output"]      for k in keys],
        "cache_read":  [by_date[k]["cache_read"]  for k in keys],
        "cache_write": [by_date[k]["cache_write"] for k in keys],
        "cost":        [round(by_date[k]["cost"], 4) for k in keys],
        "sessions":    [by_date[k]["sessions"]    for k in keys],
    }


def fmt_int(n: int) -> str:
    """1234567 → '1.2M' / '123K' / '456' """
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_cost(c: float) -> str:
    if c == 0:
        return "$0"
    if c < 0.01:
        return f"${c*100:.2f}¢"
    return f"${c:.2f}"


def build_html(agg: dict, today: str) -> str:
    kpi = agg["kpi"]
    by_agent = agg["by_agent"]
    by_model = agg["by_model"]
    by_date = agg["by_date"]

    # 按 agent chart
    agent_labels, agent_datasets, agent_keys, agent_costs = build_agent_chart_data(by_agent)
    # 按 model chart(简化:bar 显示 cost)
    model_keys = sorted(by_model.keys(), key=lambda k: -by_model[k]["cost"])
    model_labels = model_keys
    model_costs = [round(by_model[k]["cost"], 4) for k in model_keys]
    model_tokens = [by_model[k]["total"] for k in model_keys]
    model_colors = [MODEL_COLORS.get(k, DEFAULT_COLOR) for k in model_keys]
    # 按 date chart
    date_keys, date_data = build_date_chart_data(by_date)

    # 详情表行(按 cost 降序)
    detail_rows = []
    all_rows = []
    for agent, b in by_agent.items():
        for _ in range(b["sessions"]):  # sessions 是 count,需要回原数据找
            pass
    # 简化:直接从原 rows 取所有,按 cost 降序
    raw_rows = sorted(load_rows(), key=lambda r: -r["cost_usd"])
    for r in raw_rows[:20]:
        agent_color = AGENT_COLORS.get(r["agent"], DEFAULT_COLOR)
        detail_rows.append(f"""          <tr>
            <td style="font-family: ui-monospace, monospace; font-size: 11px;">{r['timestamp'][:19]}</td>
            <td style="font-family: ui-monospace, monospace; font-size: 11px;">{r['session_id'][:24]}{'…' if len(r['session_id']) > 24 else ''}</td>
            <td><span class="badge" style="background: {agent_color}22; color: {agent_color};">{AGENT_LABEL.get(r['agent'], r['agent']) or '(unknown)'}</span></td>
            <td style="font-family: ui-monospace, monospace; font-size: 11px;">{r['model']}</td>
            <td style="text-align: right;">{fmt_int(r['input_tokens'])}</td>
            <td style="text-align: right;">{fmt_int(r['output_tokens'])}</td>
            <td style="text-align: right;">{fmt_int(r['cache_read_tokens'])}</td>
            <td style="text-align: right; font-weight: 600;">{fmt_int(r['total_tokens'])}</td>
            <td style="text-align: right; font-weight: 600;">{fmt_cost(r['cost_usd'])}</td>
          </tr>""")
    detail_rows_str = "\n".join(detail_rows)

    # Cache 命中率
    cache_pct = kpi['cache_hit_pct']

    # 注释:narrative
    if kpi["sessions"] <= 2:
        narrative = "样本太少(≤2 sessions),趋势与成本占比仅供参考。"
    else:
        # 找出最大一笔
        max_session = raw_rows[0] if raw_rows else None
        if max_session:
            narrative = (
                f"最大单笔 {fmt_cost(max_session['cost_usd'])} ({AGENT_LABEL.get(max_session['agent'], max_session['agent']) or 'unknown'} / {max_session['model']}) "
                f"占 {max_session['cost_usd']/kpi['total_cost_usd']*100:.1f}%;"
            )
        else:
            narrative = ""

    # 拼 JSON 数据
    agent_chart_json = json.dumps({
        "labels": agent_labels,
        "datasets": agent_datasets,
        "costs": agent_costs,
        "keys": agent_keys,
    }, ensure_ascii=False)

    model_chart_json = json.dumps({
        "labels": model_labels,
        "costs": model_costs,
        "tokens": model_tokens,
        "colors": model_colors,
    }, ensure_ascii=False)

    date_chart_json = json.dumps({
        "labels": date_keys,
        "data": date_data,
    }, ensure_ascii=False)

    return (HTML_TEMPLATE
        .replace("__TODAY__", today)
        .replace("__N_SESSIONS__", str(kpi["sessions"]))
        .replace("__N_ROWS__", str(kpi["rows"]))
        .replace("__TOTAL_TOKENS__", fmt_int(kpi["total_tokens"]))
        .replace("__TOTAL_COST__", f"${kpi['total_cost_usd']:.2f}")
        .replace("__AVG_COST__", f"${kpi['avg_cost_per_session']:.2f}")
        .replace("__CACHE_PCT__", f"{cache_pct:.1f}%")
        .replace("__MAX_COST__", f"${raw_rows[0]['cost_usd']:.2f}" if raw_rows else "$0")
        .replace("__NARRATIVE__", narrative)
        .replace("__AGENT_CHART_JSON__", agent_chart_json)
        .replace("__MODEL_CHART_JSON__", model_chart_json)
        .replace("__DATE_CHART_JSON__", date_chart_json)
        .replace("__DETAIL_ROWS__", detail_rows_str)
    )


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PCC Token 用量 Dashboard · __N_SESSIONS__ sessions (__TODAY__)</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
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
    .container { max-width: 1200px; margin: 0 auto; }
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
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>PCC Token 用量 Dashboard · __N_SESSIONS__ sessions</h1>
      <div class="subtitle">
        数据源 <code style="background:rgba(255,255,255,0.18);padding:2px 6px;border-radius:3px;">token-usage.csv</code> ·
        __N_ROWS__ 行 · 自动生成于 __TODAY__ ·
        风格参照 <code style="background:rgba(255,255,255,0.18);padding:2px 6px;border-radius:3px;">trending-chart</code>
      </div>
      <div class="kpi-row">
        <div class="kpi"><div class="kpi-label">总费用</div><div class="kpi-value">__TOTAL_COST__</div><div class="kpi-sub">MiniMax M3 公开 API 价估算</div></div>
        <div class="kpi"><div class="kpi-label">总 tokens</div><div class="kpi-value">__TOTAL_TOKENS__</div><div class="kpi-sub">含 cache_read</div></div>
        <div class="kpi"><div class="kpi-label">Sessions</div><div class="kpi-value">__N_SESSIONS__</div><div class="kpi-sub">unique</div></div>
        <div class="kpi"><div class="kpi-label">平均 / session</div><div class="kpi-value">__AVG_COST__</div><div class="kpi-sub">cost / session</div></div>
        <div class="kpi"><div class="kpi-label">Cache 命中率</div><div class="kpi-value">__CACHE_PCT__</div><div class="kpi-sub">cache_read / (input+cache_read)</div></div>
        <div class="kpi"><div class="kpi-label">最大单笔</div><div class="kpi-value">__MAX_COST__</div><div class="kpi-sub">cost / single session</div></div>
      </div>
    </header>

    <div class="card">
      <h2>① 按 Agent 分桶</h2>
      <p class="desc">每个 agent 累计的 token 构成(input / cache_read / output)+ 估算费用。颜色标识 agent 类型。</p>
      <div class="chart-wrap"><canvas id="agentChart"></canvas></div>
      <div class="pricing-note">
        <strong>解读:</strong>__NARRATIVE__
        蓝色系 = pcc 三件套(陪练 / 评估 / 追踪);橙色 = 三方校准 DeepSeek。
        费用仅 MiniMax M3 公开 API 价估算 + DeepSeek V4 Flash 公开 API 价;实际 MiniMax / DeepSeek 平台账单可能不同(取决于订阅优惠)。
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h2>② 按 Model 占比</h2>
        <p class="desc">各 model 的费用占比与 token 占比。</p>
        <div class="chart-wrap short"><canvas id="modelChart"></canvas></div>
      </div>
      <div class="card">
        <h2>③ 按 Date 趋势</h2>
        <p class="desc">每天的 token 构成(input / output / cache_read)+ 累计 sessions 数。</p>
        <div class="chart-wrap short"><canvas id="dateChart"></canvas></div>
      </div>
    </div>

    <div class="card">
      <h2>④ 每 session 详情(按 cost 降序)</h2>
      <p class="desc">__N_ROWS__ 行数据,只显示前 20 行(点击列头排序见浏览器)。</p>
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>session_id</th>
            <th>agent</th>
            <th>model</th>
            <th class="r">input</th>
            <th class="r">output</th>
            <th class="r">cache_read</th>
            <th class="r">total</th>
            <th class="r">cost</th>
          </tr>
        </thead>
        <tbody>
__DETAIL_ROWS__
        </tbody>
      </table>
    </div>

    <footer>
      数据来源: <code>observability/token-usage.csv</code> · 定价表 <code>scripts/calc_token_cost.py</code> ·
      Stop hook <code>scripts/hook_token_usage.py</code> · 生成于 __TODAY__
    </footer>
  </div>

  <script>
    const agentData = __AGENT_CHART_JSON__;
    const modelData = __MODEL_CHART_JSON__;
    const dateData  = __DATE_CHART_JSON__;

    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    Chart.defaults.color = '#5b6473';

    // ===== ① 按 Agent 横向 stacked bar =====
    new Chart(document.getElementById('agentChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: agentData.labels,
        datasets: agentData.datasets.map((d, i) => ({
          ...d,
          borderRadius: 4,
          borderSkipped: false,
          stack: 'tokens',
        })),
      },
      options: {
        indexAxis: 'y',
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, padding: 12 } },
          tooltip: {
            backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12,
            callbacks: {
              label: (ctx) => {
                const v = ctx.parsed.x;
                return `${ctx.dataset.label}: ${v >= 1000 ? (v/1000).toFixed(1) + 'K' : v}`;
              },
              footer: (items) => {
                const idx = items[0].dataIndex;
                return [
                  `─────`,
                  `cost: $${agentData.costs[idx].toFixed(4)}`,
                  `sessions: ${agentData.keys.length}`,
                ].join("\\n");
              },
            },
          },
        },
        scales: {
          x: { stacked: true, beginAtZero: true, ticks: { callback: (v) => v >= 1000 ? (v/1000) + 'K' : v }, grid: { color: '#eef0f4' } },
          y: { stacked: true, grid: { display: false } },
        },
      },
    });

    // ===== ② 按 Model bar(cost) =====
    new Chart(document.getElementById('modelChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: modelData.labels,
        datasets: [{
          label: 'cost (USD)',
          data: modelData.costs,
          backgroundColor: modelData.colors,
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
                  `cost: $${modelData.costs[i].toFixed(4)}`,
                  `tokens: ${modelData.tokens[i].toLocaleString()}`,
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

    // ===== ③ 按 Date line chart =====
    new Chart(document.getElementById('dateChart').getContext('2d'), {
      type: 'line',
      data: {
        labels: dateData.labels,
        datasets: [
          { label: 'input',       data: dateData.data.input,       borderColor: '#2b6cb0', backgroundColor: 'rgba(43,108,176,0.08)', borderWidth: 2.5, tension: 0.25, pointRadius: 5, pointHoverRadius: 7, fill: false },
          { label: 'cache_read',  data: dateData.data.cache_read,  borderColor: '#76b7b2', backgroundColor: 'rgba(118,183,178,0.08)', borderWidth: 2.5, tension: 0.25, pointRadius: 5, pointHoverRadius: 7, fill: false },
          { label: 'output',      data: dateData.data.output,      borderColor: '#f28e2b', backgroundColor: 'rgba(242,142,43,0.08)',  borderWidth: 2.5, tension: 0.25, pointRadius: 5, pointHoverRadius: 7, fill: false },
          { label: 'cache_write', data: dateData.data.cache_write, borderColor: '#e15759', backgroundColor: 'rgba(225,87,89,0.08)',  borderWidth: 2.5, tension: 0.25, pointRadius: 5, pointHoverRadius: 7, fill: false },
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
                const v = ctx.parsed.y;
                return `${ctx.dataset.label}: ${v >= 1000 ? (v/1000).toFixed(1) + 'K' : v}`;
              },
              footer: (items) => {
                const idx = items[0].dataIndex;
                return [
                  `─────`,
                  `cost: $${dateData.data.cost[idx].toFixed(4)}`,
                  `sessions: ${dateData.data.sessions[idx]}`,
                ].join("\\n");
              },
            },
          },
        },
        scales: {
          y: { beginAtZero: true, ticks: { callback: (v) => v >= 1000 ? (v/1000) + 'K' : v }, grid: { color: '#eef0f4' } },
          x: { grid: { display: false } },
        },
      },
    });
  </script>
</body>
</html>
"""


def main() -> int:
    rows = load_rows()
    if not rows:
        print(f"ERROR: {CSV} 无数据", file=sys.stderr)
        return 1
    agg = aggregate(rows)
    today = datetime.now().strftime("%Y-%m-%d")
    out = PROGRESS / f"token-usage-dashboard-{today}.html"
    html = build_html(agg, today)
    out.write_text(html, encoding="utf-8")
    kpi = agg["kpi"]
    print(f"✅ HTML 已生成:{out}")
    print(f"   sessions: {kpi['sessions']} · rows: {kpi['rows']}")
    print(f"   total tokens: {kpi['total_tokens']:,} · total cost: ${kpi['total_cost_usd']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
