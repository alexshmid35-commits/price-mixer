#!/bin/zsh
# Price Mixer — Start Server (macOS)

cd "$(dirname "$0")"

PYTHON=""
PORT=5001
PID_FILE="$(dirname "$0")/server.pid"

# --- [1/5] Find Python 3 ---
echo "[1/5] Checking Python 3..."
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

if [ -z "$PYTHON" ]; then
    echo ""
    echo "Python 3 not found."
    echo "Install it via Homebrew:  brew install python"
    echo "Or download from:         https://www.python.org/downloads/"
    echo ""
    read -k 1 "?Press any key to exit..."
    exit 1
fi

# --- [2/5] Check if already running ---
echo "[2/5] Checking if server is already running..."
if curl -s --max-time 2 "http://127.0.0.1:$PORT" > /dev/null 2>&1; then
    echo "      Server is already running. Opening browser..."
    open "http://127.0.0.1:$PORT"
    exit 0
fi

# --- [3/5] Check dependencies ---
echo "[3/5] Checking dependencies..."
if ! "$PYTHON" -c "import flask, pandas, numpy, requests, openpyxl, xlrd, gspread, oauth2client" &>/dev/null; then
    echo "      Some packages are missing. Installing from requirements.txt..."
    "$PYTHON" -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo ""
        echo "Failed to install dependencies."
        echo "Try running:  $PYTHON -m pip install -r requirements.txt"
        echo ""
        read -k 1 "?Press any key to exit..."
        exit 1
    fi
fi

# --- [4/5] Start server in background ---
echo "[4/5] Starting server..."
"$PYTHON" app.py > server_stdout.log 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
echo "      PID: $SERVER_PID  (saved to server.pid)"

# --- [5/5] Wait and open browser ---
echo "[5/5] Waiting for server to start..."
DEADLINE=$(($(date +%s) + 20))
while [ $(date +%s) -lt $DEADLINE ]; do
    if curl -s --max-time 1 "http://127.0.0.1:$PORT" > /dev/null 2>&1; then
        echo "      Server is up!"
        open "http://127.0.0.1:$PORT"
        echo ""
        echo "Price Mixer running at http://127.0.0.1:$PORT"
        echo "Logs: server_stdout.log"
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
echo "Server did not respond on http://127.0.0.1:$PORT within 20 seconds."
echo "Check server_stdout.log for errors."
echo ""
exit 1
