#!/bin/zsh
# Price Mixer — Install Requirements (macOS)

cd "$(dirname "$0")"

PYTHON=""

echo "Looking for Python 3..."
for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if command -v "$candidate" &>/dev/null; then
        VERSION=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        if [ "$VERSION" = "3" ]; then
            PYTHON="$candidate"
            echo "Using: $PYTHON ($("$candidate" --version 2>&1))"
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

echo ""
echo "Installing packages from requirements.txt..."
"$PYTHON" -m pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo ""
    echo "Done. All dependencies installed."
else
    echo ""
    echo "Some packages failed to install. Check the errors above."
fi

echo ""
read -k 1 "?Press any key to exit..."
