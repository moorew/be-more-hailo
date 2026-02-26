#!/bin/bash
echo "Starting BMO Web UI..."

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Please run ./setup_web.sh first."
    exit 1
fi

# Activate the virtual environment
source venv/bin/activate

# Ensure requirements are up to date
pip install -r requirements.txt > /dev/null 2>&1

# Run the web app
python3 web_app.py
