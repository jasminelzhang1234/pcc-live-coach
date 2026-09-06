#!/usr/bin/env bash
# PCC Live Coach — one-shot launcher.
# - Locates the venv Python (no `source activate` required)
# - Verifies .env exists (without it the server boots but TTS/LLM won't work)
# - Starts the server
# - Auto-opens http://127.0.0.1:8765/ in your default browser after ~3s
#
# Usage (Terminal):   ./start.sh
# Usage (Finder):     double-click start.command (Mac only)
#
# Stop: Ctrl-C in the Terminal window (or close it).

set -e

# Resolve script directory even when invoked via symlink / Finder.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "✗ Python venv not found at: $PYTHON"
    echo "  First-time setup:"
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/pip install -r requirements.txt"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "✗ .env not found at: $SCRIPT_DIR/.env"
    echo "  Copy the template and fill in your keys:"
    echo "    cp .env.example .env"
    echo "    \$EDITOR .env"
    exit 1
fi

# Refuse to start if the port is already bound — the common silent-break case
# when a previous start.sh was killed without Ctrl-C (terminal close, logout).
PORT="${PCC_LIVE_PORT:-8765}"
HOLDER=""
if command -v lsof >/dev/null 2>&1; then
    HOLDER="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -F pc 2>/dev/null | awk '/^p/{pid=$1; sub(/^p/,"",pid)}/^c/{print pid; exit}')"
fi
if [ -n "$HOLDER" ]; then
    echo "✗ Port $PORT is already held by PID $HOLDER."
    echo "  Likely cause: a previous start.sh was not stopped cleanly."
    echo "  Fix one of:"
    echo "    kill $HOLDER                # if you started it"
    echo "    PCC_LIVE_PORT=8766 $0       # use a different port"
    exit 1
fi

# Open browser after the server has bound the port.
# Server cold-start (FunASR import) takes ~3-5s; we sleep a bit longer
# so the page doesn't 502 on first paint.
(
    sleep 4
    URL="http://127.0.0.1:${PCC_LIVE_PORT:-8765}/"
    if command -v open >/dev/null 2>&1; then
        open "$URL"            # macOS
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL"        # Linux
    fi
) &

echo "▶ PCC Live Coach starting at http://127.0.0.1:${PCC_LIVE_PORT:-8765}/"
echo "  (close this window or press Ctrl-C to stop)"
exec "$PYTHON" -m phase_b
