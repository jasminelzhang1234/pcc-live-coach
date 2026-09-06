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

    Emits one JSONL row per utterance (chronological order, both coach
    and client). Coach rows carry full rhythm features (CPM, silence 5.5,
    barge-in); client rows carry role + chars + gap from prior event.
    KPIs should filter to coach-only rows (see router._compute_kpis).

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
    events = list(_iter_dialogue(dialogue_path))

    # Read session_start wall-clock ms from _meta, so the first row's
    # "前沉默 ms" is real gap from session start (not wall-clock ms - 0,
    # which would be ~1.79e12 on 2026-09-06).
    session_start_ms: Optional[int] = None
    barge_in_by_turn: Dict[int, List[int]] = {}
    for ev in events:
        if ev.get("role") == "_meta" and ev.get("event") == "session_start":
            session_start_ms = ev.get("started_ms")
        elif ev.get("role") == "_meta" and ev.get("event") == "barge_in":
            barge_in_by_turn.setdefault(ev.get("turn", 0), []).append(ev.get("ms", 0))

    # Chronological utterance order (both roles).
    utterance_order: List[Dict[str, Any]] = []
    for ev in events:
        if ev.get("event") == "utterance" and ev.get("role") in ("coach", "client"):
            if isinstance(ev.get("ms"), int) and isinstance(ev.get("turn"), int):
                utterance_order.append(ev)
    utterance_order.sort(key=lambda e: (e["ms"], e.get("turn", 0), e.get("role", "")))

    # Per-turn lookup for coach text + client reply time.
    coach_text_by_turn: Dict[int, str] = {}
    coach_ms_by_turn: Dict[int, int] = {}
    client_ms_by_turn: Dict[int, int] = {}
    for ev in utterance_order:
        turn = ev["turn"]
        if ev["role"] == "coach":
            coach_text_by_turn[turn] = ev.get("text", "")
            coach_ms_by_turn[turn] = ev["ms"]
        else:
            client_ms_by_turn[turn] = ev["ms"]

    prev_event_ms = session_start_ms if isinstance(session_start_ms, int) else 0

    for ev in utterance_order:
        role = ev["role"]
        turn = ev["turn"]
        ms = ev["ms"]
        text = ev.get("text", "")
        if role == "coach":
            client_ms = client_ms_by_turn.get(turn, ms)
            # Find intervening client utterances between previous event and this coach turn.
            intervening_client = [
                e["ms"] for e in utterance_order
                if e["role"] == "client" and prev_event_ms < e["ms"] < ms
            ]
            silence = detect_silence(
                coach_turn_ms=ms,
                previous_event_ms=prev_event_ms,
                intervening_client_ms=intervening_client,
            )
            chars = count_chars(text)
            dur_ms = max(0, client_ms - ms)
            cpm_val = cpm(chars, dur_ms)
            barge_events = barge_in_by_turn.get(turn, [])
            barge_stats = collect_barge_ins(barge_events)
            row = {
                "turn": turn,
                "ts": ms,
                "coach_chars": chars,
                "coach_dur_ms": dur_ms,
                "cpm": cpm_val,
                "cpm_band": cpm_band(cpm_val),
                "pre_silence_ms": silence.pre_silence_ms,
                "silence_5_5": silence.silence_5_5,
                "client_filled_silence": silence.client_filled,
                "barge_in_count": barge_stats.barge_in_count,
                "client_interruption_by_coach_ms": client_interruption_by_coach_ms(ms, []),
                "speaker_role": "coach",
            }
            # After coach row, "previous event" is this coach utterance itself,
            # so the upcoming client row sees the coach→client gap.
            prev_event_ms = ms
        else:  # client
            gap = max(0, ms - prev_event_ms)
            row = {
                "turn": turn,
                "ts": ms,
                "client_chars": count_chars(text),
                "pre_silence_ms": gap,
                "silence_5_5": False,  # marker 5.5 is a coach-side metric
                "barge_in_count": 0,
                "speaker_role": "client",
            }
            prev_event_ms = ms
        features.append(row)
        if out_fh_target is not None:
            out_fh_target.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_fh_target.flush()

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
