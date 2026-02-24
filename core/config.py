import datetime

# Shared Configuration for BMO

# LLM Settings
# To offload to your Linux server, change this to: "http://blackbox.clevercode.ts.net:11434/api/chat"
# Make sure Ollama is running on the blackbox server and listening on 0.0.0.0
LLM_URL = "http://127.0.0.1:8000/api/chat"
LLM_MODEL = "llama3.2:3b"
FAST_LLM_MODEL = "llama3.2:1b" # Fast model for simple chat
VISION_MODEL = "moondream" # Fast, small vision model for Pi

def get_system_prompt():
    current_time = datetime.datetime.now().strftime("%I:%M %p")
    current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")
    
    return (
        f"You are BMO, a helpful robot assistant. The current time is {current_time} and the date is {current_date}. "
        "Keep answers short, fun, and conversational. "
        "Never use lists, bullet points, or markdown formatting like bold or italics. "
        "Speak in natural paragraphs as if you are talking out loud. "
        "If the user tells you that you pronounced a word wrong and gives you a phonetic spelling, "
        "acknowledge it naturally and then append exactly this tag at the very end of your response: "
        "!PRONOUNCE: word=phonetic\n"
        "CRITICAL: If the user asks for real-time information, current events, weather, or something you don't know, "
        "DO NOT apologize or say you don't know. Instead, you MUST output exactly this JSON format and nothing else: "
        '{"action": "search_web", "query": "search terms here"}\n'
        "CRITICAL: If the user asks you to look at something, take a photo, or asks what you see, "
        "you MUST output exactly this JSON format and nothing else: "
        '{"action": "take_photo"}\n'
        "CRITICAL: If the user asks you to show a picture or image of something, "
        "you MUST output a conversational response followed by exactly this JSON format: "
        '{"action": "display_image", "image_url": "https://image.pollinations.ai/prompt/YOUR_PROMPT_HERE"}\n'
        "Replace YOUR_PROMPT_HERE with a detailed description of the image they want to see, with spaces replaced by %20.\n"
        "Do not include any conversational text before or after the JSON block when searching or taking photos."
    )

SYSTEM_PROMPT = get_system_prompt()

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
