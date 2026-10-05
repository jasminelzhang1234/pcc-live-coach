# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Gap 6 — persona model pin + multi-language file convention tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from phase_b.personas.loader import load  # noqa: E402


@pytest.fixture
def personas_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create a minimal personas dir with one zh + one en variant."""
    d = tmp_path / "personas"
    d.mkdir()
    (d / "test-01-client.md").write_text(
        "---\n"
        "id: test-01\n"
        "线: VEC 高管线\n"
        "难度: 2\n"
        "训练重点: 3.1\n"
        "版本: coach\n"
        "model: MiniMax-M3\n"
        "model_pin_date: 2026-10-05\n"
        "---\n"
        "# 测试人格 01\n"
        "\n"
        "## 不可越界（硬约束）\n"
        "- rule one\n"
        "- rule two\n"
        "\n"
        "## 语言风格\n"
        "short\n"
        "\n"
        "## 反应规则表\n"
        "default\n"
        "\n"
        "## 开场白（逐字照说）\n"
        "你好。\n"
        "\n"
        "## 表层议题\n"
        "test\n"
        , encoding="utf-8",
    )
    (d / "test-01-client.en.md").write_text(
        "---\n"
        "id: test-01\n"
        "线: VEC high line\n"
        "难度: 2\n"
        "训练重点: 3.1\n"
        "版本: coach\n"
        "model: claude-sonnet-4-5\n"
        "---\n"
        "# Test Persona 01\n"
        "\n"
        "## 不可越界（硬约束）\n"
        "- rule one\n"
        "\n"
        "## 语言风格\n"
        "short\n"
        "\n"
        "## 反应规则表\n"
        "default\n"
        "\n"
        "## 开场白（逐字照说）\n"
        "Hello.\n"
        "\n"
        "## 表层议题\n"
        "test\n"
        , encoding="utf-8",
    )
    return d


def test_load_default_chinese(personas_dir):
    """Default PERSONAS_LANG='zh' loads the .md (zh) variant."""
    p = load("test-01", personas_dir=str(personas_dir))
    assert p["id"] == "test-01"
    assert p["line"] == "VEC 高管线"
    assert p["model"] == "MiniMax-M3"
    assert p["model_pin_date"] == "2026-10-05"


def test_load_english_when_env_set(personas_dir, monkeypatch):
    """PERSONAS_LANG=en picks the .en.md variant."""
    monkeypatch.setenv("PERSONAS_LANG", "en")
    p = load("test-01", personas_dir=str(personas_dir))
    assert p["model"] == "claude-sonnet-4-5"
    # English file content is loaded (different opening).
    assert "Hello" in p["opening"]


def test_load_falls_back_to_legacy_when_lang_missing(personas_dir, monkeypatch):
    """If PERSONAS_LANG=fr and no .fr.md exists, fall back to default .md."""
    monkeypatch.setenv("PERSONAS_LANG", "fr")
    p = load("test-01", personas_dir=str(personas_dir))
    # Should fall back to the .md variant (Chinese, with MiniMax-M3).
    assert p["model"] == "MiniMax-M3"
