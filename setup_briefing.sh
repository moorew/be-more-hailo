#!/bin/bash
# Morning briefing setup: location, news feeds, window, repeating items and
# the optional extras (calendar, Home Assistant, camera).  Works from any
# folder: it finds BMO's directory and virtual environment itself.
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"
if [ ! -x venv/bin/python ]; then
    echo "BMO's virtual environment isn't set up yet: run ./install.sh first." >&2
    exit 1
fi
exec venv/bin/python -m core.briefing --setup "$@"
