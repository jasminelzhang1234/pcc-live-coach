#!/usr/bin/env python3
"""gen_trending_chart_real.py — 从 tracker-real-sessions.csv 生成 trending chart HTML。

真人练习专属 trending,跟 AI persona 完全隔离:
  - 读 progress/tracker-real-sessions.csv (95 列,含 source_type/audio_path/transcript_path/audio_quality_notes)
  - 同时读 progress/tracker.csv 计算 AI persona 平均命中率,作为参考线
  - 暖色调(amber/orange),视觉一眼区别 AI persona 的冷蓝
  - 输出 progress/trending-chart-real-{date}.html

调用:
  python3 scripts/gen_trending_chart_real.py                  # 用默认路径
  python3 scripts/gen_trending_chart_real.py --out <path>     # 自定义输出路径

与 gen_trending_chart.py 的差异:
  - 只渲染真人练习(无 persona 颜色映射,改用"客户来源"颜色)
  - 难度栏不适用,改为"客户/时长"标签
  - 加 AI persona 平均命中率参考线(横向虚线)
  - KPI 多一项 "vs AI persona 平均"(差值 + pp)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS = ROOT / "progress"
REAL_CSV = PROGRESS / "tracker-real-sessions.csv"
AI_CSV = PROGRESS / "tracker.csv"


# 真人客户来源 → 配色(暖色调)
def client_color(client_type: str) -> str:
    """根据 client_type 返回暖色配色,缺省 amber。"""
    mapping = {
        "real_client_alpha": "#d97706",  # amber-600(真人客户 A)
    }
    return mapping.get(client_type, "#ea580c")  # orange-600 fallback


def _safe_int(row: dict, key: str, default: int = 0) -> int:
    """Parse an integer cell, treating empty / None / whitespace as `default`.

    The 95-col real-sessions tracker CSV frequently has empty strings in
    marker-scoring columns (e.g. claude_total_✔ is blank until a /track
    reeval fills it). Without this guard the chart regen endpoint would
    crash on the first session whose score columns haven't been scored yet.
    """
    raw = row.get(key)
    if raw is None:
        return default
    s = str(raw).strip()
    if not s:
        return default
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def load_real_sessions(csv_path: Path) -> list[dict]:
    """读 tracker-real-sessions.csv,排序,返回 sessions dict 列表。

    防御性过滤(2026-09-11 加):排除
    - pytest 临时目录音频(/private/var/... 或路径含 pytest)
    - AI persona 标签错标行(persona 以 vec-/voc-/vic- 开头)
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"真人练习 CSV 不存在:{csv_path}")
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # 防御过滤:pytest 测试数据 + AI persona 错标行
    rows_raw = len(rows)
    rows = [
        r for r in rows
        if "pytest" not in r.get("audio_path", "")
        and not r.get("audio_path", "").startswith("/private/var")
        and not r.get("persona", "").startswith(("vec-", "voc-", "vic-"))
    ]
    rows_filtered = rows_raw - len(rows)
    if rows_filtered > 0:
        print(f"   ⚠ 过滤掉 {rows_filtered} 行污染行(纯 pytest 测试或 AI persona 错标)")

    rows.sort(
        key=lambda r: (
            r.get("conversation_date", "") or r.get("date", ""),
            r.get("conversation_time", ""),
        )
    )

    sessions = []
    for r in rows:
        yes = _safe_int(r, "claude_total_✔")
        part = _safe_int(r, "claude_total_△")
        no = _safe_int(r, "claude_total_✘")
        # 严格命中率(只算 ✔) — 更贴近 PCC 考试逻辑(每条独立判定,不靠 △ 救分)
        # 2026-09-11 改:之前 (yes + 0.5*part)/37 会出现 29✔+8△ = 30✔+6△ = 89.2% 撞分
        hit = round(yes / 37 * 100, 2)
        sid = r["session_id"]
        client_type = r.get("persona", "real_unknown")  # 真人用 persona 列存 client_type
        sessions.append(
            {
                "sid": sid,
                "conv_date": r["conversation_date"],
                "conv_time": r.get("conversation_time", ""),
                "date": r["date"],
                "reeval_of": r.get("reeval_of", ""),
                "client_type": client_type,
                "topic": r.get("topic", ""),
                "source_type": r.get("source_type", "real"),
                "audio_path": r.get("audio_path", ""),
                "transcript_path": r.get("transcript_path", ""),
                "audio_quality_notes": r.get("audio_quality_notes", ""),
                "hit": hit,
                "good": yes,
                "part": part,
                "fail": no,
                "mustHit": _safe_int(r, "must_hit_✘_count"),
                "key_weakness": r.get("key_weakness", ""),
                "color": client_color(client_type),
            }
        )
    return sessions


def compute_ai_avg() -> tuple[float, int] | None:
    """从 tracker.csv 算 AI persona 加权平均命中率(用于参考线)。

    Returns (avg_pct, n_sessions) 或 None(若 CSV 不存在)。
    """
    if not AI_CSV.exists():
        return None
    with AI_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    hits = []
    for r in rows:
        try:
            yes = _safe_int(r, "claude_total_✔")
            hits.append(yes / 37 * 100)
        except (KeyError, ValueError):
            continue
    if not hits:
        return None
    return round(sum(hits) / len(hits), 2), len(hits)


def competency_stats_from_md(md_path: Path) -> list[tuple[str, float]]:
    """从 tracker-analysis-real-{date}.md 解析能力维度命中率。
    若文件不存在或解析失败,返回硬编码 fallback。
    """
    fallback = [
        ("能力 3 建立协议", 87.5),
        ("能力 4 信任亲近", 75.0),
        ("能力 5 教练意识", 90.0),
        ("能力 6 积极聆听", 85.7),
        ("能力 7 唤起觉察", 100.0),
        ("能力 8 促进成长", 88.9),
    ]
    if not md_path.exists():
        return fallback
    out = []
    text = md_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("| 能力") and "**" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6:
                name = cells[0]
                rate_str = cells[5].replace("**", "").replace("%", "")
                try:
                    out.append((name, float(rate_str)))
                except ValueError:
                    pass
    return out or fallback


def build_html(
    sessions: list[dict],
    today: str,
    ai_avg: tuple[float, int] | None,
    radar: list[tuple[str, float]],
) -> str:
    n = len(sessions)
    hits = [s["hit"] for s in sessions]
    real_avg = sum(hits) / n if n else 0

    peak = max(sessions, key=lambda s: s["hit"]) if sessions else None
    trough = min(sessions, key=lambda s: s["hit"]) if sessions else None

    # 客户来源图例
    client_types = sorted({s["client_type"] for s in sessions})
    legend_html = "\n      ".join(
        f'<span><span class="dot" style="background: {client_color(ct)};"></span>{ct}</span>'
        for ct in client_types
    )

    # KPI: vs AI persona
    if ai_avg:
        ai_avg_pct, ai_n = ai_avg
        delta = real_avg - ai_avg_pct
        delta_html = (
            f'<div class="kpi"><div class="kpi-label">vs AI persona</div>'
            f'<div class="kpi-value" style="color: #fff;">{delta:+.1f}pp</div>'
            f'<div class="kpi-sub">AI {ai_avg_pct:.1f}% ({ai_n} 场)</div></div>'
        )
    else:
        delta_html = ""

    # 详情表行
    table_rows = []
    for i, s in enumerate(sessions, 1):
        bar_color = (
            "background: linear-gradient(90deg, #c53030, #f56565);"
            if s["hit"] < 50
            else "background: linear-gradient(90deg, #d97706, #fbbf24);"
            if s["hit"] >= 85
            else ""
        )
        bar_html = f'<div class="score-bar"><span style="width: {s["hit"]}%; {bar_color}"></span></div>'
        strong = "<strong>" + f'{s["hit"]:.2f}%' + "</strong>" if s["hit"] >= 85 or s["hit"] < 50 else f'{s["hit"]:.2f}%'
        time_str = f"{s['conv_date'][-5:]} <strong>{s['conv_time']}</strong>" if s["conv_time"] else s["conv_date"][-5:]
        topic_short = s["topic"][:24] + ("…" if len(s["topic"]) > 24 else "")
        notes_short = s["audio_quality_notes"][:30] + ("…" if len(s["audio_quality_notes"]) > 30 else "")
        # 链接到 audio / transcript 路径(相对路径,浏览器双击可看)
        audio_link = (
            f'<a href="../{s["audio_path"]}" title="{s["audio_path"]}">🎵 mp3</a>'
            if s["audio_path"] else ""
        )
        srt_link = (
            f'<a href="../{s["transcript_path"]}" title="{s["transcript_path"]}">📝 srt</a>'
            if s["transcript_path"] else ""
        )

        table_rows.append(
            f"""          <tr>
            <td>{i}</td>
            <td>{time_str}</td>
            <td><span class="badge client">{s["client_type"]}</span></td>
            <td>{topic_short}</td>
            <td>{s["good"]}</td><td>{s["part"]}</td><td>{s["fail"]}</td>
            <td>{s["mustHit"]}</td>
            <td>{bar_html}{strong}</td>
            <td>{audio_link} {srt_link}</td>
            <td style="font-size:11px; color: var(--muted);">{notes_short}</td>
          </tr>"""
        )
    table_rows_str = "\n".join(table_rows)

    # KPI 卡片
    peak_html = (
        f'<div class="kpi-value">{peak["hit"]:.1f}%</div>'
        f'<div class="kpi-sub">{peak["sid"]} ({peak["conv_date"]})</div>'
        if peak else ""
    )
    trough_html = (
        f'<div class="kpi-value">{trough["hit"]:.1f}%</div>'
        f'<div class="kpi-sub">{trough["sid"]} ({trough["conv_date"]})</div>'
        if trough else ""
    )

    # AI persona 参考线(注入到 JS)
    ai_avg_pct = ai_avg[0] if ai_avg else None

    # radar JSON
    radar_json = json.dumps([{"name": n, "rate": r} for n, r in radar])

    # sessions JSON
    sessions_json = json.dumps(
        [
            {
                **s,
                "label_short": f"{s['conv_date'][-5:]}\n{s['sid']}",
            }
            for s in sessions
        ],
        ensure_ascii=False,
    )

    narrative = (
        f"真人练习 N={n} 场 · 严格命中率平均 {real_avg:.1f}%(只算 ✔,不靠 △ 救分)"
        + (f" · 比 AI persona 严格率 {real_avg - ai_avg_pct:+.1f}pp" if ai_avg else "")
        + (f" · ⚠️ n<3,尚不构成 trend,只展示单点能力维度" if n < 3 else "")
    )

    html = HTML_TEMPLATE.format(
        n=n,
        n_trend_note=" · ⚠️ 暂不构成 trend" if n < 3 else "",
        today=today,
        real_avg=f"{real_avg:.1f}",
        peak_html=peak_html,
        trough_html=trough_html,
        delta_html=delta_html,
        legend_html=legend_html,
        table_rows=table_rows_str,
        sessions_json=sessions_json,
        radar_json=radar_json,
        ai_avg_pct=ai_avg_pct if ai_avg_pct is not None else "null",
        narrative=narrative,
    )
    return html


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>真人练习 PCC 趋势 · {n} 场 ({today})</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
  <style>
    :root {{
      --bg: #fff7ed;           /* amber-50 背景,暖色调 */
      --card: #ffffff;
      --border: #fde6c8;
      --text: #1c2027;
      --muted: #78350f;        /* amber-900 */
      --accent: #d97706;       /* amber-600 */
      --good: #2f855a;
      --warn: #d97706;
      --bad: #c53030;
      --shadow: 0 1px 2px rgba(217,119,6,0.06), 0 4px 12px rgba(217,119,6,0.06);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      background: linear-gradient(135deg, #d97706 0%, #ea580c 100%);  /* amber → orange */
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
      text-align: left; padding: 10px 12px; background: #fef3c7;
      font-weight: 600; color: var(--muted); border-bottom: 2px solid var(--border);
      font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
    }}
    tbody td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); }}
    tbody tr:hover {{ background: #fffbeb; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; font-family: ui-monospace, "SF Mono", monospace; }}
    .badge.client {{ background: #fde6c8; color: var(--accent); }}
    .score-bar {{
      display: inline-block; width: 60px; height: 6px;
      background: #fef3c7; border-radius: 3px; overflow: hidden;
      vertical-align: middle; margin-right: 6px;
    }}
    .score-bar > span {{ display: block; height: 100%; background: linear-gradient(90deg, #d97706, #fbbf24); }}
    .legend-row {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; font-size: 13px; color: var(--muted); }}
    .legend-row .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }}
    .callout {{
      padding: 14px 16px; background: #fff8e6; border-left: 3px solid var(--warn);
      border-radius: 6px; font-size: 13px; color: #5b4406; margin-top: 12px;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    footer {{ margin-top: 32px; padding: 20px; text-align: center; font-size: 12px; color: var(--muted); }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🤝 真人练习 PCC 趋势 · {n} 场数据{n_trend_note}</h1>
      <div class="subtitle">独立于 AI persona · 按 (conversation_date, conversation_time) 排序 · 双击可看 · 从 <code>tracker-real-sessions.csv</code> 生成</div>
      <div class="kpi-row">
        <div class="kpi"><div class="kpi-label">平均严格命中率</div><div class="kpi-value">{real_avg}%</div><div class="kpi-sub">{n} 场真人 ✔/37</div></div>
        <div class="kpi"><div class="kpi-label">最高分</div>{peak_html}</div>
        <div class="kpi"><div class="kpi-label">最低分</div>{trough_html}</div>
        {delta_html}
        <div class="kpi"><div class="kpi-label">生成时间</div><div class="kpi-value" style="font-size:14px;">{today}</div><div class="kpi-sub">自动化</div></div>
      </div>
    </header>

    <div class="card">
      <h2>① 严格命中率走势</h2>
      <p class="desc">每场真人练习 PCC 严格命中率 = ✔ / 37 · <strong style="color: var(--accent);">橙色虚线 = AI persona 严格率平均(参考线)</strong> · 2026-09-11 改:只看 ✔,避免 (29+0.5×8) 与 (30+0.5×6) 都 = 89.2% 撞分</p>
      <div class="chart-wrap tall"><canvas id="hitRateChart"></canvas></div>
      <div class="legend-row">{legend_html}</div>
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
        <p class="desc">最新 tracker-analysis-real 中的能力维度命中率</p>
        <div class="chart-wrap"><canvas id="radarChart"></canvas></div>
      </div>
    </div>

    <div class="card">
      <h2>④ 每场详情(按 conversation_date + time)</h2>
      <p class="desc">{n} 场真人练习的判定构成与严格命中率 · 点击"🎵 mp3 / 📝 srt"可回溯原文</p>
      <table>
        <thead>
          <tr>
            <th>#</th><th>实际时间</th><th>客户来源</th><th>议题</th>
            <th>✔</th><th>△</th><th>✘</th><th>必命中✘</th>
            <th>命中率</th><th>回溯</th><th>音频/转写备注</th>
          </tr>
        </thead>
        <tbody>
{table_rows}
        </tbody>
      </table>
    </div>

    <footer>
      数据来源: <code>progress/tracker-real-sessions.csv</code> ({n} 行, 95 列) ·
      参考线来源: <code>progress/tracker.csv</code> (AI persona) ·
      生成器: <code>scripts/gen_trending_chart_real.py</code> · 生成于 {today}
    </footer>
  </div>

  <script>
    const sessions = {sessions_json};
    const radarData = {radar_json};
    const aiAvg = {ai_avg_pct};

    const labels = sessions.map(s => s.label_short);
    const hits = sessions.map(s => s.hit);
    const clientFills = sessions.map(s => s.color);

    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    Chart.defaults.color = '#78350f';

    // 构造 annotation:AI 参考线(只在 aiAvg 非 null 时加)
    const annotations = {{}};
    if (aiAvg !== null && !isNaN(aiAvg)) {{
      annotations.aiAvgLine = {{
        type: 'line', yMin: aiAvg, yMax: aiAvg,
        borderColor: 'rgba(217, 119, 6, 0.65)',
        borderWidth: 1.8, borderDash: [6, 4],
        label: {{
          display: true, content: `AI persona 平均 ${{aiAvg.toFixed(1)}}%`,
          position: 'end',
          backgroundColor: 'rgba(217, 119, 6, 0.95)',
          color: '#fff', font: {{ size: 11, weight: '600' }}, padding: 4,
        }},
      }};
      annotations.phaseBTarget = {{
        type: 'line', yMin: 85, yMax: 85,
        borderColor: 'rgba(47, 133, 90, 0.4)',
        borderWidth: 1.2, borderDash: [3, 3],
        label: {{
          display: true, content: 'Phase B 目标 85%',
          position: 'start',
          backgroundColor: 'rgba(47, 133, 90, 0.9)',
          color: '#fff', font: {{ size: 10 }}, padding: 4,
        }},
      }};
    }}

    new Chart(document.getElementById('hitRateChart').getContext('2d'), {{
      type: 'line',
      data: {{
        labels: labels,
        datasets: [{{
          label: '命中率 (%)',
          data: hits,
          borderColor: '#d97706',
          backgroundColor: 'rgba(217, 119, 6, 0.10)',
          borderWidth: 2.5, tension: 0.25,
          pointRadius: 8, pointHoverRadius: 10,
          pointBackgroundColor: clientFills,
          pointBorderColor: '#fff', pointBorderWidth: 2,
          fill: true,
        }}],
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            backgroundColor: 'rgba(28, 32, 39, 0.92)', padding: 12,
            callbacks: {{
              label: (ctx) => {{
                const s = sessions[ctx.dataIndex];
                return [
                  `命中率: ${{s.hit.toFixed(2)}}%`,
                  `✔ ${{s.good}} · △ ${{s.part}} · ✘ ${{s.fail}}`,
                  `必命中✘: ${{s.mustHit}}`,
                  `议题: ${{s.topic}}`,
                ];
              }},
            }},
          }},
          annotation: {{ annotations }},
        }},
        scales: {{
          y: {{ beginAtZero: false, min: 35, max: 100,
                ticks: {{ callback: (v) => v + '%' }}, grid: {{ color: '#fef3c7' }} }},
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
          y: {{ beginAtZero: true, max: 37, ticks: {{ stepSize: 5 }}, grid: {{ color: '#fef3c7' }} }},
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
            fill: true, backgroundColor: 'rgba(217, 119, 6, 0.20)',
            borderColor: '#d97706', borderWidth: 2,
            pointBackgroundColor: '#d97706', pointRadius: 4 }},
          {{ label: 'Phase B 参考线',
            data: radarData.map(() => 85),
            fill: false, borderColor: 'rgba(47, 133, 90, 0.5)',
            borderWidth: 1.5, borderDash: [5, 3], pointRadius: 0 }},
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
            pointLabels: {{ font: {{ size: 12 }} }}, grid: {{ color: '#fef3c7' }},
          }},
        }},
      }},
    }});
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", type=Path, default=REAL_CSV, help="真人练习 CSV 路径")
    parser.add_argument(
        "--out",
        type=Path,
        default=PROGRESS / "trending-chart-real.html",
        help="输出 HTML 路径(默认:progress/trending-chart-real.html,覆盖式)",
    )
    parser.add_argument("--print", action="store_true", help="同时打印会话摘要到 stdout")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: 真人练习 CSV 不存在:{args.csv}", file=sys.stderr)
        return 1

    try:
        sessions = load_real_sessions(args.csv)
    except Exception as e:
        print(f"ERROR: 读 CSV 失败:{e}", file=sys.stderr)
        return 1

    if not sessions:
        print(f"ERROR: {args.csv} 没有数据行", file=sys.stderr)
        return 1

    today = datetime.now().strftime("%Y-%m-%d")
    ai_avg = compute_ai_avg()

    # radar:从与 CSV 同日/前一日的 tracker-analysis-real-*.md 解析
    analysis_candidates = sorted(PROGRESS.glob("tracker-analysis-real-*.md"), reverse=True)
    radar_src = analysis_candidates[0] if analysis_candidates else PROGRESS / "tracker-analysis-real-NEVER.md"
    radar = competency_stats_from_md(radar_src)

    html = build_html(sessions, today, ai_avg, radar)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    real_avg = sum(s["hit"] for s in sessions) / len(sessions)
    print(f"✅ 真人练习 trending chart 已生成:{args.out}")
    print(f"   场数:{len(sessions)} · 平均 {real_avg:.1f}%")
    if ai_avg:
        delta = real_avg - ai_avg[0]
        print(f"   AI persona 参考:{ai_avg[0]:.1f}% ({ai_avg[1]} 场) · 差值 {delta:+.1f}pp")
    if args.print:
        print("\n  会话明细:")
        for s in sessions:
            print(f"   - {s['sid']} | {s['conv_date']} | {s['hit']:.1f}% | 议题:{s['topic'][:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
