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

# --- AUTO-Start LLM Server (hailo-ollama on port 8000) ---
if ! lsof -i :8000 >/dev/null; then
    echo "Starting hailo-ollama server on port 8000..."
    export OLLAMA_HOST=0.0.0.0:8000
    nohup hailo-ollama serve > /tmp/ollama.log 2>&1 &
    # Give it a moment to initialize
    sleep 5
else
    echo "LLM Server already running on port 8000."
fi

# Set display for GUI if not set (assuming user is logged in on :0)
if [ -z "${DISPLAY:-}" ]; then
    export DISPLAY=:0
fi

# Run the agent using python3 (Use new Hailo optimized agent)
exec python3 agent_hailo.py "$@"

