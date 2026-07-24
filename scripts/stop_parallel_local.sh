#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="${1:-${PRICE_MIXER_RUNTIME_ROOT:-$ROOT_DIR/runtime}}"
STATE_DIR="$RUNTIME_ROOT/state"

stop_screen() {
    local screen_file="$1"
    if [ ! -f "$screen_file" ]; then
        return
    fi
    local name
    name="$(tr -dc 'A-Za-z0-9._-' < "$screen_file")"
    if [ -n "$name" ] && command -v screen >/dev/null 2>&1; then
        screen -S "$name" -X quit >/dev/null 2>&1 || true
        echo "Stopped screen session: $name"
    fi
    rm -f "$screen_file"
}

stop_pid_file() {
    local label="$1"
    local pid_file="$2"
    if [ ! -f "$pid_file" ]; then
        echo "$label is not running (no PID file)."
        return
    fi
    local pid
    pid="$(tr -dc '0-9' < "$pid_file")"
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid"
        local deadline=$(($(date +%s) + 15))
        while kill -0 "$pid" >/dev/null 2>&1 && [ "$(date +%s)" -lt "$deadline" ]; do
            sleep 0.25
        done
        if kill -0 "$pid" >/dev/null 2>&1; then
            echo "$label did not stop cleanly (PID $pid)."
            exit 1
        fi
        echo "$label stopped (PID $pid)."
    else
        echo "$label PID is stale."
    fi
    rm -f "$pid_file"
}

stop_pid_file "Web" "$STATE_DIR/parallel-web.pid"
stop_pid_file "Worker" "$STATE_DIR/parallel-worker.pid"
stop_screen "$STATE_DIR/parallel-web.screen"
stop_screen "$STATE_DIR/parallel-worker.screen"
