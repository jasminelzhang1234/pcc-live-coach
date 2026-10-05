#!/usr/bin/env python3
"""recover_orphan_sessions.py — Gap 4 (crash recovery).

After a server crash mid-session, dialogue JSONL + WAV are still on disk
(thanks to Gap 2's incremental-flush design), but the in-memory
SessionManager is empty. This script scans the disk for orphaned sessions
and reports them so the coach can decide whether to re-import them.

Usage:
    python scripts/recover_orphan_sessions.py [--sessions-dir PATH]

Output:
    For each raw/<id>.wav, print: id, mtime, size, has_dialogue.
    Orphan = on-disk audio not tracked in any in-memory state (always true
    after server restart).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for orphaned session audio.")
    parser.add_argument(
        "--sessions-dir",
        default="practice-logs/sessions",
        help="Path to sessions dir (default: practice-logs/sessions)",
    )
    parser.add_argument(
        "--min-age-hours",
        type=float,
        default=0.0,
        help="Only report files at least this old (skip fresh in-flight sessions)",
    )
    args = parser.parse_args(argv)

    sessions_dir = Path(args.sessions_dir).resolve()
    raw = sessions_dir / "raw"
    if not raw.is_dir():
        print(f"no raw/ dir at {raw}; nothing to scan.")
        return 0

    import time
    cutoff = time.time() - args.min_age_hours * 3600 if args.min_age_hours else 0

    found = 0
    for wav in sorted(raw.glob("real-*.wav")):
        try:
            mtime = wav.stat().st_mtime
        except FileNotFoundError:
            continue
        if mtime < cutoff:
            continue
        sid = wav.stem
        dlg = sessions_dir / "dialogues" / f"{sid}.jsonl"
        has_dlg = dlg.is_file()
        size = wav.stat().st_size
        # Quick dialogue line count.
        dlg_lines = 0
        if has_dlg:
            try:
                with dlg.open(encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            dlg_lines += 1
            except Exception:
                pass
        print(
            f"  {sid}  size={size:>9} B  mtime={mtime:.0f}  "
            f"dialogue={'yes ('+str(dlg_lines)+' lines)' if has_dlg else 'NO (orphan)'}"
        )
        found += 1

    if found == 0:
        print("no session audio found.")
    else:
        print(
            f"\n{found} session(s) on disk. Sessions with dialogue='NO' had their "
            "recording interrupted mid-session; dialogue='yes' ones are "
            "fully recoverable via GET /api/sessions?with_audio=true."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
