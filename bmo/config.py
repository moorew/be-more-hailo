# HARDWARE SETTINGS (USB MIC)
MIC_INDEX = 0
MIC_RATE = 48000
WAKE_THRESHOLD = 0.5
WAKE_WORD_MODEL = "./wakeword.onnx"

# MODELS
LLM_URL = "http://127.0.0.1:8000/api/chat"
LLM_MODEL = "llama3.2:3b"

# PATHS
WHISPER_CMD = "./whisper.cpp/main" # Or similar, check path
WHISPER_MODEL = "./whisper.cpp/models/ggml-base.en.bin"
PIPER_CMD = "./piper/piper"
PIPER_MODEL = "./piper/en_GB-semaine-medium.onnx"
