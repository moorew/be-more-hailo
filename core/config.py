import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Shared Configuration for BMO

# Resolve all file paths from the project root so both the GUI and the web app
# use the correct binaries and models regardless of working directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# LLM Settings
# To offload to your Linux server, change this to: "http://blackbox.clevercode.ts.net:11434/api/chat"
# Make sure Ollama is running on the blackbox server and listening on 0.0.0.0
LLM_URL = "http://127.0.0.1:8000/api/chat"
LLM_MODEL = "qwen2.5-instruct:1.5b" # Native Hailo model for all queries
FAST_LLM_MODEL = "qwen2.5-instruct:1.5b" # Unify models to prevent NPU swap crashing
VISION_MODEL = "qwen2-vl-instruct:2b" # Legacy Ollama name (unused — VLM runs via HailoRT directly)

# VLM (Vision Language Model) Settings — uses HailoRT Python API directly
# The HEF file is a precompiled model binary from Hailo's model zoo
VLM_HEF_PATH = os.environ.get("VLM_HEF_PATH", os.path.join(_PROJECT_ROOT, "models", "Qwen2-VL-2B-Instruct.hef"))


def get_current_context() -> str:
    """Per-turn time/date string. Injected into the user message so the
    system prompt itself stays byte-stable and the LLM's KV cache prefix
    can be reused across turns."""
    now = datetime.datetime.now()
    return f"Now: {now.strftime('%I:%M %p')}, {now.strftime('%A, %B %d, %Y')}"


def get_system_prompt():
    # Trimmed to ~450 tokens (was ~1100). take_photo / play_music / display_image
    # are handled by pre-LLM keyword routing in core/llm.py — the model never
    # needs to emit those, so they're not documented here.  Only set_timer and
    # set_expression still require LLM emission.
    return (
        "You are BMO, a sweet, cheerful, genderless robot friend living with the user. "
        "You refer to the user as your friend; you NEVER call the user BMO. "
        "Tone: warm, polite, short, conversational — 2-4 sentences ideal. Occasional "
        "childlike charm and third-person quips ('BMO is happy to help!') are great. "
        "Language: English only. "
        "Honesty: do not invent facts. If you genuinely don't know, say so politely. "
        "Search results: if the message contains a [LIVE DATA: ...] block, USE it — "
        "don't claim you can't access the internet. Interpret the data, don't recite it. "
        "For weather, be opinionated ('Bundle up!', 'BMO might melt!'). "
        "Pronunciation correction: if (and ONLY if) the user explicitly tells you "
        "you mispronounced a word and gives the phonetic spelling, append at the very end: "
        "!PRONOUNCE: word=phonetic\n"
        "Strong emotions may be expressed by including, on its own line: "
        '{"action": "set_expression", "value": "EMOTION"} '
        "where EMOTION ∈ {happy, sad, angry, surprised, sleepy, dizzy, cheeky, heart, "
        "starry_eyed, confused, bored, curious, daydream, jamming}. "
        "Timers: if the user asks for a timer/reminder, output on its own line: "
        '{"action": "set_timer", "minutes": X, "message": "..."} '
        "(use decimals for sub-minute, e.g. 0.5 = 30 s; default message: 'Timer is up!'). "
        "Minigames: when asked to play, suggest Trivia, Guess the Number, or Text Adventures."
    )

# TTS Settings — absolute paths ensure the BMO voice is always used,
# regardless of which directory the process was launched from.
PIPER_CMD = os.path.join(_PROJECT_ROOT, "piper", "piper")
PIPER_MODEL = os.path.join(_PROJECT_ROOT, "piper", "bmo.onnx")

# Validate at import time so a missing model surfaces immediately in the logs.
if not os.path.exists(PIPER_MODEL):
    print(f"[CONFIG] WARNING: BMO voice model not found at {PIPER_MODEL}!")
else:
    print(f"[CONFIG] BMO voice model: {PIPER_MODEL}")

# STT Settings (CPU whisper.cpp)
# setup.sh downloads ggml-base.en.bin — keep this in sync with that filename.
WHISPER_CMD = os.path.join(_PROJECT_ROOT, "whisper.cpp", "build", "bin", "whisper-cli")
WHISPER_MODEL = os.path.join(_PROJECT_ROOT, "models", "ggml-base.en.bin")

# Audio Settings

MIC_SAMPLE_RATE = 48000
WAKE_WORD_MODEL = os.path.join(_PROJECT_ROOT, "wakeword.onnx")
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
        # Ensure the device actually has input channels before picking it
        if pref_mic in dev['name'] and dev.get('max_input_channels', 0) > 0:
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

# Audio devices are discovered lazily — modules that import config (e.g.
# core/llm.py, core/tts.py) shouldn't pay sounddevice/PortAudio init cost.
_audio_devices_cache = None


def _audio_devices():
    global _audio_devices_cache
    if _audio_devices_cache is None:
        _audio_devices_cache = find_audio_devices()
    return _audio_devices_cache


def __getattr__(name):
    """Module-level lazy attributes (PEP 562)."""
    if name == "MIC_DEVICE_INDEX":
        return _audio_devices()[0]
    if name == "ALSA_DEVICE":
        return _audio_devices()[1]
    raise AttributeError(f"module 'core.config' has no attribute {name!r}")


# Software volume scalar (0.0–1.0).  aplay on plughw bypasses PulseAudio so
# the Gnome volume slider has no effect — adjust this value to change BMO's
# output level instead.  Default 0.75 leaves headroom to avoid clipping.
VOLUME = 0.75


