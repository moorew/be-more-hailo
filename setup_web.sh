#!/bin/bash

echo "Setting up BMO Web UI Environment..."

# 1. Install System Dependencies
echo "Installing required system packages (audio, python tools)..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-tk libasound2-dev libportaudio2 libopenblas-dev portaudio19-dev libsndfile1 ffmpeg

# 2. Setup Virtual Environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment 'venv'..."
    python3 -m venv venv
else
    echo "Virtual environment 'venv' already exists."
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Upgrading pip and installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create Systemd Service for Auto-start
echo "Setting up background service (bmo-web.service)..."
cat << EOF | sudo tee /etc/systemd/system/bmo-web.service
[Unit]
Description=BMO Web UI Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PWD
ExecStart=/bin/bash $PWD/start_web.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable bmo-web.service
sudo systemctl start bmo-web.service

# 4. Open automatically on Desktop Boot
echo "Setting up browser auto-start on desktop login..."
mkdir -p ~/.config/autostart
cat <<EOF > ~/.config/autostart/bmo-web.desktop
[Desktop Entry]
Type=Application
Name=BMO Web UI
Exec=chromium-browser --kiosk http://localhost:8080/
X-GNOME-Autostart-enabled=true
EOF

echo ""
echo "=========================================================="
echo "Setup complete! The web server is now running in the background."
echo "It will automatically start when the Pi reboots."
echo "Chromium will also open to BMO automatically on desktop login."
echo "=========================================================="
