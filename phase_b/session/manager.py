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
"""SessionManager — in-memory registry of active practice sessions.

Each session has:
- id (e.g. real-2026-09-03-01)
- persona_id, topic, difficulty
- audio recorder (sessions/raw/<id>.wav)
- dialogue jsonl writer (sessions/dialogues/<id>.jsonl)
- rhythm jsonl writer (sessions/rhythm/<id>.jsonl) — created in Step 8
- start_ms / end_ms timestamps

Sessions are stored under practice-logs/sessions/ (gitignored). After session.end(), the
manager keeps the record until process exit; /api/session/{id} can still
return metadata for dashboard rendering.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from phase_b.session.recorder import SessionRecorder


logger = logging.getLogger(__name__)


class SessionState:
    def __init__(
        self,
        session_id: str,
        persona_id: str,
        topic: str,
        difficulty: int,
        recorder: SessionRecorder,
        started_ms: int,
    ) -> None:
        self.id = session_id
        self.persona_id = persona_id
        self.topic = topic
        self.difficulty = difficulty
        self.recorder = recorder
        self.started_ms = started_ms
        self.ended_ms: Optional[int] = None
        # Latency telemetry (filled by Step 6+ pipeline).
        self.last_latency_ms: Optional[int] = None
        # Gap 1: ASR health flag. True after a transient ASR failure that
        # couldn't be recovered — the coach can keep talking via the
        # force_turn / retry_turn escape hatches even without partials.
        self.asr_degraded: bool = False
        # Gap 3: LLM token usage accumulated across all turns in this session.
        self.llm_input_tokens: int = 0
        self.llm_output_tokens: int = 0
        self.llm_model_used: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "persona_id": self.persona_id,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "started_ms": self.started_ms,
            "ended_ms": self.ended_ms,
            "audio_path": self.recorder.audio_path,
            "dialogue_path": self.recorder.dialogue_path,
            "rhythm_path": self.recorder.rhythm_path,
            "last_latency_ms": self.last_latency_ms,
            # Gap 3: LLM cost attribution.
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "llm_model_used": self.llm_model_used,
            "asr_minutes": round(self.recorder.audio_duration_ms() / 60000.0, 3),
        }


def _today_seq(existing: List[str]) -> int:
    """Compute the next per-day suffix for a session_id.

    `real-YYYY-MM-DD-NN` — NN is 1-based per local-date, scans `existing` for
    the max NN for today's date and returns max+1.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    prefix = f"real-{today}-"
    max_n = 0
    for sid in existing:
        if not sid.startswith(prefix):
            continue
        try:
            n = int(sid[len(prefix) :])
            if n > max_n:
                max_n = n
        except ValueError:
            continue
    return max_n + 1


class SessionManager:
    def __init__(self, sessions_dir: str = "practice-logs/sessions") -> None:
        self._sessions_dir = Path(sessions_dir).resolve()
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def _new_id(self) -> str:
        with self._lock:
            existing = list(self._sessions.keys())
            # Also scan on-disk IDs (covers prior runs) to avoid collisions.
            for p in self._sessions_dir.glob("raw/real-*.wav"):
                existing.append(p.stem)
            today = datetime.now().strftime("%Y-%m-%d")
            n = _today_seq(existing)
            return f"real-{today}-{n:02d}"

    def start(
        self, persona_id: str, topic: str = "", difficulty: int = 0
    ) -> SessionState:
        sid = self._new_id()
        recorder = SessionRecorder(self._sessions_dir, sid)
        # Gap 2: do NOT open the recorder here. The browser must send
        # {"cmd":"consent","agree":true} first; the router calls
        # recorder.grant_consent() and writes the session_start marker
        # retroactively. This satisfies PIPL/GDPR explicit-consent.
        state = SessionState(
            session_id=sid,
            persona_id=persona_id,
            topic=topic,
            difficulty=difficulty,
            recorder=recorder,
            started_ms=int(time.time() * 1000),
        )
        with self._lock:
            self._sessions[sid] = state
        logger.info("session created (pre-consent): %s persona=%s", sid, persona_id)
        return state

    def mark_consented(self, session_id: str) -> bool:
        """Called by router after browser consent. Opens recorder files and
        writes the session_start marker. Returns True if successful."""
        with self._lock:
            state = self._sessions.get(session_id)
        if state is None:
            return False
        state.recorder.grant_consent()
        try:
            state.recorder.write_dialogue(
                {
                    "role": "_meta",
                    "event": "session_start",
                    "session_id": session_id,
                    "persona_id": state.persona_id,
                    "topic": state.topic,
                    "difficulty": state.difficulty,
                    "started_ms": state.started_ms,
                    "started_iso": datetime.now().isoformat(timespec="seconds"),
                }
            )
        except Exception:
            logger.exception("failed to write session_start marker for %s", session_id)
        return True

    def get(self, session_id: str) -> Optional[SessionState]:
        return self._sessions.get(session_id)

    def end(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            state = self._sessions.get(session_id)
        if state is None:
            return None
        state.ended_ms = int(time.time() * 1000)
        state.recorder.write_dialogue(
            {
                "role": "_meta",
                "event": "session_end",
                "session_id": session_id,
                "ended_ms": state.ended_ms,
            }
        )
        state.recorder.close()
        # Probe-session fast path: no audio bytes AND no client/coach utterance
        # lines (e.g. health-check or front-end wiring test). Skip rhythm and
        # CSV row, then unlink the empty artifacts so they don't pile up.
        try:
            has_audio = state.recorder.audio_bytes() > 0
            has_turn = False
            dlg_path = Path(state.recorder.dialogue_path)
            if dlg_path.is_file():
                for line in dlg_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get("role") in ("client", "coach"):
                        has_turn = True
                        break
            if not has_audio and not has_turn:
                for p in (
                    state.recorder.audio_path,
                    state.recorder.dialogue_path,
                    state.recorder.rhythm_path,
                ):
                    Path(p).unlink(missing_ok=True)
                logger.info(
                    "session %s had no audio/turns; artifacts removed, skipping downstream",
                    session_id,
                )
                return state
        except Exception:
            logger.exception("orphan check failed for %s; continuing", session_id)
        # Step 8: post-process the dialogue into rhythm features. Done
        # synchronously after close so the JSONL files are fully flushed.
        # Failures are logged but do not break the end() return value.
        try:
            from phase_b.rhythm.turn_features import extract_turn_features
            extract_turn_features(
                Path(state.recorder.dialogue_path),
                out_path=Path(state.recorder.rhythm_path),
            )
        except Exception:
            logger.exception("rhythm extraction failed for %s", session_id)
        # Step 9: append a row to progress/tracker-sessions.csv so the
        # dashboard and tracker analysis scripts can find the session.
        # Marker scoring columns stay blank in v1.
        try:
            from phase_b.config import get_settings
            from phase_b.tracker.csv_append import append_session
            csv_path = Path(get_settings().tracker_csv)
            if not csv_path.is_absolute():
                # Resolved against the repo root (where phase_b/ lives), not cwd,
                # so the path is stable regardless of where `python -m phase_b`
                # is launched from.
                csv_path = Path(__file__).resolve().parents[2] / csv_path
            # Gap 3: pass token + ASR metrics so the CSV row carries
            # cost attribution (see phase_b/llm/cost.py for pricing).
            append_session(
                session_id=session_id,
                persona=state.persona_id,
                difficulty=state.difficulty,
                topic=state.topic,
                audio_path=state.recorder.audio_path,
                transcript_path=state.recorder.dialogue_path,
                csv_path=csv_path,
                llm_input_tokens=state.llm_input_tokens,
                llm_output_tokens=state.llm_output_tokens,
                llm_model_used=state.llm_model_used,
                asr_minutes=state.recorder.audio_duration_ms() / 60000.0,
            )
        except FileNotFoundError:
            # CSV file absent (e.g. first run before header was written) —
            # log loudly but don't crash the session.
            logger.warning("tracker CSV not found; skipping row append for %s", session_id)
        except Exception:
            logger.exception("tracker CSV append failed for %s", session_id)
        logger.info("session ended: %s duration_ms=%s", session_id, state.ended_ms - state.started_ms)
        return state

    def all(self) -> List[SessionState]:
        return list(self._sessions.values())


# Module-level singleton.
_manager: Optional[SessionManager] = None


def get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        from phase_b.config import get_settings
        from phase_b.session.retention import sweep_expired_audio

        settings = get_settings()
        _manager = SessionManager(sessions_dir=settings.sessions_dir)
        # Gap 2: sweep expired audio on process start (once per process).
        try:
            sweep_expired_audio(
                Path(settings.sessions_dir).resolve(),
                settings.audio_retention_days,
            )
        except Exception:
            logger.exception("retention sweep failed during manager init")
    return _manager