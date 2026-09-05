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
"""Marker 5.5 — coach holds space with silence.

A "present silence" is a gap ≥ 2 seconds where the coach did not fill
the space AND the client did not fill it either. We detect this between
coach turns: gap from the previous client utterance's `ms` to the current
coach utterance's `ms`, with no intervening client utterance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


# Marker threshold per ICF PCC Marker 5.5.
SILENCE_THRESHOLD_MS = 2000


@dataclass
class SilenceResult:
    pre_silence_ms: int            # gap from previous event to this coach turn
    silence_5_5: bool              # True iff gap >= threshold AND client didn't fill
    client_filled: bool            # True iff a client utterance occurred in the gap


def detect_silence(
    coach_turn_ms: int,
    previous_event_ms: int,
    intervening_client_ms: Optional[List[int]] = None,
    threshold_ms: int = SILENCE_THRESHOLD_MS,
) -> SilenceResult:
    """Return silence classification for one coach turn.

    Args:
        coach_turn_ms: ms timestamp of the coach utterance (commit time).
        previous_event_ms: ms timestamp of the prior recorded event
            (typically the previous client utterance, or session start).
        intervening_client_ms: client utterance timestamps that landed
            between `previous_event_ms` and `coach_turn_ms`. Empty list
            means the client did not fill the gap.
        threshold_ms: minimum gap for a 5.5 silence (default 2000).
    """
    intervening_client_ms = intervening_client_ms or []
    gap = max(0, coach_turn_ms - previous_event_ms)
    client_filled = any(ms > previous_event_ms and ms < coach_turn_ms for ms in intervening_client_ms)
    silence_5_5 = gap >= threshold_ms and not client_filled
    return SilenceResult(pre_silence_ms=gap, silence_5_5=silence_5_5, client_filled=client_filled)
