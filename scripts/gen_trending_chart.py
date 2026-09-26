#!/usr/bin/env python3
"""gen_trending_chart.py — 从 tracker.csv 自动生成 trending chart HTML。

读取 progress/tracker.csv (91 列),按 (conversation_date, conversation_time) 排序,
输出 progress/trending-chart-{date}.html。

调用:
  - 手动:python3 scripts/gen_trending_chart.py
  - pcc-tracker 追加新行后自动调用(更新 agent prompt 后)
  - PostToolUse hook 在 tracker.csv 写入后自动触发

输出 HTML:
  - 自包含,浏览器双击可看(无服务器)
  - 4 个图表:① 命中率走势 ② ✔/△/✘ 堆叠 ③ 能力雷达 ④ 详情表
  - 数据内嵌在 <script> 块(JSON)
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "progress" / "tracker.csv"
PROGRESS = ROOT / "progress"

PERSONA_COLORS = {
    "vec-01": "#4e79a7",
    "vec-02": "#f28e2b",
    "vec-06": "#e15759",
    "vec-07": "#76b7b2",
    "vec-08": "#59a14f",
}

DIFF_LABEL = {1: "1 易", 2: "2 中", 3: "3 难"}
DIFF_CLASS = {1: "diff-1", 2: "diff-2", 3: "diff-3"}

PERSONA_LABEL = {
    "vec-01": "vec-01 (难2)",
    "vec-02": "vec-02 (难3)",
    "vec-06": "vec-06 (难1)",
    "vec-07": "vec-07 (难2)",
    "vec-08": "vec-08 (难1)",
}


def load_sessions() -> list[dict]:
    """读 tracker.csv,排序,返回 sessions dict 列表。"""
    with CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    rows.sort(
        key=lambda r: (
            r.get("conversation_date", "") or r.get("date", ""),
            r.get("conversation_time", ""),
        )
    )

    sessions = []
    for r in rows:
        yes = int(r["claude_total_✔"])
        part = int(r["claude_total_△"])
        no = int(r["claude_total_✘"])
        hit = round((yes + 0.5 * part) / 37 * 100, 2)
        strict_hit = round(yes / 37 * 100, 2)
        sid = r["session_id"]
        # short_label = e.g. "vec-06 s01"
        parts = sid.split("-")
        # session-NN 拆出来
        last = parts[-1]
        persona_short = "-".join(parts[:2])  # vec-XX
        sessions.append(
            {
                "sid": sid,
                "conv_date": r["conversation_date"],
                "conv_time": r.get("conversation_time", ""),
                "date": r["date"],
                "reeval_of": r.get("reeval_of", ""),
                "persona": r["persona"],
                "diff": int(r["difficulty"]),
                "diff_label": DIFF_LABEL[int(r["difficulty"])],
                "diff_class": DIFF_CLASS[int(r["difficulty"])],
                "hit": hit,
                "hit_strict": strict_hit,
                "good": yes,
                "part": part,
                "fail": no,
                "mustHit": int(r["must_hit_✘_count"]),
                "short_label": f"{persona_short} s{last}",
                "color": PERSONA_COLORS.get(r["persona"], "#999"),
                "eval_version": r.get("eval_version", "").strip(),
                "pcc_pass": int(r["pcc_pass_pct"]) if r.get("pcc_pass_pct", "").strip() else None,
            }
        )
    return sessions


def filter_sessions_by_kb(sessions: list[dict], kb_version: str) -> list[dict]:
    """按 KB 版本切片过滤。

    - 'current' → 最新 v4.1.x 家族(v4.1.0/1/2/3/6)
    - 'all' → 全部
    - 其它字符串 → 精确匹配(如 'v4.1.6' / 'v3')
    """
    if kb_version == "all":
        return sessions
    if kb_version == "current":
        return [s for s in sessions if s.get("eval_version", "").startswith("v4.1.")]
    return [s for s in sessions if s.get("eval_version", "") == kb_version]


def is_outlier(session: dict, threshold: float = 60.0) -> bool:
    """严格率 < threshold% 的场次视为 outlier"""
    return session.get("hit_strict", 100) < threshold


def competency_stats(sessions: list[dict]) -> list[tuple[str, float]]:
    """简化版能力维度命中率(基于总判定数 9 场 ×每能力 marker 数)。

    注:目前用 claude_total_✔/△/✘ 加权推算,如需精确可调用 analyze_tracker.py 的
    competency_stats。这里只生成 chart 的近似值。
    """
    # 从已有 analyze_tracker 输出读,这里 fallback 用一个简单的硬编码
    # 因为 CSV 里没存 per-competency 命中率(analyze_tracker.py 现算现用)
    # 改成从 tracker-analysis-{date}.md 解析
    today = datetime.now().strftime("%Y-%m-%d")
    candidates = sorted(PROGRESS.glob("tracker-analysis-*.md"), reverse=True)
    if not candidates:
        return [
            ("能力 3 建立协议", 75.0),
            ("能力 4 信任亲近", 63.9),
            ("能力 5 教练意识", 85.6),
            ("能力 6 积极聆听", 90.5),
            ("能力 7 唤起觉察", 88.2),
            ("能力 8 促进成长", 46.3),
        ]
    # 解析最新分析
    text = candidates[0].read_text(encoding="utf-8")
    out = []
    for line in text.splitlines():
        # | 能力 X | ✔ | △ | ✘ | 总 | **XX.X%** |
        if line.startswith("| 能力") and "**" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6:
                name = cells[0]
                rate_str = cells[5].replace("**", "").replace("%", "")
                try:
                    out.append((name, float(rate_str)))
                except ValueError:
                    pass
    return out


def build_html(sessions: list[dict], today: str) -> str:
    n = len(sessions)
    hits = [s["hit"] for s in sessions]
    avg = sum(s["hit_strict"] for s in sessions) / n if n else 0
    n_outliers = sum(1 for s in sessions if is_outlier(s))

    # KPI 计算
    peak = max(sessions, key=lambda s: s["hit"]) if sessions else None
    trough = min(sessions, key=lambda s: s["hit"]) if sessions else None

    # 构造 sessions JSON
    sessions_json = json.dumps(
        [
            {
                **s,
                # 给 Chart.js 的复合字段
                "label_short": f"{s['conv_date'][-5:]}\n{s['short_label']}",
            }
            for s in sessions
        ],
        ensure_ascii=False,
    )

    persona_legend = "\n      ".join(
        f'<span><span class="dot" style="background: {PERSONA_COLORS[p]};"></span>{PERSONA_LABEL[p]}</span>'
        for p in ["vec-01", "vec-02", "vec-06", "vec-07", "vec-08"]
        if any(s["persona"] == p for s in sessions)
    )

    # 详情表行
    table_rows = []
    for i, s in enumerate(sessions, 1):
        is_reeval = bool(s["reeval_of"])
        is_outl = is_outlier(s)
        bg_parts = []
        if is_reeval:
            bg_parts.append("background: #fff8e6;")
        row_class = ' class="outlier-row"' if is_outl else ""
        bg = f' style="{" ".join(bg_parts)}"' if bg_parts else ""
        bar_color = (
            "background: linear-gradient(90deg, #c53030, #f56565);"
            if s["hit_strict"] < 50
            else "background: linear-gradient(90deg, #2f855a, #48bb78);"
            if s["hit_strict"] >= 90
            else ""
        )
        bar_html = f'<div class="score-bar"><span style="width: {s["hit_strict"]}%; {bar_color}"></span></div>'
        strong = "<strong>" + f'{s["hit_strict"]:.2f}%' + "</strong>" if s["hit_strict"] >= 85 or s["hit_strict"] < 50 else f'{s["hit_strict"]:.2f}%'
        session_id_note = (
            f"{s['date']} (但记作 {s['date']})" if is_reeval and s["date"] != s["conv_date"] else s["date"]
        )
        if is_reeval:
            session_id_note = f"{s['conv_date']} (但记作 {s['date']})"
        else:
            session_id_note = s["date"]
        time_str = f"{s['conv_date'][-5:]} <strong>{s['conv_time']}</strong>" if s["conv_time"] else s["conv_date"][-5:]
        outlier_flag = "⚠️ " if is_outlier(s) else ""
        eval_v = s.get("eval_version", "")
        eval_v_label = f' <span class="kb-tag">{eval_v}</span>' if eval_v else ""
        pcc = s.get("pcc_pass")
        if pcc is None:
            pcc_cell = '<span class="muted">—</span>'
            pcc_class = ""
        elif pcc < 50:
            pcc_cell = f'<span class="pcc-bad">{pcc}%</span>'
            pcc_class = "pcc-bad-row"
        elif pcc < 70:
            pcc_cell = f'<span class="pcc-warn">{pcc}%</span>'
            pcc_class = "pcc-warn-row"
        else:
            pcc_cell = f'<span class="pcc-good">{pcc}%</span>'
            pcc_class = ""
        # 严格高 + PCC 低 = misleading 标记
        misleading = " ⚠️" if s["hit_strict"] >= 85 and pcc is not None and pcc < 50 else ""
        pcc_class_full = f'{row_class.strip()} {pcc_class}'.strip()

        table_rows.append(
            f"""          <tr class="{pcc_class_full}"{bg}>
            <td>{i}</td>
            <td>{time_str}</td>
            <td>{outlier_flag}{session_id_note}{eval_v_label}</td>
            <td><span class="badge {s['persona']}">{s['persona']}</span></td>
            <td><span class="{s['diff_class']}">{s['diff_label']}</span></td>
            <td>{s['good']}</td><td>{s['part']}</td><td>{s['fail']}</td>
            <td>{s['mustHit']}</td>
            <td>{bar_html}{strong}</td>
            <td>{s['hit']:.2f}%</td>
            <td>{pcc_cell}{misleading}</td>
          </tr>"""
        )
    table_rows_str = "\n".join(table_rows)

    # KPI 卡片
    peak_html = f'<div class="kpi-value">{peak["hit_strict"]:.1f}%</div><div class="kpi-sub">{peak["short_label"]} (难 {peak["diff"]})</div>' if peak else ""
    trough_html = (
        f'<div class="kpi-value">{trough["hit_strict"]:.1f}%</div><div class="kpi-sub">{trough["short_label"]} ({trough["conv_date"]} {trough["conv_time"]})</div>'
        if trough
        else ""
    )

    # 雷达数据(从最新 tracker-analysis 解析)
    radar = competency_stats(sessions)
    radar_json = json.dumps([{"name": n, "rate": r} for n, r in radar])

    # narrative(按 n 变化)
    if n <= 3:
        narrative = "样本太少,趋势仅供参考。"
    elif sessions[0]["hit_strict"] < sessions[-1]["hit_strict"] - 10:
        narrative = f"整体上升:{sessions[0]['hit_strict']:.2f}% → {sessions[-1]['hit_strict']:.2f}%(+{sessions[-1]['hit_strict']-sessions[0]['hit_strict']:.1f}pp)"
    else:
        narrative = "波动期,稳定区间 ~70-93%。"

    html = HTML_TEMPLATE.format(
        n=n,
        today=today,
        avg=f"{avg:.1f}",
        peak_html=peak_html,
        trough_html=trough_html,
        persona_legend=persona_legend,
        table_rows=table_rows_str,
        sessions_json=sessions_json,
        radar_json=radar_json,
        narrative=narrative,
    )
    return html


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PCC 陪练趋势 · {n} 场数据 ({today})</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
  <style>
    :root {{
      --bg: #f7f8fb; --card: #ffffff; --border: #e5e8ef;
      --text: #1c2027; --muted: #5b6473; --accent: #2b6cb0;
      --good: #2f855a; --warn: #d97706; --bad: #c53030;
      --persona-1: #4e79a7; --persona-2: #f28e2b;
      --persona-6: #e15759; --persona-7: #76b7b2; --persona-8: #59a14f;
      --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      background: linear-gradient(135deg, #2b6cb0 0%, #4299e1 100%);
      color: white; padding: 28px 32px; border-radius: 14px;
      box-shadow: var(--shadow); margin-bottom: 24px;
    }}
    header h1 {{ margin: 0 0 8px 0; font-size: 26px; font-weight: 600; letter-spacing: -0.5px; }}
    header .subtitle {{ opacity: 0.9; font-size: 14px; margin-bottom: 18px; }}
    .kpi-row {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px;
    }}
    .kpi {{
      background: rgba(255,255,255,0.14); backdrop-filter: blur(8px);
      padding: 14px 16px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.18);
    }}
    .kpi-label {{ font-size: 12px; opacity: 0.85; margin-bottom: 4px; }}
    .kpi-value {{ font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }}
    .kpi-sub {{ font-size: 11px; opacity: 0.75; margin-top: 2px; }}
    .card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 24px; margin-bottom: 20px; box-shadow: var(--shadow);
    }}
    .card h2 {{ margin: 0 0 4px 0; font-size: 18px; font-weight: 600; }}
    .card .desc {{ color: var(--muted); font-size: 13px; margin-bottom: 18px; }}
    .chart-wrap {{ position: relative; height: 380px; }}
    .chart-wrap.tall {{ height: 460px; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    thead th {{
      text-align: left; padding: 10px 12px; background: #f1f4f7;
      font-weight: 600; color: var(--muted); border-bottom: 2px solid var(--border);
      font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
    }}
    tbody td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); }}
    tbody tr:hover {{ background: #fafbfd; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; font-family: ui-monospace, "SF Mono", monospace; }}
    .badge.vec-01 {{ background: #e6eef7; color: var(--persona-1); }}
    .badge.vec-02 {{ background: #fbecd9; color: var(--persona-2); }}
    .badge.vec-06 {{ background: #fadcdc; color: var(--persona-6); }}
    .badge.vec-07 {{ background: #dff0ed; color: var(--persona-7); }}
    .badge.vec-08 {{ background: #dfecdb; color: var(--persona-8); }}
    .kb-tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-family: ui-monospace, "SF Mono", monospace; background: #e6eef7; color: #2b6cb0; margin-left: 4px; }}
    .outlier-row {{ background: #fff5f5; }}
    .outlier-row:hover {{ background: #ffe8e8 !important; }}
    .pcc-good {{ color: var(--good); font-weight: 600; }}
    .pcc-warn {{ color: var(--warn); font-weight: 600; }}
    .pcc-bad {{ color: var(--bad); font-weight: 600; }}
    .pcc-bad-row {{ background: #fffafa; }}
    .pcc-bad-row:hover {{ background: #ffe8e8 !important; }}
    .pcc-warn-row {{ background: #fffbeb; }}
    .pcc-warn-row:hover {{ background: #fef3c7 !important; }}
    .muted {{ color: var(--muted); opacity: 0.6; }}
    .diff-1 {{ color: var(--good); font-weight: 600; }}
    .diff-2 {{ color: var(--warn); font-weight: 600; }}
    .diff-3 {{ color: var(--bad); font-weight: 600; }}
    .score-bar {{
      display: inline-block; width: 60px; height: 6px;
      background: #eef0f4; border-radius: 3px; overflow: hidden;
      vertical-align: middle; margin-right: 6px;
    }}
    .score-bar > span {{ display: block; height: 100%; background: linear-gradient(90deg, #2b6cb0, #4299e1); }}
    .legend-row {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; font-size: 13px; color: var(--muted); }}
    .legend-row .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }}
    .callout {{
      padding: 14px 16px; background: #fff8e6; border-left: 3px solid var(--warn);
      border-radius: 6px; font-size: 13px; color: #5b4406; margin-top: 12px;
    }}
    footer {{ margin-top: 32px; padding: 20px; text-align: center; font-size: 12px; color: var(--muted); }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>PCC 陪练趋势 · {n} 场数据</h1>
      <div class="subtitle">按 <strong>CSV 的 (conversation_date, conversation_time)</strong> 排序 · 浏览器双击可看 · 自动从 <code>tracker.csv</code> 生成</div>
      <div class="kpi-row">
        <div class="kpi"><div class="kpi-label">平均严格命中率</div><div class="kpi-value">{avg}%</div><div class="kpi-sub">{n} 场加权 · v4.1.0 主</div></div>
        <div class="kpi"><div class="kpi-label">最高分 (严格)</div>{peak_html}</div>
        <div class="kpi"><div class="kpi-label">最低分 (严格)</div>{trough_html}</div>
        <div class="kpi"><div class="kpi-label">场数</div><div class="kpi-value">{n}</div><div class="kpi-sub">unique 陪练</div></div>
        <div class="kpi"><div class="kpi-label">生成时间</div><div class="kpi-value" style="font-size:14px;">{today}</div><div class="kpi-sub">自动化</div></div>
      </div>
    </header>

    <div class="card">
      <h2>① 命中率走势</h2>
      <p class="desc">每场 PCC marker 命中率: 蓝实=严格 ✔/37(v4.1.x 主指标)· 蓝虚=复合 (✔+0.5×△)/37(辅)· 橙点线=PCC 通过概率(pass/fail 判定)· 灰虚=严格均值 · 折线点按 persona 着色 · <strong>严格高 + PCC 低 ⚠️</strong> = 必命中失守触发一票否决</p>
      <div class="chart-wrap tall"><canvas id="hitRateChart"></canvas></div>
      <div class="legend-row">{persona_legend}</div>
      <div class="callout"><strong>解读:</strong>{narrative}</div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h2>② 判定构成 (✔/△/✘)</h2>
        <p class="desc">每场 37 条 marker 的判定分布</p>
        <div class="chart-wrap"><canvas id="stackChart"></canvas></div>
      </div>
      <div class="card">
        <h2>③ 能力维度雷达</h2>
        <p class="desc">最新 tracker-analysis 中的能力维度命中率</p>
        <div class="chart-wrap"><canvas id="radarChart"></canvas></div>
      </div>
    </div>

    <div class="card">
      <h2>④ 每场详情(按 conversation_date + time)</h2>
      <p class="desc">{n} 场陪练的判定构成与最终得分</p>
      <table>
        <thead>
          <tr><th>#</th><th>实际时间</th><th>session_id 日期</th><th>Persona</th><th>难度</th><th>✔</th><th>△</th><th>✘</th><th>必命中✘</th><th>严格 (主·v4.1.0)</th><th>复合 (辅)</th><th>PCC 通过概率</th></tr>
        </thead>
        <tbody>
{table_rows}
        </tbody>
      </table>
    </div>

    <footer>
      数据来源: <code>progress/tracker.csv</code> ({n} 行, 91 列) · 自动生成脚本 <code>scripts/gen_trending_chart.py</code> · 生成于 {today}
    </footer>
  </div>

  <script>
    // ===== 自动从 gen_trending_chart.py 注入 =====
    const sessions = {sessions_json};
    const radarData = {radar_json};

    const personaColors = {{
      'vec-01': '#4e79a7', 'vec-02': '#f28e2b',
      'vec-06': '#e15759', 'vec-07': '#76b7b2', 'vec-08': '#59a14f'
    }};

    const labels = sessions.map(s => s.label_short);
    const hits = sessions.map(s => s.hit);
    const strictHits = sessions.map(s => s.hit_strict);
    const pccPasses = sessions.map(s => (s.pcc_pass === null || s.pcc_pass === undefined) ? null : s.pcc_pass);
    const personaFills = sessions.map(s => personaColors[s.persona]);

    // KB 版本边框色映射(默认按 v4.1.x 蓝,旧版本用暗灰区分;outlier 红色边框)
    const KB_BORDER = {{
      'v4.1.0': '#2b6cb0', 'v4.1.1': '#2b6cb0', 'v4.1.2': '#2b6cb0',
      'v4.1.3': '#2b6cb0', 'v4.1.6': '#2b6cb0',
      'v1': '#999', 'v2': '#888', 'v2.5': '#777', 'v3': '#666',
      'v3 / 2026-08-30': '#555',
    }};
    const pointBorders = sessions.map(s => {{
      if ((s.hit_strict || 0) < 60) return '#e53e3e';  // outlier red
      return KB_BORDER[s.eval_version] || '#2b6cb0';
    }});
    const pointBorderWidths = sessions.map(s => (s.hit_strict || 0) < 60 ? 3.5 : 2);

    const mean = hits.reduce((a, b) => a + b, 0) / hits.length;
    const strictMean = strictHits.reduce((a, b) => a + b, 0) / strictHits.length;

    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    Chart.defaults.color = '#5b6473';

    new Chart(document.getElementById('hitRateChart').getContext('2d'), {{
      type: 'line',
      data: {{
        labels: labels,
        datasets: [
          {{
            label: '严格命中率(主·v4.1.x 默认)',
            data: strictHits,
            borderColor: '#2b6cb0',
            backgroundColor: 'rgba(43, 108, 176, 0.08)',
            borderWidth: 2.5, tension: 0.25,
            pointRadius: 7, pointHoverRadius: 9,
            pointBackgroundColor: personaFills,
            pointBorderColor: pointBorders,
            pointBorderWidth: pointBorderWidths,
            fill: true,
          }},
          {{
            label: '复合命中率(辅·历史口径)',
            data: hits,
            borderColor: '#2b6cb0',
            backgroundColor: 'rgba(43, 108, 176, 0.03)',
            borderWidth: 1.8, tension: 0.25,
            pointRadius: 4, pointHoverRadius: 6,
            pointBackgroundColor: '#2b6cb0',
            pointBorderColor: '#fff', pointBorderWidth: 1.5,
            fill: false,
            borderDash: [6, 4],
          }},
          {{
            label: 'PCC 通过概率(主·pass/fail 判定)',
            data: pccPasses,
            borderColor: '#d97706',
            backgroundColor: 'rgba(217, 119, 6, 0.05)',
            borderWidth: 2.2, tension: 0.25,
            pointRadius: 6, pointHoverRadius: 8,
            // 按 pass prob 着色:≥70% 绿,<50% 红,其他 橙
            pointBackgroundColor: sessions.map(s => {{
              const p = s.pcc_pass;
              if (p === null || p === undefined) return '#bbb';
              if (p >= 70) return '#48bb78';
              if (p < 50) return '#fc8181';
              return '#f6ad55';
            }}),
            pointBorderColor: sessions.map(s => {{
              const p = s.pcc_pass;
              if (p === null || p === undefined) return '#999';
              if (p >= 70) return '#2f855a';
              if (p < 50) return '#c53030';
              return '#d97706';
            }}),
            pointBorderWidth: 1.5,
            fill: false,
            borderDash: [2, 2],
            spanGaps: true,
          }},
        ],
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ display: true, position: 'top', labels: {{ boxWidth: 14, padding: 12, font: {{ size: 12 }} }} }},
          tooltip: {{
            backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12,
            callbacks: {{
              label: (ctx) => {{
                const s = sessions[ctx.dataIndex];
                const lbl = ctx.dataset.label;
                if (lbl.indexOf('PCC') !== -1) {{
                  const p = s.pcc_pass;
                  const pStr = (p === null || p === undefined) ? '—(无 HTML 报告)' : p + '%';
                  const flag = (s.hit_strict >= 85 && p !== null && p < 50) ? ' ⚠️ 严格高 + PCC 低(misleading)' : '';
                  return [
                    'PCC 通过概率: ' + pStr + flag,
                    '严格命中率: ' + s.hit_strict.toFixed(2) + '%(供对比)',
                  ];
                }}
                const isStrict = lbl.indexOf('严格') !== -1;
                const tag = isStrict ? '严格' : '复合';
                const num = (isStrict ? s.hit_strict : s.hit).toFixed(2);
                const diff = (s.hit - s.hit_strict).toFixed(2);
                return [
                  '实际: ' + s.conv_date + ' ' + s.conv_time,
                  tag + ': ' + num + '%',
                  '复-严差值: ' + diff + 'pp',
                  '✔ ' + s.good + ' · △ ' + s.part + ' · ✘ ' + s.fail,
                  '必命中✘: ' + s.mustHit,
                  s.reeval_of ? '⚠️ reeval of ' + s.reeval_of : ''
                ].filter(Boolean);
              }},
            }},
          }},
          annotation: {{
            annotations: {{
              meanLine: {{
                type: 'line', yMin: strictMean, yMax: strictMean,
                borderColor: 'rgba(113, 128, 150, 0.55)',
                borderWidth: 1.5, borderDash: [6, 4],
                label: {{
                  display: true, content: `严格均值 ${{strictMean.toFixed(1)}}%`,
                  position: 'end',
                  backgroundColor: 'rgba(113, 128, 150, 0.95)',
                  color: '#fff', font: {{ size: 11, weight: '600' }}, padding: 4,
                }},
              }},
            }},
          }},
        }},
        scales: {{
          y: {{ beginAtZero: false, min: 35, max: 100,
                ticks: {{ callback: (v) => v + '%' }}, grid: {{ color: '#eef0f4' }} }},
          x: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }},
        }},
      }},
    }});

    new Chart(document.getElementById('stackChart').getContext('2d'), {{
      type: 'bar',
      data: {{
        labels: labels,
        datasets: [
          {{ label: '✔', data: sessions.map(s => s.good), backgroundColor: '#48bb78', borderRadius: 4, stack: 's' }},
          {{ label: '△', data: sessions.map(s => s.part), backgroundColor: '#f6ad55', borderRadius: 4, stack: 's' }},
          {{ label: '✘', data: sessions.map(s => s.fail), backgroundColor: '#fc8181', borderRadius: 4, stack: 's' }},
        ],
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'top', labels: {{ boxWidth: 12, padding: 12 }} }},
          tooltip: {{
            backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12,
            callbacks: {{
              footer: (items) => items.reduce((sum, i) => sum + i.parsed.y, 0) + ' / 37',
            }},
          }},
        }},
        scales: {{
          y: {{ beginAtZero: true, max: 37, ticks: {{ stepSize: 5 }}, grid: {{ color: '#eef0f4' }} }},
          x: {{ stacked: true, grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }} }} }},
        }},
      }},
    }});

    new Chart(document.getElementById('radarChart').getContext('2d'), {{
      type: 'radar',
      data: {{
        labels: radarData.map(r => r.name),
        datasets: [
          {{ label: '当前命中率',
            data: radarData.map(r => r.rate),
            fill: true, backgroundColor: 'rgba(43, 108, 176, 0.18)',
            borderColor: '#2b6cb0', borderWidth: 2,
            pointBackgroundColor: '#2b6cb0', pointRadius: 4 }},
        ],
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'top', labels: {{ boxWidth: 12, padding: 12 }} }},
          tooltip: {{ backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12 }},
        }},
        scales: {{
          r: {{
            beginAtZero: true, max: 100,
            ticks: {{ stepSize: 20, callback: (v) => v + '%', backdropColor: 'transparent', font: {{ size: 10 }} }},
            pointLabels: {{ font: {{ size: 12 }} }}, grid: {{ color: '#eef0f4' }},
          }},
        }},
      }},
    }});
  </script>
</body>
</html>
"""


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="生成 trending chart HTML")
    parser.add_argument(
        "--kb-version",
        default="all",
        help="KB 版本切片:'all'(默认 = 全量 31 场)/ 'current'(v4.1.x)/ 精确版本(如 v4.1.6)",
    )
    parser.add_argument("--out", type=Path, default=None, help="输出 HTML 路径(默认按 KB 切片自动命名)")
    parser.add_argument("--print-summary", action="store_true", help="打印切片摘要到 stdout")
    args = parser.parse_args()

    if not CSV.exists():
        print(f"ERROR: tracker.csv 不存在:{CSV}", file=sys.stderr)
        return 1
    sessions_all = load_sessions()
    if not sessions_all:
        print("ERROR: tracker.csv 没有数据行", file=sys.stderr)
        return 1
    sessions = filter_sessions_by_kb(sessions_all, args.kb_version)
    if not sessions:
        print(
            f"ERROR: KB slice '{args.kb_version}' 没有匹配到任何场次(csv 全量 {len(sessions_all)} 场)",
            file=sys.stderr,
        )
        return 1
    today = datetime.now().strftime("%Y-%m-%d")
    if args.out:
        out = args.out
    elif args.kb_version == "all":
        out = PROGRESS / "trending-chart.html"
    elif args.kb_version == "current":
        out = PROGRESS / "trending-chart-v4.1.x.html"
    else:
        safe_v = args.kb_version.replace("/", "-").replace(" ", "-")
        out = PROGRESS / f"trending-chart-{safe_v}.html"
    html = build_html(sessions, today)
    out.write_text(html, encoding="utf-8")
    avg = sum(s["hit_strict"] for s in sessions) / len(sessions)
    n_outliers = sum(1 for s in sessions if is_outlier(s))
    print(f"✅ HTML 已生成:{out}")
    print(f"   场数:{len(sessions)} · 严格平均 {avg:.1f}% · outlier {n_outliers} 场 · KB={args.kb_version} / 全量 {len(sessions_all)} 场")
    print(f"   排序:(conversation_date, conversation_time)")
    print(f"\n  💡 后续维护:")
    print(f"     python3 scripts/gen_trending_chart.py                       # 默认全量(31 场)")
    print(f"     python3 scripts/gen_trending_chart.py --kb-version current # v4.1.x 切片(15 场)")
    print(f"     python3 scripts/gen_trending_chart.py --kb-version v4.1.6  # 精确版本(3 场)")
    return 0


if __name__ == "__main__":
    sys.exit(main())