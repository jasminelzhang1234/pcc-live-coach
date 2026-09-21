#!/usr/bin/env python3
"""regen_token_reports.py — 每次 session 结束后,自动重新生成两个 token HTML 报告。

被 .claude/settings.json 的 Stop hook 链调用(在 hook_token_usage.py 之后)。

跑 3 个 sub-script:
  1. backfill_token_usage.py     → progress/token-usage-backfilled-{date}.csv
  2. gen_token_dashboard.py      → observability/token-usage-dashboard-{date}.html (旧 dashboard)
  3. gen_spending_report.py      → progress/token-spending-report-{date}.html (新 spending report)

设计原则:
  - 任一脚本失败不阻塞(hook 永远 exit 0)
  - 单脚本超时 60s
  - 总耗时 ~7-10s / session,完全异步不阻塞主流程
  - 环境变量 HOOK_TOKEN_REGEN_DRY_RUN=1 可 dry-run

调用顺序很重要:
  hook_token_usage.py → 本脚本 → dashboard + spending 立即反映新 session
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.now().strftime("%Y-%m-%d")

PLAN = [
    (
        "backfill_token_usage.py",
        [sys.executable, str(ROOT / "scripts" / "backfill_token_usage.py")],
        ROOT / "progress" / f"token-usage-backfilled-{TODAY}.csv",
    ),
    (
        "gen_token_dashboard.py",
        [sys.executable, str(ROOT / "scripts" / "gen_token_dashboard.py")],
        ROOT / "observability" / f"token-usage-dashboard-{TODAY}.html",
    ),
    (
        "gen_spending_report.py",
        [sys.executable, str(ROOT / "scripts" / "gen_spending_report.py")],
        ROOT / "progress" / f"token-spending-report-{TODAY}.html",
    ),
]

TIMEOUT_S = 60


def run_step(label: str, cmd: list[str], expected: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd, cwd=ROOT,
            capture_output=True, text=True,
            timeout=TIMEOUT_S,
        )
        if result.returncode == 0:
            ok = expected.exists()
            msg = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else "ok"
            return ok, msg
        err = (result.stderr or result.stdout or "").strip()
        return False, err.splitlines()[-1] if err else f"exit={result.returncode}"
    except subprocess.TimeoutExpired:
        return False, f"timeout (>{TIMEOUT_S}s)"
    except Exception as e:
        return False, f"exception: {e}"


def main() -> int:
    dry = os.environ.get("HOOK_TOKEN_REGEN_DRY_RUN") == "1"
    if dry:
        print(f"[hook DRY-RUN] {TODAY} 会跑:", file=sys.stderr)
        for label, cmd, out in PLAN:
            print(f"  {' '.join(cmd)} → {out.relative_to(ROOT)}", file=sys.stderr)
        return 0

    print(f"[hook] regen token reports ({TODAY})...", file=sys.stderr)
    results = []
    for label, cmd, expected in PLAN:
        ok, msg = run_step(label, cmd, expected)
        results.append((label, ok, msg))

    for label, ok, msg in results:
        icon = "✅" if ok else "⚠️"
        print(f"[hook] {icon} {label}: {msg[:160]}", file=sys.stderr)

    # 失败也不阻塞
    return 0


if __name__ == "__main__":
    sys.exit(main())