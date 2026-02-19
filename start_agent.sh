#!/bin/bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Ensure model is available
python3 ensure_model.py

# Run the agent using python3
exec python3 agent.py "$@"

