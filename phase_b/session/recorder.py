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

Gap 2 (consent gate): Files are NOT opened until grant_consent() is called.
write_audio() is a no-op before consent. Manager.create() should NOT call
open() — the router does, after receiving {"cmd":"consent","agree":true}
from the browser. This satisfies PIPL/GDPR explicit-consent expectations
(README warnings alone don't satisfy the legal requirement).
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
        self._bytes_written: int = 0
        # Gap 2: gate behind explicit user consent (PIPL/GDPR).
        self._consent_granted: bool = False

    @property
    def consent_granted(self) -> bool:
        return self._consent_granted

    def grant_consent(self) -> None:
        """Open the WAV + dialogue files. Called by router after the browser
        sends {"cmd":"consent","agree":true}.

        Idempotent on the consent flag, but if the wave handle was closed
        (e.g. after SessionRecorder.close()) this re-opens the file handles
        so legacy callers (tests, future append-after-end flows) keep working.
        """
        first_time = not self._consent_granted
        self._consent_granted = True
        for p in [
            Path(self.audio_path).parent,
            Path(self.dialogue_path).parent,
            Path(self.rhythm_path).parent,
        ]:
            p.mkdir(parents=True, exist_ok=True)
        if first_time or self._wav is None:
            self._wav = wave.open(self.audio_path, "wb")
            self._wav.setnchannels(self.CHANNELS)
            self._wav.setsampwidth(self.SAMPLE_WIDTH)
            self._wav.setframerate(self.SAMPLE_RATE)
        if first_time or self._dlg is None:
            self._dlg = open(self.dialogue_path, "a", encoding="utf-8")
        if first_time:
            logger.info("recorder %s: consent granted, files opened", self._id)

    def open(self) -> None:
        """Deprecated alias for grant_consent().

        Kept for backward compatibility with existing tests that called
        recorder.open() directly. New code should call grant_consent().
        """
        self.grant_consent()

    def write_audio(self, pcm_bytes: bytes) -> None:
        """Append raw int16 mono PCM. No-op until consent is granted."""
        if not self._consent_granted:
            return
        if self._wav is None:
            raise RuntimeError("recorder not opened (consent granted but wav handle is None)")
        self._wav.writeframes(pcm_bytes)
        self._bytes_written += len(pcm_bytes)

    def write_dialogue(self, obj: Dict[str, Any]) -> None:
        if not self._consent_granted:
            # Caller should not write before consent. If they do, log loudly
            # rather than raising — dialogue JSONL is text-derived and not
            # subject to the same legal constraint as raw audio.
            logger.warning(
                "write_dialogue called before consent on %s; dropping %s",
                self._id, obj.get("event"),
            )
            return
        if self._dlg is None:
            raise RuntimeError("recorder not opened (consent granted but dlg handle is None)")
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

    def audio_bytes(self) -> int:
        """Bytes of raw PCM written so far (excluding WAV header). 0 if never opened."""
        return self._bytes_written

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
