#!/usr/bin/env bash
# JS unit tests for the browser audio state machine.
#
# Uses Node.js ≥18 built-in `node:test` runner — no npm install required.
# Test file: tests/phase_b/test_browser_audio_state.js
# Module under test: phase_b/static/audio_state.js (vanilla ES module)
#
# Usage:
#   ./scripts/test-js.sh
#   # or equivalently:
#   node --test tests/phase_b/*.js

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec node --test tests/phase_b/*.js