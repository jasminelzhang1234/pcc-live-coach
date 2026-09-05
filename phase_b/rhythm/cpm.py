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
"""Marker 7.6 — coach pacing (chars per minute).

PCC practice target: 150–200 chars/min Chinese (≈ conversational
"paced and clear"). Below 120 reads as too slow (stalling); above 280
reads as too fast (rushing / losing presence).

We measure chars (Chinese + English letters + digits) divided by the
coach turn's effective duration — from the coach utterance commit
(`speak` cmd) to the client reply text arrival (TTS first text frame).
This is a v1 proxy: it conflates the LLM think-time with the
coach's spoken rate, but it is the only timestamp pair we record.
"""

from __future__ import annotations


# Bands per plan / spike config.
SLOW_THRESHOLD = 120
FAST_THRESHOLD = 280


def count_chars(text: str) -> int:
    """Count user-perceived characters: CJK + letters/digits + punctuation-as-word.

    Whitespace is excluded. CJK ideographs each count as 1; ASCII letters
    and digits each count as 1. This is the "string length minus spaces"
    heuristic used in the spike.
    """
    if not text:
        return 0
    return sum(1 for ch in text if not ch.isspace())


def cpm(chars: int, dur_ms: int) -> int:
    """Return chars per minute for the given text/duration. 0 if dur_ms<=0."""
    if dur_ms <= 0 or chars <= 0:
        return 0
    return int(chars * 60_000 / dur_ms)


def cpm_band(value: int) -> str:
    if value < SLOW_THRESHOLD:
        return "slow"
    if value > FAST_THRESHOLD:
        return "fast"
    return "ideal"
