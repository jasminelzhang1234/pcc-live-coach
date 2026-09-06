# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
"""Top-level pytest configuration.

Phase B ASR tests (test_asr_trigger_decoding.py, test_asr_worker.py)
require the aliyun-nls + soundfile SDKs that aren't part of the
dashboard / rhythm / assess / tracker test surface. Skipping them at
collection time avoids noisy import errors when running the dashboard
test suite locally.
"""
from __future__ import annotations

collect_ignore_glob = [
    "phase_b/test_asr_trigger_decoding.py",
    "phase_b/test_asr_worker.py",
]