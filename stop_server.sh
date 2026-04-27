#!/bin/zsh
# Price Mixer v4 REFACTORED — Stop Server (macOS)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/server.pid"

echo "Stopping Price Mixer server..."

KILLED=0

# Try PID file first (clean stop)
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "Stopped process PID $PID"
        KILLED=$((KILLED + 1))
    fi
    rm -f "$PID_FILE"
fi

# Fallback: find any python process running app.py in this directory
while IFS= read -r pid; do
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null && echo "Stopped process PID $pid" && KILLED=$((KILLED + 1))
    fi
done < <(pgrep -f "python.*$SCRIPT_DIR/app\.py" 2>/dev/null)

if [ "$KILLED" -eq 0 ]; then
    echo "No running Price Mixer server found."
else
    echo "Stopped $KILLED process(es)."
fi
