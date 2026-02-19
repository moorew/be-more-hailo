#!/bin/bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Ensure model is available
# SKIPPED: Hailo server reports model "in store" but API returns empty list/500 on pull.
# Assuming model is present based on server logs to allow boot.
# python3 ensure_model.py

# Set display for GUI if not set (assuming user is logged in on :0)
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
fi

# Run the agent using python3
exec python3 agent.py "$@"

