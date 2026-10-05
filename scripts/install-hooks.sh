#!/usr/bin/env bash
# Install pre-commit + commit-msg hooks into .git/hooks/ by symlinking
# them to scripts/hooks/. Re-running is safe (idempotent).
#
# Usage:  ./scripts/install-hooks.sh
#
# What it does:
#   1. Validates the word list (scripts/hooks/words.txt)
#   2. Symlinks scripts/hooks/<name> → .git/hooks/<name> for both hooks
#   3. Preserves existing *.sample hooks
#   4. Prints a summary

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC_DIR="$REPO_ROOT/scripts/hooks"
DST_DIR="$REPO_ROOT/.git/hooks"
WORDLIST="$SRC_DIR/words.txt"

if [ ! -d "$SRC_DIR" ]; then
    echo "❌ Source dir not found: $SRC_DIR"
    exit 1
fi

if [ ! -f "$WORDLIST" ]; then
    echo "❌ Wordlist not found: $WORDLIST"
    exit 1
fi

echo "Installing hooks from $SRC_DIR → $DST_DIR"
echo

INSTALLED=0
SKIPPED=0

for hook in pre-commit commit-msg; do
    src="$SRC_DIR/$hook"
    dst="$DST_DIR/$hook"

    if [ ! -f "$src" ]; then
        echo "  ⚠️  $hook: source missing at $src — skipping"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Make source executable (in case user pulled fresh and lost bit)
    chmod +x "$src"

    # Preserve .sample hooks; replace our own previous installs (regular or symlink).
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        if [ -L "$dst" ] && readlink "$dst" | grep -q "$SRC_DIR"; then
            echo "  ✓ $hook: already installed (symlink intact)"
            continue
        fi
        # If it's a real file (not a sample), warn before clobbering
        if [ -f "$dst" ] && [[ "$dst" != *.sample ]]; then
            echo "  ⚠️  $hook: existing non-symlink file at $dst — backing up to ${dst}.bak"
            mv "$dst" "${dst}.bak"
        fi
    fi

    ln -sf "$src" "$dst"
    echo "  ✓ $hook: linked → $src"
    INSTALLED=$((INSTALLED + 1))
done

echo
echo "Done. $INSTALLED installed, $SKIPPED skipped."
echo
echo "Word list: $WORDLIST"
echo "Edit it, then re-run:  $0"
echo
echo "Bypass a single commit:  git commit --no-verify"
echo "Run all hooks now (dry-run):  git commit --allow-empty -m 'hook self-test'"