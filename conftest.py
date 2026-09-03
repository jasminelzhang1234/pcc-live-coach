"""Project-level pytest config.

Adds the project root to sys.path so `from phase_b.X import Y` works
under `pytest tests/...`. Without this, pytest's rootdir auto-detection
treats `phase_b/` as a package and tries to import `phase_b.test_*` as
a submodule of the package (which fails because there's no
`phase_b/test_*` directory).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
