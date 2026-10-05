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
`progress/tracker-sessions.csv` and appends one row per session
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
from typing import Any, Dict, List, Optional, Tuple

from phase_b.config import get_settings


logger = logging.getLogger(__name__)


DEFAULT_TRACKER_CSV = "progress/tracker-sessions.csv"


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
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
    llm_model_used: str = "",
    asr_minutes: float = 0.0,
) -> Dict[str, str]:
    """Construct a row dict matching the given 95-col header.

    Unknown header columns are filled with empty strings. The marker
    scoring columns (claude_*, deepseek_*, totals, etc.) are intentionally
    blank — v1 only registers the session.

    Gap 3 additions: pass llm_* and asr_* to surface cost attribution in
    the tracker CSV. If the canonical header doesn't include the new
    columns yet, they're dropped silently (defensive).
    """
    now = now or datetime.now()
    # Compute cost in USD using the canonical pricing table.
    llm_cost_usd = ""
    asr_cost_usd = ""
    if "llm_cost_usd" in header:
        try:
            from phase_b.llm.cost import llm_cost_usd as _calc_llm, asr_cost_usd as _calc_asr
            llm_cost_usd = f"{_calc_llm(llm_model_used, llm_input_tokens, llm_output_tokens):.6f}"
            asr_cost_usd = f"{_calc_asr(asr_minutes):.6f}"
        except Exception:
            llm_cost_usd = ""
            asr_cost_usd = ""
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
        # Gap 3: cost columns.
        "llm_input_tokens": str(llm_input_tokens) if "llm_input_tokens" in header else "",
        "llm_output_tokens": str(llm_output_tokens) if "llm_output_tokens" in header else "",
        "llm_model_used": llm_model_used if "llm_model_used" in header else "",
        "llm_cost_usd": llm_cost_usd,
        "asr_minutes": f"{asr_minutes:.3f}" if "asr_minutes" in header else "",
        "asr_cost_usd": asr_cost_usd,
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

    Uses an in-process dict cache keyed by csv_path (header + rows +
    session_id index). First call loads O(n); later calls in the same
    process are O(1) lookup + O(n) full-file rewrite (CSV has no
    random-access insert). Total cost for n upserts in one process: O(n)
    instead of the un-cached O(n²).

    Returns:
        "inserted"  — no prior row for this session_id
        "replaced"  — prior row was found and dropped before insert
        "no_csv"    — csv_path missing; caller decides whether that's a 404
    """
    header, rows, index = _load_cache(csv_path)
    if rows is None:
        return "no_csv"
    session_id = row.get("session_id", "")
    if session_id and session_id in index:
        rows[index[session_id]] = row
        replaced = True
    else:
        rows.append(row)
        if session_id:
            index[session_id] = len(rows) - 1
        replaced = False
    _write_cache(csv_path, header, rows)
    logger.info(
        "%s row session_id=%s -> %s", "replaced" if replaced else "inserted", session_id, csv_path,
    )
    return "replaced" if replaced else "inserted"


# --- In-process cache -------------------------------------------------------
# Cache key = resolved csv_path. Value = (header, rows, index_by_session_id).
# `rows` is None when the file does not exist on first lookup.
# Note: this cache assumes upsert_session_row is the only writer; external
# writers (CI / dashboards) MUST call flush_cache(csv_path) afterwards to
# stay consistent. Tests get unique tmp_paths so no cross-test pollution.
_CSV_CACHE: Dict[Path, Tuple[List[str], Optional[List[Dict[str, str]]], Dict[str, int]]] = {}


def _load_cache(
    csv_path: Path,
) -> tuple[list[str], Optional[list[Dict[str, str]]], dict[str, int]]:
    """Return (header, rows, index). rows is None if csv_path doesn't exist."""
    cached = _CSV_CACHE.get(csv_path)
    if cached is not None:
        return cached
    if not csv_path.is_file():
        _CSV_CACHE[csv_path] = ([], None, {})
        return _CSV_CACHE[csv_path]
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"tracker CSV has no header: {csv_path}")
        raw_rows = [r for r in reader if r]
    index: dict[str, int] = {}
    for i, r in enumerate(raw_rows):
        if r and r[0]:
            index[r[0]] = i
    rows: list[Dict[str, str]] = [dict(zip(header, r)) for r in raw_rows]
    _CSV_CACHE[csv_path] = (header, rows, index)
    return _CSV_CACHE[csv_path]


def _write_cache(csv_path: Path, header: list[str], rows: list[Dict[str, str]]) -> None:
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in rows:
            writer.writerow([r.get(col, "") for col in header])


def flush_cache(csv_path: Optional[Path] = None) -> None:
    """Drop cached CSV state. Pass a specific path to drop just one entry,
    or omit to drop the entire cache (e.g. between test runs).
    """
    if csv_path is None:
        _CSV_CACHE.clear()
    else:
        _CSV_CACHE.pop(csv_path, None)


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
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
    llm_model_used: str = "",
    asr_minutes: float = 0.0,
) -> Path:
    """Convenience: load header from CSV, build row, append, return path.

    Gap 3 additions: pass llm_* and asr_* kwargs to surface cost in the
    tracker CSV row.
    """
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
        llm_input_tokens=llm_input_tokens,
        llm_output_tokens=llm_output_tokens,
        llm_model_used=llm_model_used,
        asr_minutes=asr_minutes,
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
