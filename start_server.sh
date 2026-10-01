#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="${PRICE_MIXER_RUNTIME_ROOT:-$ROOT_DIR/../PriceMixer_next_runtime_2026-07-24}"
PYTHON="$ROOT_DIR/.venv/bin/python"
WORKER_PID_FILE="$RUNTIME_ROOT/state/parallel-worker.pid"

web_healthy() {
    curl -fsS --max-time 2 "http://127.0.0.1:5001/api/health" >/dev/null 2>&1
}

parser_healthy() {
    curl -fsS --max-time 2 \
        "http://127.0.0.1:5055/api/price-mixer/status" >/dev/null 2>&1
}

worker_healthy() {
    [ -f "$WORKER_PID_FILE" ] || return 1
    local pid
    pid="$(tr -dc '0-9' < "$WORKER_PID_FILE")"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" >/dev/null 2>&1 || return 1
    ps -p "$pid" -o command= 2>/dev/null | grep -q "price_mixer.workers.durable_worker"
}

stop_legacy_web() {
    local pid_file="$ROOT_DIR/server.pid"
    [ -f "$pid_file" ] || return 0
    local pid command
    pid="$(tr -dc '0-9' < "$pid_file")"
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
        command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        if [[ "$command" == *"app.py"* ]]; then
            kill "$pid" >/dev/null 2>&1 || true
            sleep 1
        fi
    fi
    rm -f "$pid_file"
}

echo "[1/5] Проверяю структуру Price Mixer..."
if [ ! -f "$RUNTIME_ROOT/state/app_settings.json" ]; then
    echo "Не найдена актуальная runtime-папка: $RUNTIME_ROOT"
    exit 1
fi
if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "Не найден файл настроек: $ROOT_DIR/.env"
    exit 1
fi
if [ ! -f "$ROOT_DIR/onliner-parser/ui_server.py" ]; then
    echo "Не найден встроенный Onliner-парсер."
    exit 1
fi

echo "[2/5] Проверяю Python и зависимости..."
if [ ! -x "$PYTHON" ]; then
    python3 -m venv "$ROOT_DIR/.venv"
fi
if ! "$PYTHON" -c \
    "import dotenv, flask, pandas, numpy, requests, openpyxl, xlrd, gspread, oauth2client" \
    >/dev/null 2>&1; then
    "$PYTHON" -m pip install -r "$ROOT_DIR/requirements.txt"
fi

echo "[3/5] Проверяю текущие процессы..."
if web_healthy && parser_healthy && worker_healthy; then
    echo "Все компоненты уже работают."
    open "http://127.0.0.1:5001"
    exit 0
fi

if web_healthy || parser_healthy || worker_healthy; then
    echo "Найден неполный старый запуск. Перезапускаю стек целиком..."
    "$ROOT_DIR/scripts/stop_primary_local.sh" "$RUNTIME_ROOT" >/dev/null 2>&1 || true
fi
stop_legacy_web

echo "[4/5] Запускаю web, worker и Onliner-парсер..."
PRICE_MIXER_PYTHON="$PYTHON" \
    "$ROOT_DIR/scripts/start_primary_local.sh" \
    "$RUNTIME_ROOT" "$ROOT_DIR/onliner-parser"

echo "[5/5] Открываю Price Mixer..."
open "http://127.0.0.1:5001"
echo "Price Mixer полностью запущен. Для следующего запуска используй только start_server.sh."
