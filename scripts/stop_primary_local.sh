#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="${1:?Runtime root is required}"
STATE_DIR="$RUNTIME_ROOT/state"

"$ROOT_DIR/scripts/stop_parallel_local.sh" "$RUNTIME_ROOT"

if [ -f "$STATE_DIR/parallel-parser.screen" ]; then
    name="$(tr -dc 'A-Za-z0-9._-' < "$STATE_DIR/parallel-parser.screen")"
    if [ -n "$name" ] && command -v screen >/dev/null 2>&1; then
        screen -S "$name" -X quit >/dev/null 2>&1 || true
        echo "Stopped screen session: $name"
    fi
    rm -f "$STATE_DIR/parallel-parser.screen"
fi

if [ -f "$STATE_DIR/parallel-parser.pid" ]; then
    pid="$(tr -dc '0-9' < "$STATE_DIR/parallel-parser.pid")"
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid"
    fi
    rm -f "$STATE_DIR/parallel-parser.pid"
fi
