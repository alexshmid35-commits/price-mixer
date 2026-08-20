#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="${1:-${PRICE_MIXER_RUNTIME_ROOT:-$ROOT_DIR/runtime}}"
PARSER_DIR="${2:-${PRICE_MIXER_PARSER_DIR:-$ROOT_DIR/onliner-parser}}"
MIXER_PYTHON="${PRICE_MIXER_PYTHON:-$ROOT_DIR/.venv/bin/python}"
PARSER_PYTHON="${PRICE_MIXER_PARSER_PYTHON:-$MIXER_PYTHON}"
ENV_FILE="${PRICE_MIXER_ENV_FILE:-$ROOT_DIR/.env}"
STATE_DIR="$RUNTIME_ROOT/state"
LOG_DIR="$RUNTIME_ROOT/logs"
PARSER_SCREEN="pricemixer-parser-5055"
PARSER_SCREEN_FILE="$STATE_DIR/parallel-parser.screen"

if [ ! -x "$PARSER_PYTHON" ]; then
    echo "Parser Python environment not found: $PARSER_PYTHON"
    exit 1
fi
if [ ! -f "$PARSER_DIR/ui_server.py" ]; then
    echo "Embedded parser not found: $PARSER_DIR/ui_server.py"
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "Environment file not found: $ENV_FILE"
    exit 1
fi
if lsof -tiTCP:5055 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port 5055 is already in use:"
    lsof -nP -iTCP:5055 -sTCP:LISTEN
    exit 1
fi

mkdir -p "$STATE_DIR" "$LOG_DIR"
cd "$ROOT_DIR"
if command -v screen >/dev/null 2>&1; then
    screen -S "$PARSER_SCREEN" -X quit >/dev/null 2>&1 || true
    screen -dmS "$PARSER_SCREEN" \
        "$MIXER_PYTHON" "$ROOT_DIR/scripts/run_parser_component.py" \
        "$PARSER_DIR" "$RUNTIME_ROOT" "$PARSER_PYTHON" "$ENV_FILE"
    echo "$PARSER_SCREEN" > "$PARSER_SCREEN_FILE"
else
    nohup "$MIXER_PYTHON" "$ROOT_DIR/scripts/run_parser_component.py" \
        "$PARSER_DIR" "$RUNTIME_ROOT" "$PARSER_PYTHON" "$ENV_FILE" </dev/null &
fi

cleanup_failed_start() {
    "$ROOT_DIR/scripts/stop_primary_local.sh" "$RUNTIME_ROOT" >/dev/null 2>&1 || true
}

deadline=$(($(date +%s) + 90))
while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -fs --max-time 2 \
        "http://127.0.0.1:5055/api/price-mixer/status" >/dev/null; then
        break
    fi
    sleep 0.5
done
if ! curl -fs --max-time 2 \
    "http://127.0.0.1:5055/api/price-mixer/status" >/dev/null; then
    echo "Parser did not become healthy within 90 seconds."
    tail -n 80 "$LOG_DIR/parallel-parser.log" || true
    cleanup_failed_start
    exit 1
fi

if ! PRICE_MIXER_PYTHON="$MIXER_PYTHON" \
    PRICE_MIXER_ENV_FILE="$ENV_FILE" \
    "$ROOT_DIR/scripts/start_parallel_local.sh" "$RUNTIME_ROOT" 5001; then
    cleanup_failed_start
    exit 1
fi

echo "Primary Price Mixer is ready: http://127.0.0.1:5001"
echo "Onliner parser is ready: http://127.0.0.1:5055"
