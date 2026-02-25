#!/bin/bash
echo "Starting BMO Web UI..."

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Please run ./setup_web.sh first."
    exit 1
fi

# Activate the virtual environment
source venv/bin/activate

# Run the web app
python3 web_app.py
