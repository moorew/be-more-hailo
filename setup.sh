#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🤖 Pi Local Assistant Setup Script${NC}"

# 1. Install System Dependencies (The "Hidden" Requirements)
echo -e "${YELLOW}[1/8] Installing System Tools (apt)...${NC}"
sudo apt update
sudo apt install -y python3-tk libasound2-dev libportaudio2 libatlas-base-dev cmake build-essential espeak-ng git curl

# 2. Clone Repository (if run via curl outside repo)
echo -e "${YELLOW}[2/8] Checking for Repository...${NC}"
if [ ! -f "requirements.txt" ] || [ ! -f "agent_hailo.py" ]; then
    if [ -d "be-more-agent" ]; then
        echo -e "${YELLOW}Directory 'be-more-agent' already exists. Entering it...${NC}"
        cd be-more-agent
    else
        echo -e "${YELLOW}Downloading be-more-agent repository...${NC}"
        git clone https://github.com/moorew/be-more-hailo.git be-more-agent
        cd be-more-agent
    fi
    # Make scripts executable
    chmod +x *.sh
fi

# 3. Create Folders
echo -e "${YELLOW}[3/8] Creating Folders...${NC}"
mkdir -p piper
mkdir -p sounds/greeting_sounds
mkdir -p sounds/thinking_sounds
mkdir -p sounds/ack_sounds
mkdir -p sounds/error_sounds
mkdir -p faces/idle
mkdir -p faces/listening
mkdir -p faces/thinking
mkdir -p faces/speaking
mkdir -p faces/error
mkdir -p faces/warmup

# 4. Download Piper (Architecture Check)
echo -e "${YELLOW}[4/8] Setting up Piper TTS...${NC}"
ARCH=$(uname -m)
if [ "$ARCH" == "aarch64" ]; then
    # FIXED: Using the specific 2023.11.14-2 release known to work on Pi
    wget -O piper.tar.gz https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar -xvf piper.tar.gz -C piper --strip-components=1
    rm piper.tar.gz
else
    echo -e "${RED}⚠️  Not on Raspberry Pi (aarch64). Skipping Piper download.${NC}"
fi

# 5. Download Voice Model
echo -e "${YELLOW}[5/8] Downloading Voice Model & STT pre-reqs...${NC}"
cd piper
wget -nc -O en_GB-semaine-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx
wget -nc -O en_GB-semaine-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx.json
cd ..

# Make directory for Whisper
mkdir -p models
echo -e "${YELLOW}Downloading Whisper-Base.hef from GitHub Releases...${NC}"
wget -nc -O models/Whisper-Base.hef https://github.com/moorew/be-more-hailo/releases/latest/download/Whisper-Base.hef

# 6. Install Python Libraries
echo -e "${YELLOW}[6/8] Installing Python Libraries...${NC}"
# Check if venv exists, if not create it
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt



# 7. Pull AI Models
echo -e "${YELLOW}[7/8] Checking AI Models...${NC}"
echo -e "${YELLOW}Pulling Hailo-10H optimized models via hailo-ollama API...${NC}"
curl --silent http://localhost:8000/api/pull -H 'Content-Type: application/json' -d '{ "model": "qwen2.5-instruct:1.5b", "stream": false }'
echo -e "${GREEN}Models pulled successfully!${NC}"

# 7. OpenWakeWord Model (Added this back so the user has a default)
if [ ! -f "wakeword.onnx" ]; then
    echo -e "${YELLOW}Downloading default 'Hey Jarvis' wake word...${NC}"
    curl -L -o wakeword.onnx https://github.com/dscripka/openWakeWord/raw/main/openwakeword/resources/models/hey_jarvis_v0.1.onnx
fi

# 8. Create Desktop Shortcut
echo -e "${YELLOW}[8/8] Creating Desktop Shortcut...${NC}"
cat << EOF > ~/Desktop/BMO.desktop
[Desktop Entry]
Name=BMO
Comment=Launch Be More Agent
Exec=bash -c 'cd "$PWD" && ./start_agent.sh'
Icon=$PWD/static/favicon.png
Terminal=true
Type=Application
Categories=Utility;Application;
EOF
chmod +x ~/Desktop/BMO.desktop

# Also place in applications menu
mkdir -p ~/.local/share/applications/
cp ~/Desktop/BMO.desktop ~/.local/share/applications/
echo -e "${GREEN}Desktop shortcut created!${NC}"

echo -e "${GREEN}✨ Setup Complete! To start BMO, you can now click the 'BMO' icon on your desktop, or run './start_agent.sh' / './start_web.sh' from the terminal.${NC}"
