#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="${1:-${PRICE_MIXER_RUNTIME_ROOT:-$ROOT_DIR/runtime}}"
PORT="${2:-${PRICE_MIXER_PORT:-5012}}"
ENV_FILE="${PRICE_MIXER_ENV_FILE:-$ROOT_DIR/.env}"
PYTHON="${PRICE_MIXER_PYTHON:-$ROOT_DIR/.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
    echo "Python environment not found: $PYTHON"
    echo "Set PRICE_MIXER_PYTHON to a compatible Python 3.11 executable."
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "Environment file not found: $ENV_FILE"
    exit 1
fi
if ! [[ "$PORT" =~ '^[0-9]+$' ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "Invalid port: $PORT"
    exit 1
fi

STATE_DIR="$RUNTIME_ROOT/state"
DATA_DIR="$RUNTIME_ROOT/data"
CACHE_DIR="$RUNTIME_ROOT/cache"
UPLOAD_DIR="$RUNTIME_ROOT/uploads"
LOG_DIR="$RUNTIME_ROOT/logs"
BACKUP_DIR="$RUNTIME_ROOT/backups"
WEB_PID_FILE="$STATE_DIR/parallel-web.pid"
WORKER_PID_FILE="$STATE_DIR/parallel-worker.pid"
WEB_SCREEN_FILE="$STATE_DIR/parallel-web.screen"
WORKER_SCREEN_FILE="$STATE_DIR/parallel-worker.screen"
WEB_SCREEN="pricemixer-web-$PORT"
WORKER_SCREEN="pricemixer-worker-$PORT"
RUNNER="$ROOT_DIR/scripts/run_parallel_component.py"

mkdir -p \
    "$STATE_DIR" "$DATA_DIR" "$CACHE_DIR" "$UPLOAD_DIR" "$LOG_DIR" \
    "$BACKUP_DIR"

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $PORT is already in use:"
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
    exit 1
fi

for pid_file in "$WEB_PID_FILE" "$WORKER_PID_FILE"; do
    if [ -f "$pid_file" ]; then
        old_pid="$(tr -dc '0-9' < "$pid_file")"
        if [ -n "$old_pid" ] && kill -0 "$old_pid" >/dev/null 2>&1; then
            echo "Parallel Price Mixer is already running (PID $old_pid)."
            exit 1
        fi
        rm -f "$pid_file"
    fi
done

cd "$ROOT_DIR"
if command -v screen >/dev/null 2>&1; then
    screen -S "$WEB_SCREEN" -X quit >/dev/null 2>&1 || true
    screen -S "$WORKER_SCREEN" -X quit >/dev/null 2>&1 || true
    screen -dmS "$WORKER_SCREEN" \
        "$PYTHON" "$RUNNER" worker "$ROOT_DIR" "$RUNTIME_ROOT" "$PORT" \
        "$ENV_FILE" "$PYTHON"
    screen -dmS "$WEB_SCREEN" \
        "$PYTHON" "$RUNNER" web "$ROOT_DIR" "$RUNTIME_ROOT" "$PORT" \
        "$ENV_FILE" "$PYTHON"
    echo "$WEB_SCREEN" > "$WEB_SCREEN_FILE"
    echo "$WORKER_SCREEN" > "$WORKER_SCREEN_FILE"
    START_MODE="screen"
else
    nohup "$PYTHON" "$RUNNER" worker "$ROOT_DIR" "$RUNTIME_ROOT" "$PORT" \
        "$ENV_FILE" "$PYTHON" </dev/null &
    WORKER_PID=$!
    echo "$WORKER_PID" > "$WORKER_PID_FILE"
    nohup "$PYTHON" "$RUNNER" web "$ROOT_DIR" "$RUNTIME_ROOT" "$PORT" \
        "$ENV_FILE" "$PYTHON" </dev/null &
    WEB_PID=$!
    echo "$WEB_PID" > "$WEB_PID_FILE"
    START_MODE="pid"
fi

cleanup_failed_start() {
    if [ "$START_MODE" = "screen" ]; then
        screen -S "$WEB_SCREEN" -X quit >/dev/null 2>&1 || true
        screen -S "$WORKER_SCREEN" -X quit >/dev/null 2>&1 || true
        rm -f "$WEB_SCREEN_FILE" "$WORKER_SCREEN_FILE"
    else
        kill "$WEB_PID" "$WORKER_PID" >/dev/null 2>&1 || true
        rm -f "$WEB_PID_FILE" "$WORKER_PID_FILE"
    fi
}

deadline=$(($(date +%s) + 90))
while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -fs --max-time 2 "http://127.0.0.1:$PORT/api/health" >/dev/null; then
        echo "Parallel Price Mixer is ready: http://127.0.0.1:$PORT"
        echo "Process mode: $START_MODE"
        echo "Runtime: $RUNTIME_ROOT"
        exit 0
    fi
    sleep 0.5
done

echo "Price Mixer did not become healthy within 90 seconds."
tail -n 80 "$LOG_DIR/parallel-web.log" || true
cleanup_failed_start
exit 1
