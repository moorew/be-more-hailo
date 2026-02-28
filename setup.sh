#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}BMO Agent Setup${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# 1. System packages
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/9] Installing system packages...${NC}"
sudo apt update
sudo apt install -y \
    python3-tk libasound2-dev libportaudio2 libatlas-base-dev \
    cmake build-essential git curl ffmpeg \
    libcamera-apps python3-libcamera  # Camera support (rpicam-still / libcamera-still)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Clone repository (if run via curl outside the repo)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/9] Checking repository...${NC}"
if [ ! -f "requirements.txt" ] || [ ! -f "agent_hailo.py" ]; then
    if [ -d "be-more-agent" ]; then
        echo "Directory 'be-more-agent' already exists. Entering it..."
        cd be-more-agent
    else
        git clone https://github.com/moorew/be-more-hailo.git be-more-agent
        cd be-more-agent
    fi
    chmod +x *.sh
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Create asset folders
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/9] Creating asset folders...${NC}"
mkdir -p piper models
mkdir -p sounds/greeting_sounds sounds/thinking_sounds sounds/ack_sounds sounds/error_sounds
mkdir -p faces/idle faces/listening faces/thinking faces/speaking faces/error faces/warmup

# ─────────────────────────────────────────────────────────────────────────────
# 4. Piper TTS engine
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/9] Setting up Piper TTS...${NC}"
ARCH=$(uname -m)
if [ "$ARCH" == "aarch64" ]; then
    wget -q -O piper.tar.gz https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar -xf piper.tar.gz -C piper --strip-components=1
    rm piper.tar.gz
else
    echo -e "${RED}Not on aarch64 — skipping Piper download.${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. Piper voice model
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[5/9] Downloading voice model...${NC}"
BASE_VOICE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium"
wget -nc -q -O piper/en_GB-semaine-medium.onnx      "$BASE_VOICE/en_GB-semaine-medium.onnx"
wget -nc -q -O piper/en_GB-semaine-medium.onnx.json "$BASE_VOICE/en_GB-semaine-medium.onnx.json"

# ─────────────────────────────────────────────────────────────────────────────
# 6. whisper.cpp (CPU-based STT)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[6/9] Building whisper.cpp for CPU STT...${NC}"
if [ ! -f "whisper.cpp/build/bin/whisper-cli" ]; then
    if [ ! -d "whisper.cpp" ]; then
        git clone https://github.com/ggerganov/whisper.cpp.git
    fi
    cmake -B whisper.cpp/build -S whisper.cpp -DCMAKE_BUILD_TYPE=Release
    cmake --build whisper.cpp/build --config Release -j$(nproc)
fi

# Download Whisper base.en model
if [ ! -f "models/ggml-base.en.bin" ]; then
    echo -e "${YELLOW}Downloading Whisper base.en model...${NC}"
    wget -q -O models/ggml-base.en.bin \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. Python environment and dependencies
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[7/9] Installing Python dependencies...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip setuptools wheel -q
pip install -r requirements.txt -q

# ─────────────────────────────────────────────────────────────────────────────
# 8. Pull AI models via hailo-ollama
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[8/9] Pulling AI models via hailo-ollama...${NC}"
OLLAMA_URL="http://localhost:8000/api"

echo "  Pulling LLM: qwen2.5-instruct:1.5b..."
curl -sf "$OLLAMA_URL/pull" \
    -H 'Content-Type: application/json' \
    -d '{"model": "qwen2.5-instruct:1.5b", "stream": false}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Done.' if d.get('status')=='success' else f'  Warning: {d}')" \
    2>/dev/null || echo -e "${RED}  Could not reach hailo-ollama at $OLLAMA_URL. Start it first if needed.${NC}"

echo "  Pulling Vision model: qwen2-vl-instruct:2b (optional, for camera features)..."
curl -sf "$OLLAMA_URL/pull" \
    -H 'Content-Type: application/json' \
    -d '{"model": "qwen2-vl-instruct:2b", "stream": false}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Done.' if d.get('status')=='success' else f'  Warning: {d}')" \
    2>/dev/null || echo "  Skipping vision model (hailo-ollama not reachable)."

# ─────────────────────────────────────────────────────────────────────────────
# 8b. Camera check
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}Checking camera availability...${NC}"
if command -v libcamera-still &>/dev/null || command -v rpicam-still &>/dev/null; then
    echo -e "${GREEN}  Camera tools found. Vision features are enabled.${NC}"
else
    echo -e "${YELLOW}  Camera tools not found in PATH."
    echo -e "  If you have a Pi Camera connected, run: sudo apt install -y libcamera-apps${NC}"
fi

# Wake word model
if [ ! -f "wakeword.onnx" ]; then
    echo -e "${YELLOW}Downloading default wake word model (Hey Jarvis)...${NC}"
    curl -sL -o wakeword.onnx \
        https://github.com/dscripka/openWakeWord/raw/main/openwakeword/resources/models/hey_jarvis_v0.1.onnx
fi

# ─────────────────────────────────────────────────────────────────────────────
# 9. Desktop shortcut
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[9/9] Creating desktop shortcut...${NC}"
cat <<EOF > ~/Desktop/BMO.desktop
[Desktop Entry]
Name=BMO
Comment=Launch BMO Agent
Exec=bash -c 'cd "$PWD" && ./start_agent.sh'
Icon=$PWD/static/favicon.png
Terminal=true
Type=Application
Categories=Utility;Application;
EOF
chmod +x ~/Desktop/BMO.desktop
mkdir -p ~/.local/share/applications/
cp ~/Desktop/BMO.desktop ~/.local/share/applications/

echo -e "${GREEN}Setup complete. Run './start_agent.sh' for on-device mode or './start_web.sh' for the web interface.${NC}"
