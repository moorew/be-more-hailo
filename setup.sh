#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}BMO Agent Setup${NC}"

# Detect the installed HailoRT version — used for hailo-ollama build tag
# and for downloading a VLM HEF compiled against the same runtime.
HAILORT_VER=$(dpkg-query -W -f='${Version}' h10-hailort 2>/dev/null || echo "5.1.1")
echo -e "${YELLOW}Detected HailoRT version: ${HAILORT_VER}${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# 1. System packages
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/13] Installing system packages...${NC}"
sudo apt update
sudo apt install -y \
    python3-tk python3-venv libasound2-dev libportaudio2 libopenblas-dev \
    cmake build-essential git curl ffmpeg libssl-dev \
    libcamera-apps python3-libcamera \
    hailo-h10-all  # Hailo-10H PCIe driver, firmware, and runtime

# ─────────────────────────────────────────────────────────────────────────────
# 2. Fix Hailo driver conflict
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/13] Checking Hailo NPU driver...${NC}"
# The old hailo_pci (Hailo-8) driver conflicts with hailo1x_pci (Hailo-10H).
# Both create a 'hailo_chardev' sysfs class, so if hailo_pci loads first,
# hailo1x_pci fails to create /dev/hailo0. Blacklist the old driver.
if lsmod | grep -q "^hailo_pci "; then
    echo "  Blacklisting legacy hailo_pci driver (conflicts with hailo1x_pci)..."
    echo "blacklist hailo_pci" | sudo tee /etc/modprobe.d/blacklist-hailo-legacy.conf > /dev/null
    sudo rmmod hailo1x_pci 2>/dev/null
    sudo rmmod hailo_pci 2>/dev/null
    sudo modprobe hailo1x_pci
    echo -e "${GREEN}  Driver conflict resolved.${NC}"
elif [ ! -e /dev/hailo0 ]; then
    echo "  /dev/hailo0 not found — blacklisting legacy driver and reloading..."
    echo "blacklist hailo_pci" | sudo tee /etc/modprobe.d/blacklist-hailo-legacy.conf > /dev/null
    sudo rmmod hailo1x_pci 2>/dev/null
    sudo rmmod hailo_pci 2>/dev/null
    sudo modprobe hailo1x_pci 2>/dev/null
    if [ -e /dev/hailo0 ]; then
        echo -e "${GREEN}  /dev/hailo0 is now available.${NC}"
    else
        echo -e "${RED}  Warning: /dev/hailo0 still not found. Check 'dmesg | grep hailo' for details.${NC}"
    fi
else
    echo -e "${GREEN}  /dev/hailo0 found — Hailo NPU is ready.${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Clone repository (if run via curl outside the repo)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/13] Checking repository...${NC}"
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
# 4. Create asset folders
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/13] Creating asset folders...${NC}"
mkdir -p piper models
mkdir -p sounds/greeting_sounds sounds/thinking_sounds sounds/ack_sounds sounds/error_sounds
mkdir -p faces/idle faces/listening faces/thinking faces/speaking faces/error faces/warmup

# ─────────────────────────────────────────────────────────────────────────────
# 5. Piper TTS engine
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[5/13] Setting up Piper TTS...${NC}"
ARCH=$(uname -m)
if [ "$ARCH" == "aarch64" ]; then
    wget -q -O piper.tar.gz https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar -xf piper.tar.gz -C piper --strip-components=1
    rm piper.tar.gz
else
    echo -e "${RED}Not on aarch64 — skipping Piper download.${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. Piper voice model
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[6/13] Downloading voice models...${NC}"

# 6.1 Base Voice (En-GB Semaine)
BASE_VOICE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium"
wget -nc -q -O piper/en_GB-semaine-medium.onnx      "$BASE_VOICE/en_GB-semaine-medium.onnx"
wget -nc -q -O piper/en_GB-semaine-medium.onnx.json "$BASE_VOICE/en_GB-semaine-medium.onnx.json"

# 6.2 Custom BMO Voice (Fine-tuned from Amy)
BMO_VOICE="https://github.com/brenpoly/be-more-agent/releases/download/v1.0-voice"
wget -nc -q -O piper/bmo.onnx      "$BMO_VOICE/bmo.onnx"
wget -nc -q -O piper/bmo.onnx.json "$BMO_VOICE/bmo.onnx.json"

# ─────────────────────────────────────────────────────────────────────────────
# 7. whisper.cpp (CPU-based STT)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[7/13] Building whisper.cpp for CPU STT...${NC}"
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
# 8. Build and install hailo-ollama (LLM server for Hailo NPU)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[8/13] Setting up hailo-ollama...${NC}"
if command -v hailo-ollama &>/dev/null; then
    echo -e "${GREEN}  hailo-ollama is already installed.${NC}"
else
    echo "  Building hailo-ollama from source (this takes a few minutes)..."
    HAILO_OLLAMA_VERSION="v${HAILORT_VER}"
    BUILD_DIR="/tmp/hailo_model_zoo_genai"
    rm -rf "$BUILD_DIR"
    git clone --branch "$HAILO_OLLAMA_VERSION" --depth 1 \
        https://github.com/hailo-ai/hailo_model_zoo_genai.git "$BUILD_DIR"
    mkdir -p "$BUILD_DIR/build"
    cmake -B "$BUILD_DIR/build" -S "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
    cmake --build "$BUILD_DIR/build" --config Release -j$(nproc)

    # Install binary
    sudo cp "$BUILD_DIR/build/src/apps/server/hailo-ollama" /usr/bin/hailo-ollama
    sudo chmod +x /usr/bin/hailo-ollama

    # Install config and model manifests
    mkdir -p ~/.config/hailo-ollama
    cp "$BUILD_DIR/config/hailo-ollama.json" ~/.config/hailo-ollama/
    mkdir -p ~/.local/share/hailo-ollama
    cp -r "$BUILD_DIR/models/" ~/.local/share/hailo-ollama/

    rm -rf "$BUILD_DIR"
    echo -e "${GREEN}  hailo-ollama installed successfully.${NC}"
fi

# Start hailo-ollama for model pulling
if ! curl -sf http://localhost:8000/api/tags > /dev/null 2>&1; then
    echo "  Starting hailo-ollama server..."
    export OLLAMA_HOST=0.0.0.0:8000
    nohup hailo-ollama serve > /tmp/ollama.log 2>&1 &
    sleep 3
fi

# ─────────────────────────────────────────────────────────────────────────────
# 9. Python environment and dependencies
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[9/13] Installing Python dependencies...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Enable system site-packages so the venv can import hailo_platform
# (installed as a system deb package, not available on PyPI).
if grep -q "include-system-site-packages = false" venv/pyvenv.cfg 2>/dev/null; then
    sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' venv/pyvenv.cfg
    echo "  Enabled system site-packages for hailo_platform access."
fi

source venv/bin/activate
pip install --upgrade pip setuptools wheel -q
pip install -r requirements.txt -q

# ─────────────────────────────────────────────────────────────────────────────
# 10. Pull LLM model via hailo-ollama
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[10/13] Pulling LLM model via hailo-ollama...${NC}"
OLLAMA_URL="http://localhost:8000/api"

echo "  Pulling LLM: qwen2.5-instruct:1.5b..."
curl -sf "$OLLAMA_URL/pull" \
    -H 'Content-Type: application/json' \
    -d '{"model": "qwen2.5-instruct:1.5b", "stream": false}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Done.' if d.get('status')=='success' else f'  Warning: {d}')" \
    2>/dev/null || echo -e "${RED}  Could not reach hailo-ollama at $OLLAMA_URL. Start it first if needed.${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# 11. Download VLM HEF (Vision Language Model for camera features)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[11/13] Downloading VLM model (Qwen2-VL-2B — ~2.2 GB)...${NC}"
VLM_HEF="models/Qwen2-VL-2B-Instruct.hef"
if [ -f "$VLM_HEF" ]; then
    echo -e "${GREEN}  VLM HEF already present.${NC}"
else
    # Download from Hailo's public CDN, matching the installed HailoRT version.
    # Use wget with retries — curl sometimes fails on this 2+ GB file.
    VLM_URL="https://dev-public.hailo.ai/v${HAILORT_VER}/blob/Qwen2-VL-2B-Instruct.hef"
    echo "  Downloading from $VLM_URL ..."
    wget -c --tries=3 -O "$VLM_HEF" "$VLM_URL" 2>&1 || {
        echo -e "${RED}  Failed to download VLM HEF. Camera vision will be unavailable.${NC}"
        echo -e "${YELLOW}  You can download it manually later:${NC}"
        echo "    wget -O models/Qwen2-VL-2B-Instruct.hef $VLM_URL"
    }
    if [ -f "$VLM_HEF" ]; then
        SIZE=$(stat --printf="%s" "$VLM_HEF" 2>/dev/null || stat -f "%z" "$VLM_HEF" 2>/dev/null)
        if [ "$SIZE" -gt 100000000 ]; then
            echo -e "${GREEN}  VLM HEF downloaded ($(du -h "$VLM_HEF" | cut -f1)).${NC}"
        else
            echo -e "${RED}  Download appears incomplete (${SIZE} bytes). Re-run setup to retry.${NC}"
            rm -f "$VLM_HEF"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 12. Camera check, wake word model, and misc
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[12/13] Checking camera and wake word...${NC}"
if command -v libcamera-still &>/dev/null || command -v rpicam-still &>/dev/null; then
    echo -e "${GREEN}  Camera tools found. Vision features are enabled.${NC}"
else
    echo -e "${YELLOW}  Camera tools not found in PATH."
    echo -e "  If you have a Pi Camera connected, run: sudo apt install -y libcamera-apps${NC}"
fi

# Wake word model
if [ ! -f "wakeword.onnx" ]; then
    echo -e "${YELLOW}Downloading default wake word model (Hey BMO)...${NC}"
    curl -sL -o wakeword.onnx \
        https://github.com/dscripka/openWakeWord/raw/main/openwakeword/resources/models/hey_jarvis_v0.1.onnx
fi

# ─────────────────────────────────────────────────────────────────────────────
# 13. Desktop shortcut
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[13/13] Creating desktop shortcut...${NC}"
cat <<EOF > ~/Desktop/BMO.desktop
[Desktop Entry]
Name=BMO
Comment=Launch BMO Agent
Exec=bash -c 'cd "$PWD" && ./start_agent.sh'
Icon=$PWD/static/bmo_stylized_icon.png
Terminal=false
Type=Application
Categories=Utility;Application;
EOF
chmod +x ~/Desktop/BMO.desktop
mkdir -p ~/.local/share/applications/
cp ~/Desktop/BMO.desktop ~/.local/share/applications/

echo -e "${GREEN}Setup complete. Run './start_agent.sh' for on-device mode or './start_web.sh' for the web interface.${NC}"
