# Be More Agent — Hailo-10H Edition

<p align="center">
  <img src="bmo_irl.jpg" height="300" alt="BMO On-Device" />
  <img src="bmo-web.png" height="300" alt="BMO Web Interface" />
</p>

A fork of [@brenpoly's be-more-agent](https://github.com/brenpoly/be-more-agent) project, updated to run on the **Raspberry Pi 5** with the **Hailo-10H AI HAT+**. The agent listens for a wake word, transcribes speech, queries a local LLM, and speaks its response — all on-device, with no cloud services required.

This fork adds a headless **web interface**, a shared `core/` module layer used by both interfaces, and updated support for the Hailo NPU hardware.

---

## What runs where

| Component | Where it runs | Notes |
|-----------|--------------|-------|
| LLM (`qwen2.5-instruct:1.5b`) | Hailo-10H NPU | via `hailo-ollama` |
| Vision (`qwen2-vl-instruct:2b`) | Hailo-10H NPU | optional; requires camera |
| STT (Whisper base.en) | CPU | via `whisper.cpp`; NPU path causes PCIe timeouts |
| TTS (Piper) | CPU | streams sentence-by-sentence while LLM generates |
| Wake word (openWakeWord) | CPU | "Hey BMO" custom model |

STT runs on the CPU by design. Pushing 16kHz audio arrays through the Hailo PCIe bus caused consistent 15+ second timeouts during development. `whisper.cpp` on the quad-core ARM is fast enough and keeps the NPU free for inference.

---

## Interfaces

### On-Device (`agent_hailo.py`)
Runs on the Pi with a screen, USB microphone, and USB speaker attached. Displays animated faces via a Tkinter GUI and handles the full wake word → record → transcribe → respond → speak loop locally.

After each response, BMO stays in "Still listening..." mode for 8 seconds so you can continue a conversation without re-saying the wake word.

### Web (`web_app.py`)
A FastAPI server with a browser-based UI. You hold a button to record audio, which is sent to the Pi over WebSockets. The Pi transcribes, queries the LLM, and sends back a response audio file for playback in your browser.

The web interface includes:
- **Debug panel** — shows conversation history and server logs
- **Pronunciation override** — corrects how Piper pronounces specific words
- **LLM status indicator** — shows whether the NPU model is ready
- **Hands-free mode** — enables wake word detection so you don't need to hold the button
- **Pi Audio toggle** — routes audio to the Pi's physical speaker instead of browser playback

---

## Secure remote access

Modern browsers block microphone access unless the page is served over HTTPS. For the web interface, [Tailscale](https://tailscale.com/) provides a simple solution:

1. Install Tailscale on the Pi and your client device
2. Enable [HTTPS certificates](https://tailscale.com/kb/1153/enabling-https/) in the Tailscale admin console
3. On the Pi, run:
   ```bash
   tailscale serve --bg --https=443 localhost:8080
   ```
4. Access the web UI at `https://<your-pi-hostname>.ts.net`

---

## Hardware

- Raspberry Pi 5 (4GB or 8GB recommended)
- Hailo-10H AI HAT+ (required for NPU features)
- USB microphone and speaker (for on-device mode)
- HDMI or DSI display (for on-device GUI)
- Raspberry Pi Camera Module (optional, for vision/photo features)

---

## Project structure

```
be-more-agent/
├── agent_hailo.py          # On-device GUI application
├── web_app.py              # FastAPI web server
├── core/
│   ├── config.py           # All configuration (models, devices, paths)
│   ├── llm.py              # LLM inference, web search, conversation history
│   ├── tts.py              # Text-to-speech via Piper
│   └── stt.py              # Speech-to-text via whisper.cpp
├── templates/              # Jinja2 HTML templates for the web UI
├── static/                 # CSS, JS, favicon
├── setup.sh                # Automated installation script
├── setup_services.sh       # Installs systemd background services
├── start_web.sh            # Starts the web server
├── start_agent.sh          # Starts the on-device GUI
├── requirements.txt        # Python dependencies
├── wakeword.onnx           # OpenWakeWord model
├── piper/                  # Piper TTS engine and voice model
├── models/                 # Whisper model weights
├── whisper.cpp/            # Compiled whisper.cpp STT binary
└── faces/ sounds/          # GUI assets
```

---

## Installation

### Prerequisites

- Raspberry Pi OS (64-bit, current stable)
- `hailo-ollama` installed and running — follow [Hailo's documentation](https://github.com/hailo-ai/hailo-ollama) for setup

### Automated install

```bash
curl -sSL https://raw.githubusercontent.com/moorew/be-more-hailo/main/setup.sh | bash
cd be-more-agent
```

The script will:
- Install system packages including `libcamera-apps` for camera support
- Download and extract the Piper TTS engine
- Clone and compile `whisper.cpp`
- Download the `ggml-base.en` Whisper model
- Create a Python virtual environment and install dependencies
- Pull `qwen2.5-instruct:1.5b` (LLM) and `qwen2-vl-instruct:2b` (vision) via `hailo-ollama`
- Check camera availability and report if tools are missing

### Manual install

```bash
git clone https://github.com/moorew/be-more-hailo.git be-more-agent
cd be-more-agent
chmod +x *.sh
./setup.sh
```

---

## Running

**Web server:**
```bash
source venv/bin/activate
./start_web.sh
```
Open `http://<YOUR_PI_IP>:8080` in a browser (or your Tailscale HTTPS address for microphone access).

**On-device GUI:**
```bash
source venv/bin/activate
./start_agent.sh
```

**Background services (auto-start on boot):**
```bash
./setup_services.sh
```
Then manage with `sudo systemctl start|stop|restart bmo-web` or `bmo-ollama`.

---

## Configuration

All settings are in `core/config.py`. The most commonly changed values:

```python
# LLM models (must be pulled via hailo-ollama)
LLM_MODEL       = "qwen2.5-instruct:1.5b"
FAST_LLM_MODEL  = "qwen2.5-instruct:1.5b"
VISION_MODEL    = "qwen2-vl-instruct:2b"

# Audio device for local hardware playback (run `aplay -l` to find yours)
# The USB speaker is typically on a different card from the mic — check both.
ALSA_DEVICE = "plughw:UACDemoV10,0"

# Microphone device index (run `python3 -c "import sounddevice as sd; print(sd.query_devices())"`)
MIC_DEVICE_INDEX = 1
MIC_SAMPLE_RATE  = 48000

# STT binary and model
WHISPER_CMD   = "./whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = "./models/ggml-base.en.bin"
```

Environment variables override any of these at runtime:
```bash
export ALSA_DEVICE="plughw:2,0"
```

---

## Dual-model routing (optional)

By default, all queries go to a single model (`qwen2.5-instruct:1.5b`). To route longer or more complex queries to a larger model:

1. Pull the larger model via `hailo-ollama`
2. Set `LLM_MODEL` to the larger model name in `core/config.py`
3. Keep `FAST_LLM_MODEL` pointing to `qwen2.5-instruct:1.5b`

Short, simple prompts (under 15 words, no complex keywords) stay on the fast model. Longer or more complex ones are routed to `LLM_MODEL`.

Note: swapping models on the Hailo-10H takes a few seconds on the first query after a switch.

---

## Camera and vision

If you have a Raspberry Pi Camera Module connected:

1. Enable the camera interface in `raspi-config`
2. Install camera tools if not already present:
   ```bash
   sudo apt install -y libcamera-apps
   ```
3. Ask BMO to take a photo or look at something — the agent captures a frame with `rpicam-still` or `libcamera-still` and sends it to the vision model (`qwen2-vl-instruct:2b`) on the NPU

If no camera is found, BMO will say so rather than crashing.

---

## Customisation

**Personality:** Edit the system prompt returned by `get_system_prompt()` in `core/config.py`.

**Faces:** Place PNG sequences in `faces/<state>/`. The GUI loops through all images in each folder.

**Sounds:** Put `.wav` files in `sounds/<category>/`. BMO picks one at random per event.

**Wake word:** Replace `wakeword.onnx` with any OpenWakeWord-compatible model.

---

## Credits

The original project is entirely the work of [@brenpoly](https://github.com/brenpoly/be-more-agent). This fork adds Hailo NPU support, the web interface, and various fixes — but the core concept and character are theirs.

**"BMO"** and **"Adventure Time"** are trademarks of Cartoon Network (Warner Bros. Discovery). This is a fan project for personal and educational use only, not affiliated with or endorsed by Cartoon Network.

---

## License

MIT — see [LICENSE](LICENSE).
