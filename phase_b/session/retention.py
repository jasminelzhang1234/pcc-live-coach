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
"""Audio retention sweep — Gap 2 compliance (PIPL/GDPR data minimization).

Deletes raw/<id>.wav files older than `retention_days`. Dialogue JSONL,
rhythm JSONL, and tracker CSV are NOT touched — they contain text-derived
metrics, not raw voice, and are needed for the dashboard / trending chart.

Called from:
  - SessionManager.get_manager() on first init (process start)
  - POST /api/retention/set (user-initiated sweep)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path


logger = logging.getLogger(__name__)


def sweep_expired_audio(sessions_dir: Path, retention_days: int) -> int:
    """Delete raw/<id>.wav files older than retention_days.

    Args:
        sessions_dir: e.g. Path("practice-logs/sessions")
        retention_days: 0 disables; positive = delete older than N days.

    Returns:
        Number of wav files deleted.
    """
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400
    raw = sessions_dir / "raw"
    if not raw.is_dir():
        return 0
    deleted = 0
    for wav in raw.glob("real-*.wav"):
        try:
            if wav.stat().st_mtime < cutoff:
                wav.unlink()
                deleted += 1
                logger.info("retention: deleted %s (older than %d days)", wav.name, retention_days)
        except FileNotFoundError:
            # Race with concurrent delete — ignore.
            continue
        except Exception:
            logger.exception("retention sweep failed for %s", wav)
    if deleted:
        logger.info("retention sweep: deleted %d file(s) (cutoff=%d days)", deleted, retention_days)
    return deleted
