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
# .env always wins over inherited shell env: shell LLM_API_KEY from another
# project silently broke MiniMax auth on 2026-09-06 (got 401 instead of the
# .env-stored key).
# Project-local config keys whose .env value must always win over any
# stale shell value left over from another project. 2026-09-06 hits:
#   LLM_API_KEY  → MiniMax 401 (stale key from another project)
#   LLM_MODEL    → MiniMax 400 ("unknown model 'deepseek-chat'")
# Non-credential env vars (TRACKER_CSV, host/port) keep shell-or-test
# precedence so test fixtures can override them.
_DOTENV_OVERRIDE_KEYS = frozenset({
    "LLM_API_KEY",
    "LLM_MODEL",
    "ALIYUN_ASR_APPKEY",
    "ALIYUN_ACCESS_KEY_ID",
    "ALIYUN_ACCESS_KEY_SECRET",
})


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
        if not key or not value:
            continue
        if key in _DOTENV_OVERRIDE_KEYS:
            os.environ[key] = value
        elif key not in os.environ:
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
    # WebSocket ping tuning — must cover MiniMax-M3 reasoning_split latency
    # (30-60s typical, 70-80s peak). Default uvicorn 20/20 is too short;
    # the WS gets killed mid-LLM-reply and the browser sees "回复结束 —
    # 继续说话" without ever receiving the reply_text / TTS frames.
    # 60/60 covers p99 reasoning with a buffer; if the client truly dies,
    # server still detects within ~120s. (2026-09-06 dashboard v2)
    ws_ping_interval_s: float = 60.0
    ws_ping_timeout_s: float = 60.0

    # ASR — 阿里云智能语音交互(实时语音识别)
    aliyun_asr_appkey: str = ""              # ALIYUN_ASR_APPKEY
    aliyun_access_key_id: str = ""           # ALIYUN_ACCESS_KEY_ID
    aliyun_access_key_secret: str = ""       # ALIYUN_ACCESS_KEY_SECRET

    # LLM (MiniMax by default; switchable to local OpenAI-compatible)
    llm_base_url: str = "https://api.minimaxi.com/v1"
    llm_api_key: str = ""
    llm_model: str = "MiniMax-M3"
    llm_timeout_s: float = 90.0  # M3 with reasoning_split often runs 30-60s on persona prompts
    llm_max_tokens: int = 1000  # M3 spends ~200 tokens on reasoning; need headroom for the actual reply
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
    sessions_dir: str = "practice-logs/真人练习"
    tracker_csv: str = "progress/tracker-real-sessions.csv"


def get_settings() -> Settings:
    """Build Settings from environment, honoring `.env`."""
    s = Settings(
        host=_env("PCC_LIVE_HOST", "127.0.0.1"),
        port=_env_int("PCC_LIVE_PORT", 8765),
        log_level=_env("PCC_LIVE_LOG_LEVEL", "info"),
        allow_lan=_env_bool("PCC_LIVE_ALLOW_LAN", False),
        ws_ping_interval_s=float(_env("WS_PING_INTERVAL_S", "60")),
        ws_ping_timeout_s=float(_env("WS_PING_TIMEOUT_S", "60")),
        aliyun_asr_appkey=_env("ALIYUN_ASR_APPKEY", ""),
        aliyun_access_key_id=_env("ALIYUN_ACCESS_KEY_ID", ""),
        aliyun_access_key_secret=_env("ALIYUN_ACCESS_KEY_SECRET", ""),
        llm_base_url=_env("LLM_BASE_URL", "https://api.minimaxi.com/v1"),
        llm_api_key=_env("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", "MiniMax-M3"),
        llm_timeout_s=float(_env("LLM_TIMEOUT_S", "90")),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 1000),
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
        sessions_dir=_env("SESSIONS_DIR", "practice-logs/真人练习"),
        tracker_csv=_env("TRACKER_CSV", "progress/tracker-real-sessions.csv"),
    )
    # Safety: refuse 0.0.0.0 unless allow_lan
    if not s.allow_lan and s.host in ("0.0.0.0", ""):
        raise SystemExit(
            "Refusing to bind 0.0.0.0 (would expose audio to LAN). "
            "Set PCC_LIVE_ALLOW_LAN=1 to override."
        )
    return s