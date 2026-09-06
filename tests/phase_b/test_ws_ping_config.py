# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
"""WS keepalive ping tuning — regression guard.

uvicorn defaults to ws_ping_interval=20 / ws_ping_timeout=20. With
MiniMax-M3 reasoning_split, an LLM call typically takes 30-60s, peaking
70-80s. With the default 20s ping, the WS would be torn down *before*
the reply_text / TTS frames reach the browser — the user sees "回复
结束 — 继续说话" without ever hearing the reply.

These tests verify the config defaults are wired through to the
uvicorn launch (and to a Settings env-var override), so this regression
can't quietly come back.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def test_settings_default_ping_values_cover_m3_reasoning():
    """Defaults must be ≥ 30s so M3 reasoning (typical 30-60s) doesn't
    kill the WS mid-reply. Picked 60/60 for a buffer above p99 (70-80s)."""
    from phase_b.config import get_settings

    s = get_settings()
    assert s.ws_ping_interval_s == 60.0, (
        f"ws_ping_interval_s={s.ws_ping_interval_s}; expected 60.0 — "
        f"uvicorn default 20s will tear down the WS during M3 reasoning."
    )
    assert s.ws_ping_timeout_s == 60.0, (
        f"ws_ping_timeout_s={s.ws_ping_timeout_s}; expected 60.0 — "
        f"uvicorn default 20s will tear down the WS during M3 reasoning."
    )


def test_settings_ping_override_via_env_var(monkeypatch):
    """WS_PING_TIMEOUT_S / WS_PING_INTERVAL_S env vars override defaults
    (for ops who need a tighter or looser timeout). Test reload behavior
    is consistent with the existing _DOTENV_OVERRIDE_KEYS pattern."""
    import phase_b.config as cfg

    monkeypatch.setenv("WS_PING_INTERVAL_S", "90")
    monkeypatch.setenv("WS_PING_TIMEOUT_S", "45")
    cfg2 = importlib.reload(cfg)
    s = cfg2.get_settings()
    assert s.ws_ping_interval_s == 90.0
    assert s.ws_ping_timeout_s == 45.0
    importlib.reload(cfg)  # restore


def test_main_passes_ping_settings_to_uvicorn(monkeypatch):
    """`python -m phase_b` must forward the ping values to uvicorn.run().
    We monkeypatch uvicorn.run so no real server starts, then assert
    the kwargs are present and correct."""
    import phase_b.__main__ as main_mod

    captured = {}

    def fake_uvicorn_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(main_mod.uvicorn, "run", fake_uvicorn_run)
    main_mod.main()

    assert "ws_ping_interval" in captured, (
        f"uvicorn.run kwargs missing ws_ping_interval; got: {list(captured.keys())}"
    )
    assert "ws_ping_timeout" in captured
    # 60.0 by default; we didn't override env, so this is the baseline.
    assert captured["ws_ping_interval"] == 60.0
    assert captured["ws_ping_timeout"] == 60.0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))