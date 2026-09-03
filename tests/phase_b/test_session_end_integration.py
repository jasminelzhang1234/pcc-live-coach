# Copyright 2026 the maintainer Zhang. Licensed under the Apache License, Version 2.0
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
"""Step 9 — manager end-to-end + CSV resilience.

Verifies that SessionManager.end():
  1. always writes the rhythm JSONL (Step 8)
  2. appends a row to the tracker CSV if it exists
  3. logs and continues if the tracker CSV is missing (defensive — the
     CSV might not be checked in yet on a fresh clone)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import csv  # noqa: E402
import tempfile  # noqa: E402

from phase_b.config import get_settings  # noqa: E402
from phase_b.session.manager import SessionManager  # noqa: E402


def test_end_writes_rhythm_jsonl(tmp_path: Path):
    """Even without a tracker CSV, rhythm must be written."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    # Use a tracker CSV path that does not exist — manager.end() must
    # log a warning and continue, NOT crash.
    missing_csv = tmp_path / "nope.csv"
    # Monkey-patch get_settings to return our missing CSV path.
    s = get_settings()
    # Settings is frozen — patch via env var instead.
    import os
    os.environ["TRACKER_CSV"] = str(missing_csv)
    # Reset cached settings.
    import importlib
    import phase_b.config as cfg_mod
    importlib.reload(cfg_mod)
    from phase_b.session import manager as mgr_mod
    importlib.reload(mgr_mod)

    try:
        mgr = mgr_mod.SessionManager(sessions_dir=str(sessions_dir))
        state = mgr.start(persona_id="vec-01", topic="t", difficulty=0)
        state.recorder.write_dialogue({"role": "coach", "event": "utterance", "turn": 1, "text": "hi", "ms": 1000})
        state.recorder.write_dialogue({"role": "client", "event": "utterance", "turn": 1, "text": "hello", "ms": 3000})
        # Capture log warnings to assert the warning is emitted.
        caplog = []
        handler = logging.Handler()
        handler.emit = lambda rec: caplog.append(rec.getMessage())
        mgr_logger = logging.getLogger("phase_b.session.manager")
        mgr_logger.addHandler(handler)
        try:
            mgr.end(state.id)
        finally:
            mgr_logger.removeHandler(handler)
        # Rhythm JSONL must exist.
        assert Path(state.recorder.rhythm_path).exists()
        # Warning must have been logged about the missing tracker CSV.
        assert any("tracker CSV not found" in m for m in caplog), caplog
    finally:
        # Restore env + reload modules so other tests aren't affected.
        os.environ.pop("TRACKER_CSV", None)
        importlib.reload(cfg_mod)
        importlib.reload(mgr_mod)


def test_end_appends_to_existing_csv(tmp_path: Path):
    """When the tracker CSV exists, a row must be appended."""
    # Build a minimal 95-col CSV in tmp.
    real_csv = PROJECT_ROOT / "progress" / "tracker-real-sessions.csv"
    target_csv = tmp_path / "tracker.csv"
    target_csv.write_bytes(real_csv.read_bytes())  # copy header + any rows
    rows_before = sum(1 for _ in open(target_csv, encoding="utf-8")) - 1  # minus header

    import os
    os.environ["TRACKER_CSV"] = str(target_csv)
    import importlib
    import phase_b.config as cfg_mod
    importlib.reload(cfg_mod)
    from phase_b.session import manager as mgr_mod
    importlib.reload(mgr_mod)

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    try:
        mgr = mgr_mod.SessionManager(sessions_dir=str(sessions_dir))
        state = mgr.start(persona_id="vec-09", topic="压力测试", difficulty=3)
        state.recorder.write_dialogue({"role": "coach", "event": "utterance", "turn": 1, "text": "hi", "ms": 1000})
        state.recorder.write_dialogue({"role": "client", "event": "utterance", "turn": 1, "text": "hello", "ms": 3000})
        mgr.end(state.id)
        with open(target_csv, encoding="utf-8") as f:
            rows_after = list(csv.DictReader(f))
        assert len(rows_after) == rows_before + 1
        last = rows_after[-1]
        assert last["session_id"] == state.id
        assert last["persona"] == "vec-09"
        assert last["difficulty"] == "3"
        assert last["source_type"] == "real"
        assert last["topic"] == "压力测试"
    finally:
        os.environ.pop("TRACKER_CSV", None)
        importlib.reload(cfg_mod)
        importlib.reload(mgr_mod)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
