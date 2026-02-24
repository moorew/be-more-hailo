# Shared Configuration for BMO

# LLM Settings
# To offload to your Linux server, change this to: "http://blackbox.clevercode.ts.net:11434/api/chat"
# Make sure Ollama is running on the blackbox server and listening on 0.0.0.0
LLM_URL = "http://blackbox.clevercode.ts.net:11434/api/chat"
LLM_MODEL = "llama3.2:3b"
SYSTEM_PROMPT = (
    "You are BMO, a helpful robot assistant. Keep answers short, fun, and conversational. "
    "Never use lists, bullet points, or markdown formatting like bold or italics. "
    "Speak in natural paragraphs as if you are talking out loud. "
    "If the user tells you that you pronounced a word wrong and gives you a phonetic spelling, "
    "acknowledge it naturally and then append exactly this tag at the very end of your response: "
    "!PRONOUNCE: word=phonetic\n"
    "If the user asks for real-time information, current events, weather, or something you don't know, "
    "you MUST output exactly this JSON format and nothing else: "
    '{"action": "search_web", "query": "search terms here"}\n'
    "Do not include any conversational text before or after the JSON block when searching."
)

# TTS Settings
PIPER_CMD = "./piper/piper"
PIPER_MODEL = "./piper/en_GB-semaine-medium.onnx"

# STT Settings (Whisper.cpp)
WHISPER_CMD = "./whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = "./whisper.cpp/models/ggml-base.en.bin"

# Audio Settings
MIC_DEVICE_INDEX = 1
MIC_SAMPLE_RATE = 48000
WAKE_WORD_MODEL = "./wakeword.onnx"
WAKE_WORD_THRESHOLD = 0.5
