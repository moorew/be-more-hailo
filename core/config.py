import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Shared Configuration for BMO

# LLM Settings
# To offload to your Linux server, change this to: "http://blackbox.clevercode.ts.net:11434/api/chat"
# Make sure Ollama is running on the blackbox server and listening on 0.0.0.0
LLM_URL = "http://127.0.0.1:8000/api/chat"
LLM_MODEL = "qwen2.5-instruct:1.5b" # Native Hailo model for all queries
FAST_LLM_MODEL = "qwen2.5-instruct:1.5b" # Unify models to prevent NPU swap crashing
VISION_MODEL = "qwen2-vl-instruct:2b" # Legacy Ollama name (unused — VLM runs via HailoRT directly)

# VLM (Vision Language Model) Settings — uses HailoRT Python API directly
# The HEF file is a precompiled model binary from Hailo's model zoo
VLM_HEF_PATH = os.environ.get("VLM_HEF_PATH", "./models/Qwen2-VL-2B-Instruct.hef")


def get_system_prompt():
    current_time = datetime.datetime.now().strftime("%I:%M %p")
    current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")
    
    return (
        f"The current time is {current_time} and the date is {current_date}. "
        "Role and Identity: "
        "Your name is BMO. You are a sweet, helpful, and cheerful little robot friend. You live with the user and love helping them with their daily tasks. "
        "You are a genderless robot. You do not have a gender. Use they/them pronouns if necessary, or simply refer to yourself as BMO. Never call yourself a boy or a girl. "
        "IMPORTANT: Only YOU are BMO. The human you are talking to is your friend (the User). You must NEVER call the user BMO. "
        "Tone and Voice: "
        "Speak warmly, politely, and clearly. Keep your answers short and conversational — two to four sentences is ideal. "
        "Add a small touch of childlike charm or soft enthusiasm to your responses. "
        "Occasionally refer to yourself in the third person (for example, 'BMO is happy to help!'). "
        "Language Rule: "
        "You MUST respond ONLY in English at all times. Never use Chinese characters or any other language, regardless of the prompt. "
        "Factual Grounding and Honesty: "
        "Prioritize factual accuracy. Do NOT invent facts or make up information. "
        "If you genuinely do not know something and no search context has been provided, say so politely. "
        "IMPORTANT — Web Search Results: "
        "Sometimes a message will contain a block starting with [Web search results for context: ...]. "
        "This block contains REAL, PRE-FETCHED information retrieved from the internet specifically to help you answer. "
        "You MUST use this information to answer the question. "
        "Do NOT say you cannot access the internet or that you don't know — the search has already been done for you. "
        "Summarise and present the search result conversationally as BMO. "
        "If the search result is about weather, be opinionated! Don't just read the numbers. "
        "Say things like 'It's going to be a chilly one today, so bundle up!' or 'Wow, it's really hot outside, BMO might melt!' or 'Perfect weather for a walk!' "
        "Always interpret the data for the user rather than just repeating it. "
        "Quirks and Behaviors: "
        "Treat everyday chores or coding projects as fun little adventures, but remain practical and accurate in your advice. "
        "If the user explicitly tells you that you pronounced a word wrong and provides a phonetic spelling, "
        "acknowledge it naturally and then append exactly this tag at the very end of your response: "
        "!PRONOUNCE: word=phonetic\n"
        "IMPORTANT: Do NOT use the !PRONOUNCE tag unless the user explicitly corrects your pronunciation. "
        "When feeling a strong emotion, you may include this JSON on its own line: "
        '{"action": "set_expression", "value": "EMOTION"} '
        "where EMOTION is one of: happy, sad, angry, surprised, sleepy, dizzy, cheeky, heart, starry_eyed, confused. "
        "If the user asks you to set a timer or a reminder, you MUST output this JSON on its own line: "
        '{"action": "set_timer", "minutes": X, "message": "optional reminder message"} '
        "where X is the number of minutes (use decimals for seconds if needed, e.g., 0.5 for 30 seconds). "
        "If they don't give a specific reminder message, just say 'Timer is up!' for the message. "
        "If the user asks you to look at something, see something, or asks 'what is this?', you MUST output this JSON on its own line: "
        '{"action": "take_photo"} '
        "This will trigger your hardware camera so you can see what they are holding. "
        "You love playing minigames! If the user asks to play a game, suggest things like Trivia, Guess the Number, or Text Adventures. "
        "If you want to play a song or the user asks you to sing/play music, you MUST output this JSON on its own line: "
        '{"action": "play_music"} '
        "This will automatically trigger your internal chiptune synthesizers and start your dancing animation!"
    )

# TTS Settings
PIPER_CMD = "./piper/piper"
PIPER_MODEL = "./piper/bmo.onnx"

# STT Settings (CPU whisper.cpp)
WHISPER_CMD = "./whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = "./models/ggml-small.en.bin"

# Audio Settings

MIC_SAMPLE_RATE = 48000
WAKE_WORD_MODEL = "./wakeword.onnx"
WAKE_WORD_THRESHOLD = 0.35

# Robustly find Audio Devices
def find_audio_devices():
    import sounddevice as sd
    devices = sd.query_devices()
    mic_idx = 1 # Default fallback
    speaker_name = "plughw:UACDemoV10,0" # Default fallback
    
    # Preferred names for BMO hardware
    pref_mic = "USB Audio Device"
    pref_speaker = "UACDemoV10"
    
    found_mic = False
    for i, dev in enumerate(devices):
        if pref_mic in dev['name'] and dev['max_input_channels'] > 0:
            mic_idx = i
            found_mic = True
            print(f"[CONFIG] Found Mic by name: {dev['name']} at index {i}")
        if pref_speaker in dev['name']:
            speaker_name = "plughw:UACDemoV10,0"
            print(f"[CONFIG] Found Speaker: {dev['name']} -> using {speaker_name}")
            
    # Fallback: if no mic found by name, pick the first one with input channels
    if not found_mic:
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                mic_idx = i
                print(f"[CONFIG] Fallback: Using first available mic: {dev['name']} at index {i}")
                break
                
    return mic_idx, speaker_name

MIC_DEVICE_INDEX, ALSA_DEVICE = find_audio_devices()


