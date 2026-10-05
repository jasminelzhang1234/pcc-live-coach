# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Gap 2 — sweep_expired_audio() unit tests."""
from __future__ import annotations

import os
import sys
import time
import wave
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.session.retention import sweep_expired_audio  # noqa: E402


def _make_old_wav(path: Path, days_old: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 100)  # tiny wav
    # Backdate mtime by N days.
    old_mtime = time.time() - days_old * 86400
    os.utime(str(path), (old_mtime, old_mtime))


def test_sweep_deletes_wav_older_than_threshold(tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _make_old_wav(sessions / "raw" / "real-2026-09-01-01.wav", days_old=31)
    _make_old_wav(sessions / "raw" / "real-2026-09-01-02.wav", days_old=5)

    deleted = sweep_expired_audio(sessions, retention_days=30)

    assert deleted == 1, "should delete exactly the 31-day-old file"
    assert (sessions / "raw" / "real-2026-09-01-01.wav").exists() is False
    assert (sessions / "raw" / "real-2026-09-01-02.wav").exists() is True


def test_sweep_zero_days_is_disabled(tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _make_old_wav(sessions / "raw" / "real-2026-01-01-01.wav", days_old=365)

    deleted = sweep_expired_audio(sessions, retention_days=0)

    assert deleted == 0, "retention=0 must disable sweep entirely"
    assert (sessions / "raw" / "real-2026-01-01-01.wav").exists() is True


def test_sweep_no_raw_dir_is_noop(tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()  # no raw/ subdir

    deleted = sweep_expired_audio(sessions, retention_days=30)

    assert deleted == 0


def test_sweep_empty_raw_dir(tmp_path: Path):
    sessions = tmp_path / "sessions"
    (sessions / "raw").mkdir(parents=True)

    deleted = sweep_expired_audio(sessions, retention_days=30)

    assert deleted == 0


def test_sweep_only_touches_raw_subdir(tmp_path: Path):
    """dialogue JSONL / rhythm JSONL / tracker CSV must NOT be deleted."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    # Old files in other subdirs — must survive.
    (sessions / "dialogues").mkdir(parents=True)
    (sessions / "rhythm").mkdir(parents=True)
    old_dlg = sessions / "dialogues" / "real-2026-01-01-01.jsonl"
    old_rhythm = sessions / "rhythm" / "real-2026-01-01-01.jsonl"
    old_dlg.write_text("{}")
    old_rhythm.write_text("{}")
    old_mtime = time.time() - 365 * 86400
    for p in (old_dlg, old_rhythm):
        os.utime(str(p), (old_mtime, old_mtime))

    deleted = sweep_expired_audio(sessions, retention_days=30)

    assert deleted == 0
    assert old_dlg.exists(), "dialogue JSONL must not be swept"
    assert old_rhythm.exists(), "rhythm JSONL must not be swept"
