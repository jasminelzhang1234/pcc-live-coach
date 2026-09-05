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
"""Per-turn rhythm feature extraction.

Reads a dialogue JSONL produced by SessionRecorder.write_dialogue() and
emits one JSONL line per coach turn with rhythm features:

  {
    "turn": 1,
    "ts": 1234567890,
    "coach_chars": 42,
    "coach_dur_ms": 2300,           # coach commit -> client reply text
    "cpm": 1095,
    "cpm_band": "fast",
    "pre_silence_ms": 4500,
    "silence_5_5": true,
    "client_filled_silence": false,
    "barge_in_count": 0,
    "client_interruption_by_coach_ms": 0,
    "speaker_role": "coach"
  }

Designed to run post-session as a CLI:
    python -m phase_b.rhythm.turn_features sessions/dialogues/<id>.jsonl \\
        --out sessions/rhythm/<id>.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, TextIO

from phase_b.rhythm.barge_in import collect_barge_ins, client_interruption_by_coach_ms
from phase_b.rhythm.cpm import cpm, cpm_band, count_chars
from phase_b.rhythm.silence import detect_silence


logger = logging.getLogger(__name__)


def _iter_dialogue(path: Path) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("skip bad dialogue line: %s", e)


def extract_turn_features(
    dialogue_path: Path,
    out_path: Optional[Path] = None,
    out_fh: Optional[TextIO] = None,
) -> List[Dict[str, Any]]:
    """Compute per-turn features for a session dialogue.

    Either `out_path` (writes a JSONL file) or `out_fh` (writes to an
    already-open file handle) must be provided to capture the output.
    Pass both=None to get the list in memory only.
    """
    if out_path is None and out_fh is None:
        out_fh_target: Optional[TextIO] = None
    elif out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_fh_target = open(out_path, "w", encoding="utf-8")
    else:
        out_fh_target = out_fh

    features: List[Dict[str, Any]] = []
    # Per-turn accumulators (keyed by turn number).
    coach_text_by_turn: Dict[int, str] = {}
    coach_ms_by_turn: Dict[int, int] = {}
    client_ms_by_turn: Dict[int, int] = {}
    barge_in_by_turn: Dict[int, List[int]] = {}

    # We must process events in order to know which client utterances
    # intervene before each coach commit (for silence_5_5 detection).
    events = list(_iter_dialogue(dialogue_path))

    # First pass: bucket events by turn number.
    for ev in events:
        role = ev.get("role")
        turn = ev.get("turn")
        if not isinstance(turn, int):
            continue
        ms = ev.get("ms")
        if not isinstance(ms, int):
            continue
        if role == "coach" and ev.get("event") == "utterance":
            coach_text_by_turn[turn] = ev.get("text", "")
            coach_ms_by_turn[turn] = ms
        elif role == "client" and ev.get("event") == "utterance":
            client_ms_by_turn[turn] = ms
        elif role == "_meta" and ev.get("event") == "barge_in":
            barge_in_by_turn.setdefault(turn, []).append(ms)

    # Determine chronological order of events (so we can find client
    # utterances that intervene between two coach turns).
    event_order: List[Dict[str, Any]] = []
    for ev in events:
        if isinstance(ev.get("turn"), int) and isinstance(ev.get("ms"), int):
            event_order.append(ev)
    event_order.sort(key=lambda e: (e["ms"], e.get("turn", 0)))

    # Second pass: emit one feature line per coach turn in turn order.
    turn_numbers = sorted(coach_ms_by_turn.keys())
    prev_event_ms = 0
    for turn in turn_numbers:
        coach_text = coach_text_by_turn.get(turn, "")
        coach_ms = coach_ms_by_turn[turn]
        client_ms = client_ms_by_turn.get(turn, coach_ms)
        barge_in_events = barge_in_by_turn.get(turn, [])
        # Find intervening client utterances: any client whose ms falls
        # in (prev_event_ms, coach_ms).
        intervening_client = [
            ev["ms"] for ev in event_order
            if ev.get("role") == "client"
            and ev.get("event") == "utterance"
            and prev_event_ms < ev["ms"] < coach_ms
        ]
        silence = detect_silence(
            coach_turn_ms=coach_ms,
            previous_event_ms=prev_event_ms,
            intervening_client_ms=intervening_client,
        )
        chars = count_chars(coach_text)
        dur_ms = max(0, client_ms - coach_ms)
        cpm_val = cpm(chars, dur_ms)
        barge_stats = collect_barge_ins(barge_in_events)
        feature = {
            "turn": turn,
            "ts": coach_ms,
            "coach_chars": chars,
            "coach_dur_ms": dur_ms,
            "cpm": cpm_val,
            "cpm_band": cpm_band(cpm_val),
            "pre_silence_ms": silence.pre_silence_ms,
            "silence_5_5": silence.silence_5_5,
            "client_filled_silence": silence.client_filled,
            "barge_in_count": barge_stats.barge_in_count,
            "client_interruption_by_coach_ms": client_interruption_by_coach_ms(coach_ms, []),
            "speaker_role": "coach",
        }
        features.append(feature)
        if out_fh_target is not None:
            out_fh_target.write(json.dumps(feature, ensure_ascii=False) + "\n")
            out_fh_target.flush()
        # Next coach turn's previous event is this turn's client reply time.
        prev_event_ms = client_ms

    if out_fh_target is not None and out_path is not None:
        out_fh_target.close()

    return features


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract per-turn rhythm features from a session dialogue JSONL."
    )
    parser.add_argument("dialogue", type=Path, help="input dialogue JSONL")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="output rhythm JSONL path (will be overwritten)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not args.dialogue.is_file():
        print(f"dialogue not found: {args.dialogue}", file=sys.stderr)
        return 2
    features = extract_turn_features(args.dialogue, out_path=args.out)
    print(f"[rhythm] wrote {len(features)} turn(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
