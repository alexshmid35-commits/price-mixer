#!/bin/zsh
# Совместимость со старым ярлыком. Единый лаунчер сам проверяет весь стек.
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT_DIR/start_server.sh"
