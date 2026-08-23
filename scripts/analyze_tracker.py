#!/usr/bin/env python3
"""analyze_tracker.py — pcc-tracker-agent 的数据处理后端

读 progress/tracker.csv,生成 markdown 报告到 progress/tracker-analysis-{date}.md。

输入:tracker.csv (87 列,37 markers × Claude + DeepSeek + metadata)
输出:能力维度命中率 / 反复失守 marker / 反复 △ marker / 必命中项 / 真人锚点对比 / 下一步派单

用法:
    python3 scripts/analyze_tracker.py                          # 用默认路径
    python3 scripts/analyze_tracker.py --csv <path> --out <path> # 自定义
"""

import argparse
import csv
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


def load_rows(csv_path: Path) -> list[dict]:
    """读 tracker.csv,跳过 header,转成 dict 列表。"""
    with csv_path.open(newline="") as f:
        return list(csv.DictReader(f))


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
        hit_rate = (yes + 0.5 * part) / total * 100 if total else 0
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


def render_report(rows: list[dict], date: str) -> str:
    """生成 markdown 报告"""
    n = len(rows)
    judgments = marker_judgments(rows)
    comp_stats = competency_stats(rows)
    fails = repeated_failures(judgments, threshold=max(3, n // 2))
    partials = repeated_partial(judgments, threshold=max(3, n // 2))
    strengths = strength_zone(judgments)
    must_hit = must_hit_status(rows)

    md = [
        f"# Tracker 分析报告 — {date}(自动生成,{n} 场)",
        "",
        "> 来源:[progress/tracker.csv](tracker.csv)",
        "> 生成器:`scripts/analyze_tracker.py`",
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
    weighted = (total_yes + 0.5 * total_part) / total_all * 100 if total_all else 0
    md += [
        "",
        f"**总命中率(按权重,✔ + 0.5△):{weighted:.1f}%**",
        "",
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
        "## 📋 每场 summary",
        "",
        "| session_id | persona | 难度 | ✔ | △ | ✘ | 必命中 ✘ | 评估者 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        md.append(
            f"| {row['session_id']} | {row['persona']} | {row['difficulty']} "
            f"| {row['claude_total_✔']} | {row['claude_total_△']} "
            f"| {row['claude_total_✘']} | {row['must_hit_✘_count']} "
            f"| {row['judge_main']} |"
        )

    md += [
        "",
        "---",
        "",
        f"**生成时间**:{date}",
        f"**输入**:tracker.csv({n} 行)",
    ]
    return "\n".join(md) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_csv = Path(__file__).parent.parent / "progress" / "tracker.csv"
    default_out = default_csv.parent / f"tracker-analysis-{datetime.now():%Y-%m-%d}.md"
    parser.add_argument("--csv", type=Path, default=default_csv, help="tracker.csv 路径")
    parser.add_argument("--out", type=Path, default=default_out, help="输出报告路径")
    parser.add_argument("--print", action="store_true", help="同时打印到 stdout")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: tracker.csv not found at {args.csv}", file=sys.stderr)
        return 1

    rows = load_rows(args.csv)
    if not rows:
        print("ERROR: tracker.csv is empty", file=sys.stderr)
        return 1

    today = datetime.now().strftime("%Y-%m-%d")
    report = render_report(rows, today)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"✅ 报告已生成:{args.out}({len(rows)} 场)")

    if args.print:
        print("\n" + report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
