#!/bin/bash

echo "Setting up BMO Web UI Environment..."

# Check if python3-venv is installed (common issue on Debian/Ubuntu/Raspberry Pi OS)
if ! dpkg -s python3-venv >/dev/null 2>&1; then
    echo "python3-venv is not installed. Installing it now..."
    sudo apt-get update
    sudo apt-get install -y python3-venv
fi

# Create the virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment 'venv'..."
    python3 -m venv venv
else
    echo "Virtual environment 'venv' already exists."
fi

# Activate the virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing requirements..."
pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo "To start the web server, run: ./start_web.sh"
