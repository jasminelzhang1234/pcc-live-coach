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
"""Marker 6.6 — coach does not interrupt the client.

For v1, the only signal we have is the `_meta.barge_in` events the WS
handler records when the browser sends {"cmd":"barge_in"}. These mean
the client spoke over the coach's TTS playback. Counting them per turn
gives the dashboard a "client interrupt rate" KPI; counting them per
session is the aggregate 6.6 marker signal.

A coach-initiated interruption of the client would show up as a coach
utterance whose `ms` precedes the previous client utterance's
`reply_end` — but we don't record reply_end timestamps yet, so we
cannot detect that direction in v1. This is documented as a known gap
in the rhythm output (the `client_interruption_by_coach_ms` field is
always 0 for now).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class BargeInStats:
    barge_in_count: int = 0                   # barge_ins during this turn
    barge_in_ms: List[int] = field(default_factory=list)  # timestamps


def collect_barge_ins(turn_barge_in_events: List[int]) -> BargeInStats:
    """Bundle barge_in timestamps for one coach turn into stats."""
    return BargeInStats(barge_in_count=len(turn_barge_in_events), barge_in_ms=list(turn_barge_in_events))


def client_interruption_by_coach_ms(_coach_start_ms: int, _client_utterances: list) -> int:
    """Return how many ms of client speech the coach barged into.

    Always 0 in v1 — reply_end timestamps are not yet recorded. Kept as
    a function so the rhythm output schema can include the field without
    requiring a breaking change later.
    """
    return 0
