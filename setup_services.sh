#!/bin/bash

echo "Setting up BMO background services..."

# 1. Create the Hailo-Ollama Service
echo "Creating bmo-ollama.service..."
cat << 'EOF' | sudo tee /etc/systemd/system/bmo-ollama.service
[Unit]
Description=BMO Hailo Ollama Service
After=network.target

[Service]
Type=simple
User=clevercode
Environment="OLLAMA_HOST=0.0.0.0:8000"
ExecStart=/usr/bin/hailo-ollama serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# 2. Create the Web UI Service
echo "Creating bmo-web.service..."
cat << 'EOF' | sudo tee /etc/systemd/system/bmo-web.service
[Unit]
Description=BMO Web UI Service
After=network.target bmo-ollama.service
Requires=bmo-ollama.service

[Service]
Type=simple
User=clevercode
WorkingDirectory=/home/clevercode/be-more-agent
ExecStart=/bin/bash /home/clevercode/be-more-agent/start_web.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 3. Fix Permissions
echo "Fixing permissions for the web app..."
sudo chown -R clevercode:clevercode /home/clevercode/be-more-agent
sudo chmod +x /home/clevercode/be-more-agent/*.sh

# 4. Reload systemd, enable, and start the services
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling services to start on boot..."
sudo systemctl enable bmo-ollama.service
sudo systemctl enable bmo-web.service

echo "Starting services now..."
sudo systemctl start bmo-ollama.service
sudo systemctl start bmo-web.service

echo ""
echo "========================================================"
echo "Setup Complete!"
echo "Both the Hailo LLM and the Web UI are now running in the background."
echo "They will automatically start whenever the Pi reboots."
echo "========================================================"
echo "To check the status of the Web UI: sudo systemctl status bmo-web"
echo "To check the status of the LLM:    sudo systemctl status bmo-ollama"
echo "To view the Web UI logs:           journalctl -u bmo-web -f"
echo "========================================================"
