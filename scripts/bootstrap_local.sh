#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PRICE_MIXER_BOOTSTRAP_PYTHON:-$(command -v python3.11 || command -v python3)}"

if [ -z "$PYTHON_BIN" ]; then
    echo "Python 3.11 is required."
    exit 1
fi

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$ROOT_DIR/.venv"
fi

"$ROOT_DIR/.venv/bin/python" -m pip install --upgrade pip
"$ROOT_DIR/.venv/bin/python" -m pip install -r "$ROOT_DIR/requirements-dev.txt"

echo "Price Mixer environment is ready: $ROOT_DIR/.venv"
echo "The same environment serves the mixer, worker, and embedded Onliner parser."
