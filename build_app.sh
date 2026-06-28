#!/bin/bash
set -e

OS_TYPE="$(uname -s)"
SCRIPT_DIR="$(dirname "$0")"

if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo "🍎 macOS detected. Delegating to build-mac.sh..."
    chmod +x "$SCRIPT_DIR/build-scripts/build-mac.sh"
    "$SCRIPT_DIR/build-scripts/build-mac.sh"
elif [[ "$OS_TYPE" == "Linux" ]]; then
    echo "🐧 Linux detected. Delegating to build-linux.sh..."
    chmod +x "$SCRIPT_DIR/build-scripts/build-linux.sh"
    "$SCRIPT_DIR/build-scripts/build-linux.sh"
else
    echo "⚠️ Unsupported or unknown platform: $OS_TYPE"
    echo "Please use Windows PowerShell and execute desktop_app/build-scripts/build-win.ps1 directly."
    exit 1
fi

