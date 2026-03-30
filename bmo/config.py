# HARDWARE SETTINGS (USB MIC)
MIC_INDEX = 0
MIC_RATE = 48000
WAKE_THRESHOLD = 0.35
WAKE_WORD_MODEL = "./wakeword.onnx"

# MODELS
LLM_URL = "http://127.0.0.1:8000/api/chat"
LLM_MODEL = "qwen2.5-instruct:1.5b"

WHISPER_CMD = "./whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = "./models/ggml-base.en.bin"
PIPER_CMD = "./piper/piper"
PIPER_MODEL = "./piper/bmo.onnx"
