#!/usr/bin/env python3
"""analyze_tracker.py — pcc-tracker-agent 的数据处理后端

读 progress/tracker.csv,生成 markdown 报告到 progress/tracker-analysis-{date}.md。

输入:tracker.csv (91 列,含 conversation_date / conversation_time / reeval_of / 37 markers × Claude + DeepSeek + metadata)
输出:能力维度命中率 / 反复失守 marker / 反复 △ marker / 必命中项 / 重评 lineage / 每场 summary

排序:按 (conversation_date, conversation_time) 升序(实际对话时间);
同 datetime 保留 CSV 原顺序(stable sort);conversation_time 缺失时回退到 CSV 顺序。

用法:
    python3 scripts/analyze_tracker.py                          # 用默认路径
    python3 scripts/analyze_tracker.py --csv <path> --out <path> # 自定义
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# 能力维度 → markers 映射
COMPETENCY_MARKERS = {
    "能力 3 建立协议": ["3.1", "3.2", "3.3", "3.4"],
    "能力 4 信任亲近": ["4.1", "4.2", "4.3", "4.4"],
    "能力 5 教练意识": ["5.1", "5.2", "5.3", "5.4", "5.5"],
    "能力 6 积极聆听": [f"6.{i}" for i in range(1, 8)],
    "能力 7 唤起觉察": [f"7.{i}" for i in range(1, 9)],
    "能力 8 促进成长": [f"8.{i}" for i in range(1, 10)],
}

MUST_HIT_MARKERS = ["3.1", "3.4", "6.7", "7.2", "7.3", "8.5", "8.9"]

MARKER_NAMES = {
    "3.1": "确认成果", "3.2": "成功衡量", "3.3": "意义层",
    "3.4": "定义处理什么", "4.1": "认可才能", "4.2": "同理/关心",
    "4.3": "支持", "4.4": "邀请回应教练贡献", "5.1": "好奇", "5.2": "跟随客户",
    "5.3": "决定权交还", "5.4": "探索新信息", "5.5": "允许沉默",
    "6.1": "关注", "6.2": "捕捉", "6.3": "命名情绪",
    "6.4": "非语言/能量", "6.5": "整合视角", "6.6": "不打断",
    "6.7": "简洁反映/总结", "7.1": "开放式提问", "7.2": "超越当前认知(身份层)",
    "7.3": "超越当前认知(事层)", "7.4": "身份层合约",
    "7.5": "无附着分享观察", "7.6": "邀请承诺/假设",
    "7.7": "邀请探索", "7.8": "字数比", "8.1": "目标进展",
    "8.2": "今天学到的", "8.3": "处境新理解", "8.4": "运用新学习",
    "8.5": "设计会后行动", "8.6": "资源/支持/障碍",
    "8.7": "设计问责", "8.8": "设计承诺/庆祝进展", "8.9": "共同决定结束",
}


def current_default_kb_version() -> str:
    """读 knowledge/pcc-assessor-versions.md,返回 current_version 字段;
    失败时 fallback 到 v4.1.x(2026-09-22 已发布,已知 latest)。
    """
    versions_path = Path(__file__).parent.parent / "knowledge" / "pcc-assessor-versions.md"
    if versions_path.exists():
        text = versions_path.read_text(encoding="utf-8")
        m = re.search(r"current_version:\s*(\S+)", text)
        if m:
            return m.group(1)
    return "v4.1.x"  # fallback to v4.1.x family


def is_kb_match(row: dict, kb_version: str) -> bool:
    """判定 row 是否属于指定 KB 版本切片。
    - 'current' → 匹配最新 v4.1.x 家族(v4.1.0/v4.1.1/v4.1.2/v4.1.3/v4.1.6 等)
    - 'all' → 全部
    - 其它字符串 → 精确匹配(如 'v4.1.6' / 'v3')
    """
    ev = row.get("eval_version", "").strip()
    if kb_version == "all":
        return True
    if kb_version == "current":
        return ev.startswith("v4.1.")
    return ev == kb_version


def filter_by_kb(rows: list[dict], kb_version: str) -> list[dict]:
    return [r for r in rows if is_kb_match(r, kb_version)]


def find_outliers(rows: list[dict], threshold: float = 60.0) -> list[tuple]:
    """找严格率 < threshold% 的场次。返回 [(session_id, eval_version, strict_pct), ...]"""
    out = []
    for r in rows:
        try:
            yes = int(r.get("claude_total_✔", 0))
        except (ValueError, TypeError):
            continue
        strict_pct = yes / 37 * 100
        if strict_pct < threshold:
            out.append((r["session_id"], r.get("eval_version", ""), strict_pct))
    return out


def persona_session_counts(rows: list[dict]) -> dict[str, int]:
    """每个 persona 的场次数,用于趋势报告的最小样本提示。"""
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.get("persona", "")] += 1
    return dict(counts)


def load_rows(csv_path: Path) -> list[dict]:
    """读 tracker.csv,跳过 header,转成 dict 列表。

    按 (conversation_date, conversation_time) 升序排序;同 datetime 保留 CSV 原顺序
    (stable sort)。conversation_date 缺失则回退到 date;conversation_time 缺失则视为空串。
    """
    with csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    def sort_key(r):
        cd = r.get("conversation_date", "") or r.get("date", "")
        ct = r.get("conversation_time", "") or ""
        return (cd, ct)

    rows.sort(key=sort_key)
    return rows


def marker_judgments(rows: list[dict]) -> dict[str, list[str]]:
    """对每个 marker,聚合所有场的判定。返回 {marker: ['✔','✘','△',...]}"""
    out: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for m in COMPETENCY_MARKERS["能力 8 促进成长"]:
            v = row.get(f"claude_{m}", "").strip()
            if v in ("✔", "△", "✘"):
                out[m].append(v)
        # 上面循环已覆盖所有 markers(因 8.x 包含全部),简化一下:
    # 重写:遍历所有 markers
    out = defaultdict(list)
    for row in rows:
        for comp in COMPETENCY_MARKERS.values():
            for m in comp:
                v = row.get(f"claude_{m}", "").strip()
                if v in ("✔", "△", "✘"):
                    out[m].append(v)
    return out


def competency_stats(rows: list[dict]) -> list[tuple[str, int, int, int, int, float]]:
    """算每个能力维度的命中率。返回 (能力名, ✔, △, ✘, 总数, 命中率%)"""
    out = []
    for comp, markers in COMPETENCY_MARKERS.items():
        yes = part = no = 0
        for row in rows:
            for m in markers:
                v = row.get(f"claude_{m}", "").strip()
                if v == "✔": yes += 1
                elif v == "△": part += 1
                elif v == "✘": no += 1
        total = yes + part + no
        # 严格命中率(v4.1.0 主指标,与 chart 蓝实线 / 橙实线对齐)只看 ✔,不靠 △ 救分
        # 2026-09-17 改:之前 (yes + 0.5*part)/total 会出现 29✔+8△ = 30✔+6△ 撞分
        hit_rate = yes / total * 100 if total else 0
        out.append((comp, yes, part, no, total, hit_rate))
    return out


def repeated_failures(judgments: dict[str, list[str]], threshold: int) -> list[tuple[str, list[str]]]:
    """找反复失守 marker(≥ threshold 场 ✘)"""
    return [(m, js) for m, js in judgments.items() if js.count("✘") >= threshold]


def repeated_partial(judgments: dict[str, list[str]], threshold: int) -> list[tuple[str, list[str]]]:
    """找反复 △ marker(≥ threshold 场 △,且 ✘ 数 < ✔ 数)"""
    return [(m, js) for m, js in judgments.items()
            if js.count("△") >= threshold and js.count("✘") < js.count("✔")]


def strength_zone(judgments: dict[str, list[str]]) -> list[str]:
    """优势区(所有场都 ✔)"""
    return [m for m, js in judgments.items() if all(v == "✔" for v in js)]


def must_hit_status(rows: list[dict]) -> dict[str, list[str]]:
    """必命中项跨场状态"""
    out: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for m in MUST_HIT_MARKERS:
            v = row.get(f"claude_{m}", "").strip()
            if v in ("✔", "△", "✘"):
                out[m].append(v)
    return out


def render_report(rows: list[dict], date: str, csv_name: str = "tracker.csv", kb_version: str = "all") -> str:
    """生成 markdown 报告。

    kb_version:
    - "current" → 最新 v4.1.x 家族(默认,与 trending chart 主指标对齐)
    - "all" → 全量聚合(参考用,跨 KB 版本,统计意义弱)
    - 其它(如 "v4.1.6" / "v3")→ 精确匹配单版本
    """
    n = len(rows)
    # 数据质量:row 23 (vec-04-2026-09-19-session-01) 字段错位(extra topic field → 所有列左移 1)
    # → claude_total_✔ 读到 '✔' 而非数字 → 排除该行避免污染 marker 聚合
    valid_rows = [r for r in rows if str(r.get("claude_total_✔", "")).lstrip("-").isdigit()]
    broken_rows = [r for r in rows if r not in valid_rows]
    judgments = marker_judgments(valid_rows)
    comp_stats = competency_stats(valid_rows)
    fails = repeated_failures(judgments, threshold=max(3, len(valid_rows) // 2))
    partials = repeated_partial(judgments, threshold=max(3, len(valid_rows) // 2))
    strengths = strength_zone(judgments)
    must_hit = must_hit_status(valid_rows)
    outliers = find_outliers(valid_rows, threshold=60.0)
    persona_counts = persona_session_counts(valid_rows)

    # KB 切片说明
    if kb_version == "current":
        slice_label = "v4.1.x(默认切片,与 trending chart 主指标对齐)"
    elif kb_version == "all":
        slice_label = "全量聚合(跨 KB 版本,统计意义弱,仅参考)"
    else:
        slice_label = f"{kb_version}(精确匹配)"

    md = [
        f"# Tracker 分析报告 — {date}(自动生成,{len(valid_rows)} 场 · {slice_label}",
    ]
    if broken_rows:
        md[0] += f",{len(broken_rows)} 字段错位行已排除)"
        broken_note = ", ".join(r["session_id"] for r in broken_rows)
    else:
        md[0] += ")"
    md += [
        "",
        f"> 来源:[progress/{csv_name}]({csv_name})",
        f"> KB 切片:`{kb_version}` · 生成器:`scripts/analyze_tracker.py`",
    ]
    if broken_rows:
        md += [f"> ⚠️ 字段错位行:{broken_note}(key_weakness 有未引号逗号,导致 totals 左移 1)— 仅展示于每场 summary,不参与 marker 聚合)"]
    md += [
        "",
        "## 📊 能力维度命中率",
        "",
        "| 能力 | ✔ | △ | ✘ | 总 | 命中率 |",
        "|---|---|---|---|---|---|",
    ]
    for comp, yes, part, no, total, rate in comp_stats:
        md.append(f"| {comp} | {yes} | {part} | {no} | {total} | **{rate:.1f}%** |")

    total_yes = sum(s[1] for s in comp_stats)
    total_part = sum(s[2] for s in comp_stats)
    total_no = sum(s[3] for s in comp_stats)
    total_all = total_yes + total_part + total_no
    # 严格口径(只看 ✔),与 chart 主指标 + 能力维度表对齐
    weighted = total_yes / total_all * 100 if total_all else 0
    md += [
        "",
        f"**总命中率(严格,只看 ✔):{weighted:.1f}%** — 与 trending chart 主指标(严格 ✔/37)对齐",
        "",
    ]

    # Misleading 案例:严格率 ≥85% 但 PCC 通过概率 < 50%(必命中失守触发一票否决)
    misleading_rows = []
    for r in valid_rows:  # 只用 valid_rows(排除字段错位行)
        pcc_raw = r.get("pcc_pass_pct", "").strip()
        # 老 v4.1.0/v4.1.2 行 key_weakness 含未引号逗号,字段错位,pcc_pass_pct 读到非数字 → 跳过
        if not pcc_raw or not pcc_raw.lstrip("-").isdigit():
            continue
        pcc_val = int(pcc_raw)
        try:
            yes = int(r.get("claude_total_✔", 0))
        except ValueError:
            yes = 0
        strict_pct = yes / 37 * 100
        if strict_pct >= 85 and pcc_val < 50:
            misleading_rows.append((r["session_id"], r.get("eval_version", ""), strict_pct, pcc_val, r.get("must_hit_✘_count", "0")))
    if misleading_rows:
        md += [
            "---",
            "",
            "## 🚨 严格高 + PCC 低(misleading 案例)",
            "",
            "严格率 ≥85% 但 PCC 通过概率 < 50%(必命中失守触发一票否决)。",
            "**只看严格率会高估真实表现** — 必命中失守 1 条就让 PCC 通过概率坍塌。",
            "",
            "| Session | KB 版本 | 严格率 | PCC 通过 | 必命中 ✘ |",
            "|---|---|---|---|---|",
        ]
        for sid, ev, sp, pp, mh in misleading_rows:
            md.append(f"| {sid} | {ev} | {sp:.1f}% | **{pp}%** | {mh} |")
        md += ["", ""]

    # Outlier 警告(在头部加,显眼)
    if outliers:
        md += [
            "---",
            "",
            f"## ⚠️ Outlier 场次(严格率 < 60%)",
            "",
            f"{len(outliers)} 场低于 60% 严格率,已**排除**对能力维度主指标的污染:</>",
            "",
            "| Session | KB 版本 | 严格率 |",
            "|---|---|---|",
        ]
        for sid, ev, pct in outliers:
            md.append(f"| {sid} | {ev} | **{pct:.1f}%** |")
        md += ["", ""]

    md += [
        "---",
        "",
        f"## ⚠️ 反复失守 marker(≥ {max(3, n // 2)} 场 ✘)",
        "",
        "| Marker | 名称 | 跨场 | 反复 ✘ 数 |",
        "|---|---|---|---|",
    ]
    for m, js in sorted(fails, key=lambda x: -x[1].count("✘")):
        md.append(f"| {m} | {MARKER_NAMES.get(m, '?')} | {' '.join(js)} | {js.count('✘')} |")

    md += [
        "",
        "---",
        "",
        f"## 🔶 反复 △ marker(≥ {max(3, n // 2)} 场 △)",
        "",
        "| Marker | 名称 | 跨场 | 反复 △ 数 |",
        "|---|---|---|---|",
    ]
    for m, js in sorted(partials, key=lambda x: -x[1].count("△")):
        md.append(f"| {m} | {MARKER_NAMES.get(m, '?')} | {' '.join(js)} | {js.count('△')} |")

    md += [
        "",
        "---",
        "",
        "## ✅ 优势区(全 ✔)",
        "",
        ", ".join(f"**{m}** {MARKER_NAMES.get(m, '?')}" for m in strengths),
        "",
        "---",
        "",
        "## 🎯 必命中项跨场",
        "",
        "| Marker | 跨场 | ✘ 数 |",
        "|---|---|---|",
    ]
    for m in MUST_HIT_MARKERS:
        js = must_hit.get(m, [])
        md.append(f"| {m} | {' '.join(js)} | {js.count('✘')} |")

    md += [
        "",
        "---",
        "",
        f"## 👥 Persona 场次分布(切片内 ≥ 1 场的全部 persona)",
        "",
        "| Persona | 场次 | 趋势统计意义 |",
        "|---|---|---|",
    ]
    for p, cnt in sorted(persona_counts.items(), key=lambda x: -x[1]):
        if cnt >= 3:
            note = f"✔ 可参考({cnt} 场 ≥ 3 阈值)"
        elif cnt == 2:
            note = f"⚠️ 仅单场对照,无趋势(2 场)"
        else:
            note = f"⚠️ 单场,无趋势(1 场)"
        md.append(f"| {p} | {cnt} | {note} |")
    md += [
        "",
        "> **趋势统计阈值 ≥ 3 场**:单 persona 需要至少 3 场才能说趋势,",
        "> 2 场只能说单场对照,1 场无趋势结论。",
        "",
        "---",
        "",
        "## 📋 每场 summary(按 (conversation_date, conversation_time) 升序)",
        "",
        "| # | session_id | 对话日期时间 | 评估日期 | persona | 难度 | ✔ | △ | ✘ | 必命中 ✘ | PCC 通过 | 评估者 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    outlier_sids = {sid for sid, _, _ in outliers}
    for i, row in enumerate(rows, 1):
        cd = row.get("conversation_date", "") or row.get("date", "")
        ct = row.get("conversation_time", "")
        dt = f"{cd} {ct}".strip() if ct else cd
        sid_display = row["session_id"]
        if sid_display in outlier_sids:
            sid_display = f"⚠️ {sid_display}"
        # 字段错位行(extra topic 多了 1 列 → 所有列左移 1)— 标 🚧
        broken_sids = {r["session_id"] for r in broken_rows}
        if sid_display in broken_sids:
            sid_display = f"🚧 {sid_display}"
        # 字段错位行 totals 读到 marker 字符,展示异常
        ct_raw = row.get("claude_total_✔", "")
        cdp_raw = row.get("claude_total_△", "")
        cdx_raw = row.get("claude_total_✘", "")
        ct_display = ct_raw if ct_raw.lstrip("-").isdigit() else f"🚧{ct_raw}"
        cdp_display = cdp_raw if cdp_raw.lstrip("-").isdigit() else f"🚧{cdp_raw}"
        cdx_display = cdx_raw if cdx_raw.lstrip("-").isdigit() else f"🚧{cdx_raw}"
        # PCC 通过概率(严格高 + PCC 低 = misleading)
        pcc_raw = row.get("pcc_pass_pct", "").strip()
        if ct_raw.lstrip("-").isdigit():
            strict_pct = int(ct_raw) / 37 * 100
        else:
            strict_pct = 0
        if pcc_raw and pcc_raw.lstrip("-").isdigit():
            pcc_val = int(pcc_raw)
            misleading = " ⚠️" if strict_pct >= 85 and pcc_val < 50 else ""
            pcc_cell = f"**{pcc_val}%**{misleading}"
        elif pcc_raw:
            # 老 v4.1.0/v4.1.2 行字段错位,无法读取 — 用 em-dash 表示
            pcc_cell = "—(字段错位)"
        else:
            pcc_cell = "—(无 HTML 报告)"
        md.append(
            f"| {i} | {sid_display} | {dt} | {row['date']} "
            f"| {row['persona']} | {row['difficulty']} "
            f"| {ct_display} | {cdp_display} "
            f"| {cdx_display} | {row['must_hit_✘_count']} "
            f"| {pcc_cell} | {row['judge_main']} |"
        )

    # 重评 lineage
    reevals = [r for r in rows if r.get("reeval_of", "").strip()]
    if reevals:
        md += [
            "",
            "---",
            "",
            "## 🔁 重评 lineage",
            "",
            "| 当前 session_id | 重评自 | 对话日期时间 | 评估日期 | 备注 |",
            "|---|---|---|---|---|",
        ]
        for r in reevals:
            cd = r.get("conversation_date", "")
            ct = r.get("conversation_time", "")
            dt = f"{cd} {ct}".strip() if ct else cd
            note = f"同次对话用新版评估规则重跑"
            md.append(
                f"| {r['session_id']} | {r['reeval_of']} "
                f"| {dt} | {r['date']} | {note} |"
            )

    md += [
        "",
        "---",
        "",
        f"**生成时间**:{date}",
        f"**输入**:{csv_name}({n} 行,{len(rows[0]) if rows else 0} 列)",
        f"**排序**:按 (conversation_date, conversation_time),同 datetime 保留 CSV 原顺序",
    ]
    return "\n".join(md) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_csv = Path(__file__).parent.parent / "progress" / "tracker.csv"
    parser.add_argument("--csv", type=Path, default=default_csv, help="tracker.csv 路径")
    parser.add_argument(
        "--kb-version",
        default="current",
        help="KB 版本切片:'current'(默认 = v4.1.x)/ 'all' / 精确版本(如 v4.1.6 / v3)",
    )
    parser.add_argument("--print", action="store_true", help="同时打印到 stdout")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出报告路径(默认按 KB 切片自动命名)",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: tracker.csv not found at {args.csv}", file=sys.stderr)
        return 1

    rows = load_rows(args.csv)
    if not rows:
        print("ERROR: tracker.csv is empty", file=sys.stderr)
        return 1

    filtered = filter_by_kb(rows, args.kb_version)
    if not filtered:
        print(
            f"ERROR: KB slice '{args.kb_version}' 没有匹配到任何场次,csv 全量 {len(rows)} 场",
            file=sys.stderr,
        )
        return 1

    today = datetime.now().strftime("%Y-%m-%d")
    csv_name = args.csv.name
    report = render_report(filtered, today, csv_name=csv_name, kb_version=args.kb_version)

    # 默认输出文件名按 KB 切片命名:
    #   current → tracker-analysis-{date}.md(默认,覆盖)
    #   all     → tracker-analysis-all-{date}.md
    #   精确版   → tracker-analysis-{version}-{date}.md
    if args.out:
        out = args.out
    elif args.kb_version == "current":
        out = default_csv.parent / f"tracker-analysis-{today}.md"
    elif args.kb_version == "all":
        out = default_csv.parent / f"tracker-analysis-all-{today}.md"
    else:
        safe_v = args.kb_version.replace("/", "-").replace(" ", "-")
        out = default_csv.parent / f"tracker-analysis-{safe_v}-{today}.md"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"✅ 报告已生成:{out}({len(filtered)} 场 / KB={args.kb_version} / 全量 {len(rows)} 场)")

    if args.print:
        print("\n" + report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
