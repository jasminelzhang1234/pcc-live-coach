# Copyright 2026 the maintainer Zhang. Licensed under the Apache License, Version 2.0
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
"""Config — single source of truth for all defaults.

Reads `.env` if present (best-effort, no extra dependency).
Plain dataclass + os.environ (no pydantic_settings, no extra install).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Best-effort .env load (no python-dotenv required).
def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_load_dotenv(_PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # Server
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "info"
    allow_lan: bool = False  # refuse 0.0.0.0 unless explicitly enabled

    # ASR (FunASR) — in-process chunked offline (SenseVoiceSmall validated).
    asr_model: str = "iic/SenseVoiceSmall"
    asr_vad_model: str = "fsmn-vad"
    asr_punc_model: str = "ct-punc"
    asr_chunk_ms: int = 1000  # how often to flush a partial decode
    asr_language: str = "auto"

    # LLM (MiniMax by default; switchable to local OpenAI-compatible)
    llm_base_url: str = "https://api.minimaxi.com/v1"
    llm_api_key: str = ""
    llm_model: str = "MiniMax-M3"
    llm_timeout_s: float = 30.0
    llm_max_tokens: int = 200
    llm_temperature: float = 0.6

    # TTS (MiniMax T2A)
    tts_ws_url: str = "wss://api.minimaxi.com/ws/v1/t2a_v2"
    tts_api_key: str = ""
    tts_model: str = "speech-2.6-hd"
    tts_voice: str = "male-qn-jingying"  # placeholder; verify against MiniMax voice catalog at implementation time
    tts_sample_rate: int = 16000
    tts_timeout_s: float = 30.0

    # Audio
    audio_sample_rate: int = 16000
    audio_frame_ms: int = 30
    audio_channels: int = 1

    # Rhythm features
    silence_threshold_ms: int = 2000  # 5.5
    cpm_slow: int = 120  # 7.6
    cpm_ideal_low: int = 150
    cpm_ideal_high: int = 200
    cpm_fast: int = 280
    barge_in_debounce_ms: int = 500  # 6.6

    # Paths
    personas_dir: str = "personas"
    sessions_dir: str = "sessions"
    tracker_csv: str = "progress/tracker-real-sessions.csv"


def get_settings() -> Settings:
    """Build Settings from environment, honoring `.env`."""
    s = Settings(
        host=_env("PCC_LIVE_HOST", "127.0.0.1"),
        port=_env_int("PCC_LIVE_PORT", 8765),
        log_level=_env("PCC_LIVE_LOG_LEVEL", "info"),
        allow_lan=_env_bool("PCC_LIVE_ALLOW_LAN", False),
        asr_model=_env("FUNASR_MODEL", "iic/SenseVoiceSmall"),
        asr_vad_model=_env("FUNASR_VAD_MODEL", "fsmn-vad"),
        asr_punc_model=_env("FUNASR_PUNC_MODEL", "ct-punc"),
        asr_chunk_ms=_env_int("ASR_CHUNK_MS", 1000),
        asr_language=_env("ASR_LANGUAGE", "auto"),
        llm_base_url=_env("LLM_BASE_URL", "https://api.minimaxi.com/v1"),
        llm_api_key=_env("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", "MiniMax-M3"),
        llm_timeout_s=float(_env("LLM_TIMEOUT_S", "30")),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 200),
        llm_temperature=float(_env("LLM_TEMPERATURE", "0.6")),
        tts_ws_url=_env("TTS_WS_URL", "wss://api.minimaxi.com/ws/v1/t2a_v2"),
        tts_api_key=_env("TTS_API_KEY", ""),
        tts_model=_env("TTS_MODEL", "speech-2.6-hd"),
        tts_voice=_env("TTS_VOICE", "male-qn-jingying"),
        tts_sample_rate=_env_int("TTS_SAMPLE_RATE", 16000),
        tts_timeout_s=float(_env("TTS_TIMEOUT_S", "30")),
        audio_sample_rate=_env_int("AUDIO_SAMPLE_RATE", 16000),
        audio_frame_ms=_env_int("AUDIO_FRAME_MS", 30),
        audio_channels=_env_int("AUDIO_CHANNELS", 1),
        silence_threshold_ms=_env_int("SILENCE_THRESHOLD_MS", 2000),
        cpm_slow=_env_int("CPM_SLOW", 120),
        cpm_ideal_low=_env_int("CPM_IDEAL_LOW", 150),
        cpm_ideal_high=_env_int("CPM_IDEAL_HIGH", 200),
        cpm_fast=_env_int("CPM_FAST", 280),
        barge_in_debounce_ms=_env_int("BARGE_IN_DEBOUNCE_MS", 500),
        personas_dir=_env("PERSONAS_DIR", "personas"),
        sessions_dir=_env("SESSIONS_DIR", "sessions"),
        tracker_csv=_env("TRACKER_CSV", "progress/tracker-real-sessions.csv"),
    )
    # Safety: refuse 0.0.0.0 unless allow_lan
    if not s.allow_lan and s.host in ("0.0.0.0", ""):
        raise SystemExit(
            "Refusing to bind 0.0.0.0 (would expose audio to LAN). "
            "Set PCC_LIVE_ALLOW_LAN=1 to override."
        )
    return s