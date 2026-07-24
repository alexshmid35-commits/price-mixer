#!/bin/zsh
# Price Mixer v4 REFACTORED — Start Server (macOS)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON=""
PORT=5001
PID_FILE="$SCRIPT_DIR/server.pid"

# --- [1/6] Find Python (prefer .venv) ---
echo "[1/6] Checking Python..."

# Check .venv first
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python3"
    echo "      Using .venv: $PYTHON"
else
    for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
        if command -v "$candidate" &>/dev/null; then
            VERSION=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
            if [ "$VERSION" = "3" ]; then
                PYTHON="$candidate"
                echo "      Found: $PYTHON ($("$candidate" --version 2>&1))"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo ""
    echo "Python 3 not found."
    echo "Install it via Homebrew:  brew install python"
    echo "Or download from:         https://www.python.org/downloads/"
    echo ""
    read -k 1 "?Press any key to exit..."
    exit 1
fi

# --- [2/6] Check if already running ---
echo "[2/6] Checking if server is already running..."
if curl -s --max-time 2 "http://127.0.0.1:$PORT" > /dev/null 2>&1; then
    echo "      Server is already running. Opening browser..."
    open "http://127.0.0.1:$PORT"
    exit 0
fi

# --- [3/6] Check / create venv ---
echo "[3/6] Checking virtual environment..."
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "      Creating .venv..."
    "$PYTHON" -m venv "$SCRIPT_DIR/.venv"
    echo "      Installing dependencies..."
    "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
else
    echo "      .venv exists"
fi

# Use venv python from now on
PYTHON="$SCRIPT_DIR/.venv/bin/python3"

# --- [4/6] Check dependencies ---
echo "[4/6] Checking dependencies..."
if ! "$PYTHON" -c "import flask, pandas, numpy, requests, openpyxl, xlrd, gspread, oauth2client" &>/dev/null; then
    echo "      Some packages missing. Installing..."
    "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
    if [ $? -ne 0 ]; then
        echo ""
        echo "Failed to install dependencies."
        echo ""
        read -k 1 "?Press any key to exit..."
        exit 1
    fi
fi

# --- [5/6] Start server in background ---
echo "[5/6] Starting server..."
nohup "$PYTHON" app.py > server_stdout.log 2>&1 </dev/null &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
echo "      PID: $SERVER_PID  (saved to server.pid)"

# --- [6/6] Wait and open browser ---
echo "[6/6] Waiting for server to start..."
DEADLINE=$(($(date +%s) + 90))
while [ $(date +%s) -lt $DEADLINE ]; do
    if curl -s --max-time 1 "http://127.0.0.1:$PORT" > /dev/null 2>&1; then
        echo "      Server is up!"
        open "http://127.0.0.1:$PORT"
        echo ""
        echo "Price Mixer v4 REFACTORED running at http://127.0.0.1:$PORT"
        echo "Logs: server_stdout.log"
        echo "Auth: credentials are loaded from .env"
        echo "To stop: ./stop_server.sh"
        exit 0
    fi
    # Check if process died early
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo ""
        echo "Server process crashed. Check server_stdout.log for errors."
        echo ""
        exit 1
    fi
    sleep 0.7
done

echo ""
echo "Server did not respond on http://127.0.0.1:$PORT within 90 seconds."
echo "Check server_stdout.log for errors."
echo ""
exit 1
