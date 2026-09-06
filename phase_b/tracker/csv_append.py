# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""CSV append for real-voice sessions.

Reads the existing 95-column header from
`progress/tracker-real-sessions.csv` and appends one row per session
with all marker scoring columns empty. Marker scoring is out of scope
for v1; this module only registers the session so the dashboard can
find it.

CLI:
    python -m phase_b.tracker.csv_append \\
        --session-id real-2026-09-03-01 \\
        --persona vec-01 \\
        --difficulty 2 \\
        --topic "压力管理" \\
        --audio-path sessions/raw/real-2026-09-03-01.wav \\
        --transcript-path sessions/dialogues/real-2026-09-03-01.jsonl
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from phase_b.config import get_settings


logger = logging.getLogger(__name__)


DEFAULT_TRACKER_CSV = "progress/tracker-real-sessions.csv"


def _load_header(csv_path: Path) -> list[str]:
    """Read the first row of the CSV as the column header."""
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"tracker CSV has no header: {csv_path}")
    return header


def build_row(
    *,
    session_id: str,
    persona: str,
    difficulty: int,
    topic: str,
    audio_path: str,
    transcript_path: str,
    header: list[str],
    now: Optional[datetime] = None,
    reeval_of: str = "",
    judge_main: str = "",
    judge_2: str = "",
    audio_quality_notes: str = "",
) -> Dict[str, str]:
    """Construct a row dict matching the given 95-col header.

    Unknown header columns are filled with empty strings. The marker
    scoring columns (claude_*, deepseek_*, totals, etc.) are intentionally
    blank — v1 only registers the session.
    """
    now = now or datetime.now()
    # Build a map of known fields by header name.
    known: Dict[str, str] = {
        "session_id": session_id,
        "date": now.strftime("%Y-%m-%d"),
        "conversation_date": now.strftime("%Y-%m-%d"),
        "conversation_time": now.strftime("%H:%M:%S"),
        "reeval_of": reeval_of,
        "persona": persona,
        "difficulty": str(difficulty),
        "topic": topic,
        "judge_main": judge_main,
        "judge_2": judge_2,
        "source_type": "real",
        "audio_path": audio_path,
        "transcript_path": transcript_path,
        "audio_quality_notes": audio_quality_notes,
    }
    row: Dict[str, str] = {}
    for col in header:
        row[col] = known.get(col, "")
    return row


def append_row(
    *,
    csv_path: Path,
    row: Dict[str, str],
) -> None:
    """Append one row to the CSV, preserving header order.

    Uses csv.DictWriter with append mode + newline='' per stdlib guidance.
    If the file does not exist, write the header first (defensive — the
    file should already exist with the canonical header).
    """
    header = list(row.keys())
    file_exists = csv_path.is_file()
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    logger.info("appended row session_id=%s -> %s", row.get("session_id"), csv_path)


def upsert_session_row(
    *,
    csv_path: Path,
    row: Dict[str, str],
) -> str:
    """Idempotent insert: if `session_id` already exists in the CSV, drop
    the old row first; then append the new row.

    Returns:
        "inserted"  — no prior row for this session_id
        "replaced"  — prior row was found and dropped before insert
        "no_csv"    — csv_path missing; caller decides whether that's a 404
    """
    if not csv_path.is_file():
        return "no_csv"
    session_id = row.get("session_id", "")
    # Read all rows, drop any matching session_id, then rewrite the file.
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            header = list(row.keys())
        rows = [r for r in reader if r and (len(r) == 0 or r[0] != session_id)]
    replaced = False
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            next(reader)  # header
            for r in reader:
                if r and r[0] == session_id:
                    replaced = True
                    break
        except StopIteration:
            pass
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        # Re-emit only the surviving rows (everything except the duplicate).
        for r in rows:
            if r:
                writer.writerow(r)
        writer.writerow([row.get(col, "") for col in header])
    logger.info(
        "%s row session_id=%s -> %s", "replaced" if replaced else "inserted", session_id, csv_path,
    )
    return "replaced" if replaced else "inserted"


def append_session(
    *,
    session_id: str,
    persona: str,
    difficulty: int,
    topic: str,
    audio_path: str,
    transcript_path: str,
    csv_path: Optional[Path] = None,
    reeval_of: str = "",
    audio_quality_notes: str = "",
) -> Path:
    """Convenience: load header from CSV, build row, append, return path."""
    if csv_path is None:
        try:
            settings_root = Path(get_settings().project_root)
        except Exception:
            settings_root = Path.cwd()
        csv_path = settings_root / DEFAULT_TRACKER_CSV
    if not csv_path.is_file():
        raise FileNotFoundError(f"tracker CSV not found: {csv_path}")
    header = _load_header(csv_path)
    row = build_row(
        session_id=session_id,
        persona=persona,
        difficulty=difficulty,
        topic=topic,
        audio_path=audio_path,
        transcript_path=transcript_path,
        header=header,
        reeval_of=reeval_of,
        audio_quality_notes=audio_quality_notes,
    )
    append_row(csv_path=csv_path, row=row)
    return csv_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Append a real-voice session row to the tracker CSV.")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--persona", required=True)
    parser.add_argument("--difficulty", type=int, default=0)
    parser.add_argument("--topic", default="")
    parser.add_argument("--audio-path", required=True)
    parser.add_argument("--transcript-path", required=True)
    parser.add_argument("--reeval-of", default="")
    parser.add_argument("--audio-quality-notes", default="")
    parser.add_argument("--csv", type=Path, default=None, help="override tracker CSV path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        path = append_session(
            session_id=args.session_id,
            persona=args.persona,
            difficulty=args.difficulty,
            topic=args.topic,
            audio_path=args.audio_path,
            transcript_path=args.transcript_path,
            csv_path=args.csv,
            reeval_of=args.reeval_of,
            audio_quality_notes=args.audio_quality_notes,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"[tracker] appended {args.session_id} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
