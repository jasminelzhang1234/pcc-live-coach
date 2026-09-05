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
"""SessionRecorder — writes raw audio (WAV) + per-turn JSONL lines.

File layout (all under <sessions_dir>/):
    raw/<id>.wav           — 16kHz mono int16 PCM, appended incrementally
    dialogues/<id>.jsonl   — one JSON object per line: turns, meta events
    rhythm/<id>.jsonl      — one JSON per turn with rhythm numbers (Step 8)

Files are opened in append mode. dialogue / rhythm are opened with mode='a'
so multiple processes can write (Step 6 has only one writer per session, so
no contention in practice).
"""

from __future__ import annotations

import json
import logging
import wave
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class SessionRecorder:
    SAMPLE_RATE = 16000
    SAMPLE_WIDTH = 2  # bytes per sample (int16)
    CHANNELS = 1

    def __init__(self, sessions_dir: Path, session_id: str) -> None:
        self._root = sessions_dir
        self._id = session_id
        self.audio_path = str(self._root / "raw" / f"{session_id}.wav")
        self.dialogue_path = str(self._root / "dialogues" / f"{session_id}.jsonl")
        self.rhythm_path = str(self._root / "rhythm" / f"{session_id}.jsonl")
        self._wav: Optional[wave.Wave_write] = None
        self._dlg: Optional[Any] = None

    def open(self) -> None:
        for p in [
            Path(self.audio_path).parent,
            Path(self.dialogue_path).parent,
            Path(self.rhythm_path).parent,
        ]:
            p.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(self.audio_path, "wb")
        self._wav.setnchannels(self.CHANNELS)
        self._wav.setsampwidth(self.SAMPLE_WIDTH)
        self._wav.setframerate(self.SAMPLE_RATE)
        self._dlg = open(self.dialogue_path, "a", encoding="utf-8")

    def write_audio(self, pcm_bytes: bytes) -> None:
        """Append raw int16 mono PCM."""
        if self._wav is None:
            raise RuntimeError("recorder not opened")
        self._wav.writeframes(pcm_bytes)

    def write_dialogue(self, obj: Dict[str, Any]) -> None:
        if self._dlg is None:
            raise RuntimeError("recorder not opened")
        self._dlg.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._dlg.flush()

    def write_rhythm(self, obj: Dict[str, Any]) -> None:
        # Step 8 creates the file lazily. For Step 3 we only ensure the dir.
        Path(self.rhythm_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.rhythm_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def audio_duration_ms(self) -> int:
        if self._wav is None:
            return 0
        return int(self._wav.getnframes() / self.SAMPLE_RATE * 1000)

    def close(self) -> None:
        if self._wav is not None:
            try:
                self._wav.close()
            except Exception:
                pass
            self._wav = None
        if self._dlg is not None:
            try:
                self._dlg.close()
            except Exception:
                pass
            self._dlg = None