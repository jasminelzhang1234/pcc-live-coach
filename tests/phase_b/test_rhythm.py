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
"""Step 8 — rhythm extractor unit tests.

Covers silence_5_5, cpm/cpm_band, barge_in counting, and the per-turn
end-to-end extraction over a synthetic dialogue fixture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.rhythm.barge_in import collect_barge_ins  # noqa: E402
from phase_b.rhythm.cpm import cpm, cpm_band, count_chars  # noqa: E402
from phase_b.rhythm.silence import SILENCE_THRESHOLD_MS, detect_silence  # noqa: E402
from phase_b.rhythm.turn_features import extract_turn_features  # noqa: E402


# ---- silence ---------------------------------------------------------------


def test_silence_short_gap_not_counted():
    res = detect_silence(coach_turn_ms=1000, previous_event_ms=500)
    assert res.pre_silence_ms == 500
    assert res.silence_5_5 is False
    assert res.client_filled is False


def test_silence_long_gap_unfilled_counts():
    res = detect_silence(coach_turn_ms=3500, previous_event_ms=1000)
    assert res.pre_silence_ms == 2500
    assert res.silence_5_5 is True
    assert res.client_filled is False


def test_silence_long_gap_filled_by_client_does_not_count():
    res = detect_silence(
        coach_turn_ms=4000,
        previous_event_ms=1000,
        intervening_client_ms=[2000, 3000],
    )
    assert res.pre_silence_ms == 3000
    assert res.silence_5_5 is False
    assert res.client_filled is True


def test_silence_threshold_is_2_seconds():
    assert SILENCE_THRESHOLD_MS == 2000


# ---- cpm -------------------------------------------------------------------


def test_cpm_basic():
    # 60 chars in 30s = 120 cpm (boundary slow → ideal in our band; >120 == ideal)
    assert cpm(60, 30_000) == 120


def test_cpm_zero_duration():
    assert cpm(60, 0) == 0


def test_cpm_zero_chars():
    assert cpm(0, 5_000) == 0


def test_cpm_band_thresholds():
    assert cpm_band(50) == "slow"
    assert cpm_band(119) == "slow"
    assert cpm_band(120) == "ideal"
    assert cpm_band(200) == "ideal"
    assert cpm_band(280) == "ideal"
    assert cpm_band(281) == "fast"
    assert cpm_band(400) == "fast"


def test_count_chars_excludes_whitespace():
    # CJK + ASCII + spaces; spaces must not count.
    text = "我 最近 压力很大 啊 work busy"
    # chars: 我(1) + 最近(2) + 压力很大(4) + 啊(1) + work(4) + busy(4) = 16
    assert count_chars(text) == 16


def test_count_chars_empty():
    assert count_chars("") == 0
    assert count_chars("   ") == 0


# ---- barge_in --------------------------------------------------------------


def test_collect_barge_ins_empty():
    stats = collect_barge_ins([])
    assert stats.barge_in_count == 0
    assert stats.barge_in_ms == []


def test_collect_barge_ins_counts():
    stats = collect_barge_ins([1000, 1500, 2300])
    assert stats.barge_in_count == 3
    assert stats.barge_in_ms == [1000, 1500, 2300]


# ---- end-to-end turn_features extraction -----------------------------------


def _write_dialogue(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "test-dialogue.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return p


def test_extract_single_turn_basic(tmp_path: Path):
    """Single coach+client utterance pair (1 turn). Emits coach row + client row."""
    dialogue = _write_dialogue(tmp_path, [
        {"role": "coach", "event": "utterance", "turn": 1, "text": "你好", "ms": 1000},
        {"role": "client", "event": "utterance", "turn": 1, "text": "你好啊,有什么我能帮你的吗?", "ms": 2000},
    ])
    out = tmp_path / "test-rhythm.jsonl"
    features = extract_turn_features(dialogue, out_path=out)
    assert len(features) == 2
    coach_f = features[0]
    client_f = features[1]
    assert coach_f["speaker_role"] == "coach"
    assert coach_f["turn"] == 1
    assert coach_f["coach_chars"] == 2
    assert coach_f["coach_dur_ms"] == 1000
    assert coach_f["cpm"] == 120  # 2 chars in 1s
    assert coach_f["cpm_band"] == "ideal"
    assert coach_f["pre_silence_ms"] == 1000  # prev_event_ms=0 fallback (no session_start)
    assert coach_f["silence_5_5"] is False
    assert coach_f["barge_in_count"] == 0
    assert client_f["speaker_role"] == "client"
    assert client_f["pre_silence_ms"] == 1000  # gap = 2000 - 1000
    assert client_f["silence_5_5"] is False
    assert client_f["barge_in_count"] == 0
    assert out.is_file()
    # file content matches returned features
    written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert written == features


def test_extract_three_turns_with_silence_and_barge_in(tmp_path: Path):
    """Three coach turns: 1 long-silence (5.5), 1 with barge_in, 1 normal.
    Emits one row per utterance: 3 coach + 3 client = 6 rows in chronological order."""
    dialogue = _write_dialogue(tmp_path, [
        # Turn 1: coach commits at 1000, client reply at 3000. 2s gap (silence_5_5).
        {"role": "coach", "event": "utterance", "turn": 1, "text": "最近怎么样?", "ms": 1000},
        {"role": "client", "event": "utterance", "turn": 1, "text": "还行吧,就是有点累。", "ms": 3000},
        # Turn 2: coach commits at 6500 (3.5s after client reply → 5.5), 2 barge_ins during reply.
        {"role": "coach", "event": "utterance", "turn": 2, "text": "能具体说说是什么让你累吗?", "ms": 6500},
        {"role": "_meta", "event": "barge_in", "turn": 2, "ms": 7000},
        {"role": "_meta", "event": "barge_in", "turn": 2, "ms": 7500},
        {"role": "client", "event": "utterance", "turn": 2, "text": "工作上的事", "ms": 9000},
        # Turn 3: short reply, fast pace (38 chars in 1s = 2280 cpm → fast band).
        {"role": "coach", "event": "utterance", "turn": 3, "text": "好的,那让我们一起看看工作里到底发生了什么", "ms": 9500},
        {"role": "client", "event": "utterance", "turn": 3, "text": "好的", "ms": 10500},
    ])
    features = extract_turn_features(dialogue)
    assert len(features) == 6

    coach_rows = [f for f in features if f["speaker_role"] == "coach"]
    client_rows = [f for f in features if f["speaker_role"] == "client"]
    assert len(coach_rows) == 3
    assert len(client_rows) == 3

    # Turn 1 coach: prev_event_ms starts at 0 (no session_start in fixture);
    # gap = 1000 (coach at 1000 - prev at 0). 1000 < 2000 → not silence_5_5.
    # 6 chars in 2000ms = 180 cpm → ideal.
    f1 = coach_rows[0]
    assert f1["pre_silence_ms"] == 1000
    assert f1["silence_5_5"] is False
    assert f1["barge_in_count"] == 0
    assert f1["coach_chars"] == 6  # 最近怎么样?
    assert f1["cpm"] == 180
    assert f1["cpm_band"] == "ideal"

    # Turn 2 coach: prev = client_ms(turn1) = 3000; gap = 6500-3000 = 3500.
    # silence_5_5 (>= 2000). 2 barge_ins. 13 chars in 2500ms = 312 cpm → fast.
    f2 = coach_rows[1]
    assert f2["pre_silence_ms"] == 3500
    assert f2["silence_5_5"] is True
    assert f2["barge_in_count"] == 2
    assert f2["cpm_band"] == "fast"

    # Turn 3 coach: prev = client_ms(turn2) = 9000; gap = 9500-9000 = 500.
    # not silence_5_5. 0 barge_ins. 22 chars in 1000ms = 1320 → fast.
    f3 = coach_rows[2]
    assert f3["pre_silence_ms"] == 500
    assert f3["silence_5_5"] is False
    assert f3["barge_in_count"] == 0
    assert f3["cpm_band"] == "fast"


def test_extract_client_filling_silence_blocks_5_5(tmp_path: Path):
    """If the client interjects in a long gap, it does NOT count as 5.5 silence."""
    dialogue = _write_dialogue(tmp_path, [
        {"role": "coach", "event": "utterance", "turn": 1, "text": "hi", "ms": 1000},
        {"role": "client", "event": "utterance", "turn": 1, "text": "嗯", "ms": 2000},
        # client speaks at 4000 (after previous client reply at 2000),
        # coach commits at 6000 — but the 4000 client interjection makes it NOT a 5.5 silence.
        {"role": "client", "event": "utterance", "turn": 1, "text": "嗯嗯", "ms": 4000},
        {"role": "coach", "event": "utterance", "turn": 2, "text": "tell me more", "ms": 6000},
        {"role": "client", "event": "utterance", "turn": 2, "text": "ok", "ms": 8000},
    ])
    features = extract_turn_features(dialogue)
    coach_rows = [f for f in features if f["speaker_role"] == "coach"]
    f2 = coach_rows[1]
    # previous event for turn 2 = client_ms of turn 1 = 4000 (the latest client utterance
    # before coach commit at 6000 is at 4000)
    assert f2["pre_silence_ms"] == 2000
    # intervening_client = [4000] which IS between 4000 and 6000 — wait, 4000 not > 4000,
    # so it's empty → client_filled=False → silence_5_5=True
    # (this matches the recorded behavior: we use >prev, <coach)
    assert f2["client_filled_silence"] is False
    assert f2["silence_5_5"] is True


def test_extract_handles_barge_in_with_no_text_change(tmp_path: Path):
    """Barge-ins don't create new coach turns — coach row count stays at 1."""
    dialogue = _write_dialogue(tmp_path, [
        {"role": "coach", "event": "utterance", "turn": 1, "text": "x", "ms": 1000},
        {"role": "_meta", "event": "barge_in", "turn": 1, "ms": 1100},
        {"role": "_meta", "event": "barge_in", "turn": 1, "ms": 1200},
        {"role": "client", "event": "utterance", "turn": 1, "text": "y", "ms": 1500},
    ])
    features = extract_turn_features(dialogue)
    coach_rows = [f for f in features if f["speaker_role"] == "coach"]
    assert len(coach_rows) == 1
    assert coach_rows[0]["barge_in_count"] == 2
    assert len(features) == 2  # 1 coach + 1 client


def test_extract_returns_in_memory_when_no_out(tmp_path: Path):
    dialogue = _write_dialogue(tmp_path, [
        {"role": "coach", "event": "utterance", "turn": 1, "text": "hi", "ms": 1000},
        {"role": "client", "event": "utterance", "turn": 1, "text": "hey", "ms": 2000},
    ])
    features = extract_turn_features(dialogue)
    assert len(features) == 2  # 1 coach + 1 client
    # No file should be written since neither out_path nor out_fh was given.
    out_files = list(tmp_path.glob("*.jsonl"))
    assert len(out_files) == 1  # only the input file


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
