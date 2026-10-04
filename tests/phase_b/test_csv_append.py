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
"""Step 9 — CSV append unit tests."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.tracker.csv_append import (  # noqa: E402
    _load_header,
    append_row,
    append_session,
    build_row,
)


HEADER_95 = [
    "session_id", "date", "conversation_date", "conversation_time", "reeval_of",
    "persona", "difficulty", "topic", "judge_main", "judge_2",
] + [f"claude_{n}" for n in [
    "3.1", "3.2", "3.3", "3.4",
    "4.1", "4.2", "4.3", "4.4",
    "5.1", "5.2", "5.3", "5.4", "5.5",
    "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7",
    "7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8",
    "8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "8.9",
]] + [
    "claude_total_✔", "claude_total_△", "claude_total_✘",
    "must_hit_✘_count", "key_weakness",
] + [f"deepseek_{n}" for n in [
    "3.1", "3.2", "3.3", "3.4",
    "4.1", "4.2", "4.3", "4.4",
    "5.1", "5.2", "5.3", "5.4", "5.5",
    "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7",
    "7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8",
    "8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "8.9",
]] + [
    "claude_deepseek_agreement",
    "eval_version", "source_type", "audio_path", "transcript_path", "audio_quality_notes",
]


def _write_header(tmp_path: Path) -> Path:
    p = tmp_path / "tracker-sessions.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER_95)
    return p


def test_load_header(tmp_path: Path):
    p = _write_header(tmp_path)
    header = _load_header(p)
    assert len(header) == 95
    assert header[0] == "session_id"
    assert header[-1] == "audio_quality_notes"


def test_build_row_fills_known_fields_and_blanks_markers(tmp_path: Path):
    p = _write_header(tmp_path)
    header = _load_header(p)
    from datetime import datetime
    fixed_now = datetime(2026, 9, 3, 14, 30, 0)
    row = build_row(
        session_id="real-2026-09-03-99",
        persona="vec-01",
        difficulty=2,
        topic="压力管理",
        audio_path="sessions/raw/real-2026-09-03-99.wav",
        transcript_path="sessions/dialogues/real-2026-09-03-99.jsonl",
        header=header,
        now=fixed_now,
    )
    assert row["session_id"] == "real-2026-09-03-99"
    assert row["date"] == "2026-09-03"
    assert row["conversation_date"] == "2026-09-03"
    assert row["conversation_time"] == "14:30:00"
    assert row["persona"] == "vec-01"
    assert row["difficulty"] == "2"
    assert row["topic"] == "压力管理"
    assert row["source_type"] == "real"
    assert row["audio_path"] == "sessions/raw/real-2026-09-03-99.wav"
    assert row["transcript_path"] == "sessions/dialogues/real-2026-09-03-99.jsonl"
    # marker scoring columns must be blank in v1
    for col in header:
        if col.startswith("claude_") and col not in ("claude_total_✔", "claude_total_△", "claude_total_✘"):
            assert row[col] == "", f"expected blank, got {row[col]!r} for {col}"
    for col in header:
        if col.startswith("deepseek_"):
            assert row[col] == "", f"expected blank, got {row[col]!r} for {col}"
    assert row["claude_total_✔"] == ""
    assert row["must_hit_✘_count"] == ""
    assert row["key_weakness"] == ""
    assert row["claude_deepseek_agreement"] == ""
    assert row["eval_version"] == ""
    assert row["audio_quality_notes"] == ""
    assert row["reeval_of"] == ""
    assert row["judge_main"] == ""
    assert row["judge_2"] == ""


def test_append_row_preserves_header_order_and_count(tmp_path: Path):
    p = _write_header(tmp_path)
    header = _load_header(p)
    row = build_row(
        session_id="real-2026-09-03-01",
        persona="vec-01",
        difficulty=2,
        topic="t",
        audio_path="a.wav",
        transcript_path="t.jsonl",
        header=header,
    )
    append_row(csv_path=p, row=row)
    with open(p, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        lines = list(reader)
    assert len(lines) == 2  # header + 1 data row
    assert lines[0] == HEADER_95
    assert lines[1][0] == "real-2026-09-03-01"
    assert lines[1][header.index("source_type")] == "real"
    assert len(lines[1]) == 95


def test_append_session_uses_existing_csv(tmp_path: Path):
    p = _write_header(tmp_path)
    out = append_session(
        session_id="real-2026-09-03-02",
        persona="vec-02",
        difficulty=1,
        topic="情绪",
        audio_path="a2.wav",
        transcript_path="t2.jsonl",
        csv_path=p,
    )
    assert out == p
    with open(p, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["session_id"] == "real-2026-09-03-02"
    assert rows[0]["persona"] == "vec-02"


def test_append_session_missing_csv_raises(tmp_path: Path):
    import pytest
    missing = tmp_path / "nope.csv"
    with pytest.raises(FileNotFoundError):
        append_session(
            session_id="x",
            persona="vec-01",
            difficulty=0,
            topic="",
            audio_path="a",
            transcript_path="t",
            csv_path=missing,
        )


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
