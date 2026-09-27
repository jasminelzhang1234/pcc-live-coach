#!/usr/bin/env python3
"""gen_trending_chart.py — 从 tracker.csv 自动生成 trending chart HTML。

读取 progress/tracker.csv (header 列数,2026-09-27 = 92 列),按 (conversation_date, conversation_time) 排序,
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

def _safe_int_pcc(raw: str) -> int | None:
    """老 v4.1.0/v4.1.2 行 key_weakness 含未引号逗号,字段错位 → pcc_pass_pct 读到非数字。
    这些行无法估算 PCC,通过概率返回 None(图表渲染为 N/A)。"""
    s = (raw or "").strip()
    if not s or not s.lstrip("-").isdigit():
        return None
    return int(s)


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
        # 字段错位行(row 23 vec-04-2026-09-19-session-01)→ totals 读到 marker 字符,跳过
        if not str(r.get("claude_total_✔", "")).lstrip("-").isdigit():
            continue
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
                "hit": hit,
                "hit_strict": strict_hit,
                "good": yes,
                "part": part,
                "fail": no,
                "mustHit": int(r["must_hit_✘_count"]),
                "short_label": f"{persona_short} s{last}",
                "eval_version": r.get("eval_version", "").strip(),
                "pcc_pass": _safe_int_pcc(r.get("pcc_pass_pct", "")),
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


def build_html(sessions: list[dict], today: str, n_cols: int = 0) -> str:
    n = len(sessions)
    hits = [s["hit"] for s in sessions]
    avg = sum(s["hit_strict"] for s in sessions) / n if n else 0
    n_outliers = sum(1 for s in sessions if is_outlier(s))

    # KPI 计算
    peak = max(sessions, key=lambda s: s["hit"]) if sessions else None
    trough = min(sessions, key=lambda s: s["hit_strict"]) if sessions else None

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

    # 详情表行(单维度主信号重构,2026-09-27):
    # - PCC 通过概率列是**唯一**保留 3 色(绿/橙/红)的位置
    # - persona / diff / KB 版本全部去色(灰底 + 小色点 / 数字 / 灰字)
    # - outlier 行用单一浅黄背景,合并旧 pcc-bad-row / pcc-warn-row 冗余
    table_rows = []
    for i, s in enumerate(sessions, 1):
        is_reeval = bool(s["reeval_of"])
        is_outl = is_outlier(s)
        # 行背景:reeval 加淡黄,outlier 用 highlight-row(单一浅黄类)
        if is_outl:
            row_class = "highlight-row"
            bg = ""
        elif is_reeval:
            row_class = ""
            bg = ' style="background: #fffbeb;"'
        else:
            row_class = ""
            bg = ""
        # 进度条统一蓝色,长度是唯一编码;数字不加粗不染色,纯信息(2026-09-27 单维度主信号)
        bar_html = f'<div class="score-bar"><span style="width: {s["hit_strict"]}%"></span></div>'
        pct_str = f'{s["hit_strict"]:.2f}%'
        # session_id_note:仅 reeval 时显示"(但记作 MM-DD)" — 非 reeval 时日期已在 time_str 里,避免冗余
        if is_reeval and s["date"] != s["conv_date"]:
            session_id_note = f"但记作 {s['date'][-5:]}"
        else:
            session_id_note = ""
        time_str = f"{s['conv_date'][-5:]} <strong>{s['conv_time']}</strong>" if s["conv_time"] else s["conv_date"][-5:]
        outlier_flag = "⚠️ " if is_outlier(s) else ""
        eval_v = s.get("eval_version", "")
        eval_v_label = f' <span class="kb-tag">{eval_v}</span>' if eval_v else ""
        # PCC 通过概率:唯一保留 3 色语义的字段
        pcc = s.get("pcc_pass")
        if pcc is None:
            pcc_cell = '<span class="muted">—</span>'
        elif pcc < 50:
            pcc_cell = f'<span class="pcc-bad">{pcc}%</span>'
        elif pcc < 70:
            pcc_cell = f'<span class="pcc-warn">{pcc}%</span>'
        else:
            pcc_cell = f'<span class="pcc-good">{pcc}%</span>'
        # 严格高 + PCC 低 = misleading 标记
        misleading = " ⚠️" if s["hit_strict"] >= 85 and pcc is not None and pcc < 50 else ""

        table_rows.append(
            f"""          <tr class="{row_class}"{bg}>
            <td>{i}</td>
            <td>{time_str} {outlier_flag}{session_id_note}{eval_v_label}</td>
            <td><span class="persona-tag"><span class="persona-dot {s['persona']}"></span>{s['persona']}</span></td>
            <td><span class="diff-num">{s['diff']}</span></td>
            <td>{s['good']}</td><td>{s['part']}</td><td>{s['fail']}</td>
            <td>{s['mustHit']}</td>
            <td>{bar_html}{pct_str}</td>
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

    # PCC 通过场次:概率 ≥ 70% 算通过,50-69% 边缘,< 50% 失败
    pcc_passed = [s for s in sessions if s.get("pcc_pass") is not None and s["pcc_pass"] >= 70]
    pcc_marginal = [s for s in sessions if s.get("pcc_pass") is not None and 50 <= s["pcc_pass"] < 70]
    pcc_failed = [s for s in sessions if s.get("pcc_pass") is not None and s["pcc_pass"] < 50]
    n_pass = len(pcc_passed)
    n_marg = len(pcc_marginal)
    n_fail = len(pcc_failed)
    n_with_pcc = n_pass + n_marg + n_fail
    pass_pct = (n_pass / n_with_pcc * 100) if n_with_pcc else 0
    pass_html = (
        f'<div class="kpi-value">{n_pass}/{n_with_pcc}</div>'
        f'<div class="kpi-sub">{pass_pct:.0f}% 通过(≥70%) · 边缘 {n_marg} · 失败 {n_fail}</div>'
    )

    # 雷达数据(从最新 tracker-analysis 解析)
    radar = competency_stats(sessions)
    radar_json = json.dumps([{"name": n, "rate": r} for n, r in radar])

    html = HTML_TEMPLATE.format(
        n=n,
        n_cols=n_cols,
        today=today,
        avg=f"{avg:.1f}",
        pass_html=pass_html,
        peak_html=peak_html,
        trough_html=trough_html,
        table_rows=table_rows_str,
        sessions_json=sessions_json,
        radar_json=radar_json,
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
    header .subtitle {{ opacity: 0.9; font-size: 14px; margin-bottom: 12px; }}
    header .footnote {{ opacity: 0.85; font-size: 12px; font-weight: 400; margin-bottom: 18px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }}
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
    /* persona 标签:灰底 + 小色点(避免与状态色撞色;2026-09-27 单维度主信号重构) */
    .persona-tag {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-family: ui-monospace, "SF Mono", monospace; }}
    .persona-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
    .persona-dot.vec-01 {{ background: var(--persona-1); }}
    .persona-dot.vec-02 {{ background: var(--persona-2); }}
    .persona-dot.vec-06 {{ background: var(--persona-6); }}
    .persona-dot.vec-07 {{ background: var(--persona-7); }}
    .persona-dot.vec-08 {{ background: var(--persona-8); }}
    .persona-dot.voc-08 {{ background: #8b5cf6; }}
    .persona-dot.voc-06 {{ background: #a78bfa; }}
    .persona-dot.voc-07 {{ background: #c4b5fd; }}
    /* KB 版本标签:灰色为主,避免蓝色抢戏 */
    .kb-tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-family: ui-monospace, "SF Mono", monospace; background: #f1f4f7; color: var(--muted); margin-left: 4px; }}
    /* outlier / reeval:极浅黄(单一背景,合并旧 pcc-bad-row / pcc-warn-row 冗余) */
    .highlight-row {{ background: #fffaf0; }}
    .highlight-row:hover {{ background: #fff3d6 !important; }}
    /* PCC 通过概率单元格:唯一保留 3 色语义的位置 */
    .pcc-good {{ color: var(--good); font-weight: 600; }}
    .pcc-warn {{ color: var(--warn); font-weight: 600; }}
    .pcc-bad {{ color: var(--bad); font-weight: 600; }}
    .muted {{ color: var(--muted); opacity: 0.6; }}
    /* 难度数字:纯灰,无色 */
    .diff-num {{ display: inline-block; min-width: 20px; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-family: ui-monospace, "SF Mono", monospace; background: #f1f4f7; color: var(--text); text-align: center; }}
    .score-bar {{
      display: inline-block; width: 60px; height: 6px;
      background: #eef0f4; border-radius: 3px; overflow: hidden;
      vertical-align: middle; margin-right: 6px;
    }}
    .score-bar > span {{ display: block; height: 100%; background: linear-gradient(90deg, #2b6cb0, #4299e1); }}
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
      <div class="footnote"><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#2b6cb0;border:1.5px solid #fff;vertical-align:middle;margin-right:4px;"></span>数据点(蓝)<span style="margin-left:12px;"></span><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#2b6cb0;border:3.5px solid #e53e3e;vertical-align:middle;margin-right:4px;"></span>outlier(严格率 &lt; 60%)</div>
      <div class="kpi-row">
        <div class="kpi"><div class="kpi-label">PCC 通过场次</div>{pass_html}</div>
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
          <tr><th>#</th><th>时间 + 标记</th><th>Persona</th><th>难度</th><th>✔</th><th>△</th><th>✘</th><th>必命中✘</th><th>严格 (主·v4.1.0)</th><th>复合 (辅)</th><th>PCC 通过概率</th></tr>
        </thead>
        <tbody>
{table_rows}
        </tbody>
      </table>
    </div>

    <footer>
      数据来源: <code>progress/tracker.csv</code> ({n} 行, {n_cols} 列) · 自动生成脚本 <code>scripts/gen_trending_chart.py</code> · 生成于 {today}
    </footer>
  </div>

  <script>
    // ===== 自动从 gen_trending_chart.py 注入 =====
    const sessions = {sessions_json};
    const radarData = {radar_json};

    const labels = sessions.map(s => s.label_short);
    const hits = sessions.map(s => s.hit);
    const strictHits = sessions.map(s => s.hit_strict);
    const pccPasses = sessions.map(s => (s.pcc_pass === null || s.pcc_pass === undefined) ? null : s.pcc_pass);

    // 数据点边框:仅 outlier 红色粗边框(单维度主信号 — 2026-09-27 重构)
    const pointBorders = sessions.map(s => ((s.hit_strict || 0) < 60 ? '#e53e3e' : '#ffffff'));
    const pointBorderWidths = sessions.map(s => (s.hit_strict || 0) < 60 ? 3.5 : 1.5);

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
            pointBackgroundColor: '#2b6cb0',
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
                  'Persona: ' + s.persona + ' · 难度 ' + s.diff,
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
                  position: 'start',
                  backgroundColor: 'rgba(113, 128, 150, 0.95)',
                  color: '#fff', font: {{ size: 11, weight: '600' }}, padding: 4,
                }},
              }},
            }},
          }},
        }},
        scales: {{
          y: {{ beginAtZero: true, min: 0, max: 100,
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
    # 读取 CSV header 列数(动态 — schema 演进时 footer 元数据自动更新,2026-09-27 加固)
    with CSV.open(newline="", encoding="utf-8") as _f:
        _reader = csv.reader(_f)
        n_cols = len(next(_reader))
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
    html = build_html(sessions, today, n_cols=n_cols)
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