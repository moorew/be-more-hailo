# Be More Agent 🤖 (Hailo-10H & Web Edition)
**A Customizable, Offline-First AI Agent for Raspberry Pi**

[![Watch the Demo](https://img.youtube.com/vi/l5ggH-YhuAw/maxresdefault.jpg)](https://youtu.be/l5ggH-YhuAw)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-red) ![License](https://img.shields.io/badge/License-MIT-green)

This project turns a Raspberry Pi into a fully functional, conversational AI agent. Unlike cloud-based assistants, this agent runs **100% locally** on your device. It listens for a wake word, processes speech, "thinks" using a local Large Language Model (LLM), and speaks back with a low-latency neural voice.

**Major Upgrade:** This fork has been completely revamped to support the **Hailo-10H NPU** for lightning-fast local AI inference, introduces a **headless web service** alongside the original on-device GUI, and features a unified "core" architecture!

## ✨ What's New in this Version (vs Original)

* **Hailo-10H NPU Support**: Optimized to run on the Raspberry Pi 5 with the Hailo-10H AI accelerator, drastically reducing LLM response times.
* **Dual Interfaces (On-Device GUI & Web App)**: 
  * **On-Device (gent_hailo.py)**: The classic Tkinter-based GUI that displays reactive faces on an attached screen (HDMI/DSI) and listens via a physical USB microphone.
  * **Web Version (web_app.py)**: A responsive, mobile-friendly web interface using FastAPI and WebSockets. Interact with your agent from your phone, tablet, or PC browser!
* **Unified core Architecture**: Both the on-device GUI and the web app share the exact same brain! The logic for LLMs, Text-to-Speech (TTS), and Speech-to-Text (STT) has been extracted into a shared core/ module. Any improvements made to core/ instantly benefit both interfaces.
* **Dual-Model Routing**: Intelligently routes simple queries to a blazing-fast lightweight model (llama3.2:1b) and complex queries to a larger model (llama3.2:3b), ensuring the best balance of speed and intelligence.
* **Service Management**: Run the web agent seamlessly in the background using the provided systemd service scripts.

## 🧠 How It Works: On-Device vs Web

Because of the new modular design, the project can be run in two different ways depending on your needs:

### 1. On-Device Mode (gent_hailo.py)
This is the traditional "robot" mode. You plug a screen, microphone, and speaker directly into the Raspberry Pi.
- **Input**: Uses sounddevice and openwakeword to constantly listen for the wake word ("Hey BMO") via the physical microphone.
- **Processing**: Uses the shared core/ modules to transcribe audio, query the LLM, and generate speech.
- **Output**: Plays audio directly through the Pi's speakers via ALSA/sounddevice and updates the Tkinter GUI with animated faces.

### 2. Web Mode (web_app.py)
This is the "headless" mode. The Pi sits on your network without needing a screen or microphone attached.
- **Input**: You open the web interface on your phone or PC. You hold a button to record audio, which is sent to the Pi via WebSockets.
- **Processing**: Uses the **exact same** core/ modules to transcribe the audio, query the LLM, and generate speech.
- **Output**: The generated audio file and text response are sent back over the WebSocket and played in your browser.

**The Shared core/**: Whether you ask a question via the physical microphone or the web browser, the request is routed through core/llm.py. This means features like **Dual-Model Routing** (picking the 1B or 3B model based on prompt complexity) work identically across both platforms!

## 🛠️ Hardware Requirements

* **Raspberry Pi 5** (Recommended)
* **Hailo-10H AI Accelerator** (Optional but highly recommended for speed)
* USB Microphone & Speaker (For On-Device mode)
* LCD Screen (DSI or HDMI) (For On-Device mode)
* Raspberry Pi Camera Module (Optional for vision features)

---

## 📂 Project Structure

`	ext
be-more-agent/
├── agent_hailo.py             # The On-Device GUI application
├── web_app.py                 # The FastAPI web server application
├── core/                      # Shared modular brain components
│   ├── llm.py                 # LLM inference and dual-model routing
│   ├── tts.py                 # Text-to-Speech (Piper)
│   ├── stt.py                 # Speech-to-Text (Whisper)
│   └── config.py              # System configuration
├── templates/                 # HTML templates for the Web UI
├── static/                    # CSS, JS, and Favicon for the Web UI
├── setup_services.sh          # Script to install systemd services
├── start_web.sh               # Script to launch the web server
├── start_agent.sh             # Script to launch the on-device GUI
├── wakeword.onnx              # OpenWakeWord model (The "Ear")
├── requirements.txt           # Python dependencies
├── whisper.cpp/               # Speech-to-Text engine
├── piper/                     # Piper TTS engine & voice models
├── sounds/                    # Sound effects folder
└── faces/                     # Face images folder
`

---

## 🚀 Installation

### 1. Prerequisites
Ensure your Raspberry Pi OS is up to date.
`ash
sudo apt update && sudo apt upgrade -y
sudo apt install git ffmpeg -y
`

### 2. Install Ollama (with Hailo Support)
This agent relies on [Ollama](https://ollama.com) to run the brain. If you have a Hailo-10H NPU, ensure you install the Hailo-optimized version of Ollama.
`ash
curl -fsSL https://ollama.com/install.sh | sh
`
*Pull the required models:*
`ash
ollama pull llama3.2:3b
ollama pull llama3.2:1b
`

### 3. Clone & Setup
`ash
git clone https://github.com/brenpoly/be-more-agent.git
cd be-more-agent
chmod +x setup.sh setup_web.sh setup_services.sh start_web.sh start_agent.sh
./setup.sh
`
*The setup script will install system libraries, download Piper TTS, and set up the Python virtual environment.*

### 4. Running the Agent

**To run the Web Server:**
`ash
source venv/bin/activate
./start_web.sh
`
Then, open your browser and navigate to http://<YOUR_PI_IP>:8000.

**To run the On-Device GUI:**
`ash
source venv/bin/activate
./start_agent.sh
`

### 5. Run as a Background Service (Optional)
To have the web agent start automatically when the Pi boots:
`ash
./setup_services.sh
`

---

## ⚙️ Configuration (core/config.py)

You can modify the models, URLs, and system prompts in core/config.py:

`python
LLM_URL = "http://127.0.0.1:8000/api/chat"
LLM_MODEL = "llama3.2:3b"
FAST_LLM_MODEL = "llama3.2:1b" # Fast model for simple chat
VISION_MODEL = "moondream"
`

---

## 🧠 How Dual-Model Routing Works

To provide the fastest possible responses, the core/llm.py module analyzes your prompt before sending it to the LLM. 
- If your prompt is **short** (<= 15 words) and does **not** contain complex keywords (like "explain", "code", "story", "how"), it is routed to the FAST_LLM_MODEL (llama3.2:1b).
- If your prompt is **long** or requires deep reasoning, it is routed to the primary LLM_MODEL (llama3.2:3b).

This ensures snappy conversational replies while retaining the ability to handle complex tasks!

---

## 🎨 Customizing Your Character

This software is a generic framework. You can give it a new personality by replacing the assets:
1.  **Faces:** The script looks for PNG sequences in aces/[state]/. It will loop through all images found in the folder.
2.  **Sounds:** Put multiple .wav files in the sounds/[category]/ folders. The robot will pick one at random each time (e.g., different "thinking" hums or "error" buzzes).

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.

## ⚖️ Legal Disclaimer
**"BMO"** and **"Adventure Time"** are trademarks of **Cartoon Network** (Warner Bros. Discovery).
This project is a **fan creation** built for educational and hobbyist purposes only. It is **not** affiliated with, endorsed by, or connected to Cartoon Network or the official Adventure Time brand in any way.
