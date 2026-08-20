#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="${PRICE_MIXER_RUNTIME_ROOT:-$ROOT_DIR/../PriceMixer_next_runtime_2026-07-24}"
PARSER_DIR="${PRICE_MIXER_PARSER_DIR:-$ROOT_DIR/onliner-parser}"
DEFAULT_PYTHON="$ROOT_DIR/.venv/bin/python"

PRICE_MIXER_PYTHON="${PRICE_MIXER_PYTHON:-$DEFAULT_PYTHON}" \
    "$ROOT_DIR/scripts/start_primary_local.sh" "$RUNTIME_ROOT" "$PARSER_DIR"

open "http://127.0.0.1:5001"
echo "Price Mixer и парсер работают в фоне."
