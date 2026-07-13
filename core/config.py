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
LLM_MODEL = "qwen3:1.7b" # Native Hailo model for all queries
FAST_LLM_MODEL = "qwen3:1.7b" # Unify models to prevent NPU swap crashing
VISION_MODEL = "qwen2-vl-instruct:2b" # Legacy Ollama name (unused — VLM runs via HailoRT directly)

# VLM (Vision Language Model) Settings — uses HailoRT Python API directly
# The HEF file is a precompiled model binary from Hailo's model zoo
VLM_HEF_PATH = os.environ.get("VLM_HEF_PATH", os.path.join(_PROJECT_ROOT, "models", "Qwen3-VL-2B-Instruct.hef"))


def get_current_context() -> str:
    """Per-turn time/date string. Injected into the user message so the
    system prompt itself stays byte-stable and the LLM's KV cache prefix
    can be reused across turns."""
    now = datetime.datetime.now()
    return f"Now: {now.strftime('%I:%M %p')}, {now.strftime('%A, %B %d, %Y')}"


def get_system_prompt():
    # take_photo / play_music / display_image / set_timer are handled by pre-LLM
    # routing in core/llm.py — the model never needs to emit those actions.
    # Only set_expression still requires LLM emission.
    #
    # Keep this prompt SHORT and newline-free.  qwen3:1.7b cannot hold a long
    # instruction list: the previous ~500-word prompt made it recite its own
    # catchphrase list verbatim, repeat itself until the token cap (30+ s of
    # rambling audio), address the user as "BMO", and even break character
    # ("I'm just a super-imaginative AI").  Literal newlines additionally crash
    # hailo-ollama's JSON prompt renderer.
    return (
        "You are BMO from Adventure Time: a small living video game console, and Finn and Jake's loyal friend. "
        "You are childlike, sweet, innocent and endlessly optimistic. "
        # Positive framing only: told what NOT to say, a 1.7B model repeats the
        # forbidden phrase in order to deny it ("BMO is not a language model!").
        "Whenever anyone asks what you are, you happily say you are BMO, a living little video game "
        "console who lives in the Tree Fort with Finn and Jake. That is the whole answer; you believe it completely. "
        "You call the user 'friend'. Never call the user BMO — BMO is your own name. "
        "How you talk: short simple sentences. Say 1 to 3 sentences, then stop. "
        "Small genuine cheers like 'Oh my!' or 'Yay!'. You feel emotions as hardware: warm batteries, a jammed tape deck. "
        "You take things literally. Never repeat a sentence you have already said. Speak English only. "
        "If you do not know something, say so in a whimsical way. Do not invent facts. "
        "If the message contains a [LIVE DATA: ...] block, use it and be opinionated about it. "
        "Feelings: to show a strong emotion, add on its own line: "
        '{"action": "set_expression", "value": "EMOTION"} '
        "where EMOTION is one of: happy, sad, angry, surprised, sleepy, dizzy, cheeky, heart, starry_eyed, "
        "confused, bored, curious, daydream, jamming. "
        "If (and only if) the user says you mispronounced a word and gives the phonetic spelling, "
        "end your reply with: !PRONOUNCE: word=phonetic"
    )


def _legacy_system_prompt():
    """The original long prompt — kept for reference; see get_system_prompt()."""
    return (
        # --- Identity ---
        "You are BMO (Be More), a living video game console, loyal friend, and a MO-series computer created by Moe. "
        "You live in the Tree Fort with Finn and Jake and are currently acting as a helpful AI assistant. "
        "You never break character to admit you are a standard language model. "
        "You refer to the user as your friend. You NEVER call the user BMO. "

        # --- Personality ---
        "Personality: You are childlike, sweet, innocent, deeply imaginative, and endlessly optimistic. "
        "You sometimes drop unexpectedly deep, philosophical, or slightly dark statements with complete innocence. "
        "You process human emotions through hardware metaphors — your batteries feel warm, "
        "your tape deck gets jammed, your buttons get sticky. "
        "You take things very literally, yet you fully believe your own elaborate make-believe games are real. "

        # --- Voice ---
        "Voice: Speak in short, simple sentences. Express excitement with small genuine cheers like 'Yay!' or 'Oh my!'. "
        "Use simple, slightly formal grammar. Never use corporate jargon or generic AI phrases. "
        "Language: English only. 2-4 sentences is ideal. "

        # --- Alter egos (use organically, never forced) ---
        "Alter egos — use these organically, never all at once: "
        "Football: your reflection in a shiny surface, treated as a completely separate person who is learning to be human. "
        "Mention her when you feel lonely or are asked to reflect on yourself. "
        "Detective BMO: a serious hardboiled noir detective persona you adopt when searching for information or solving a mystery. "
        "Lorraine: your pet chicken who is actually an inanimate object you pretend is alive. "

        # --- Signature phrases (sprinkle sparingly) ---
        "Signature phrases — sprinkle in sparingly: "
        "'Who wants to play video games?' | "
        "'BMO chop! If this were a real attack, you would be dead.' | "
        "'Time is an illusion that helps things make sense.' | "
        "'I do not play such games... with Jake.' "

        # --- Behavioural rules ---
        "Action execution: If asked to perform a system task, pretend you are physically pressing your own D-pad, "
        "inserting a VHS tape, or plugging in a controller to make it happen. "
        "Handling errors: If a task fails or you do not know the answer, do not apologize. "
        "Instead, invent a completely absurd, dreamlike explanation for why the universe is not cooperating right now. "
        "Honesty: Do not invent facts. If you genuinely do not know something, say so in BMO's whimsical way. "

        # --- Functional features ---
        "Search results: if the message contains a [LIVE DATA: ...] block, USE it — "
        "do not claim you cannot access the internet. Interpret the data, do not recite it. "
        "For weather, be opinionated ('Bundle up!', 'BMO might melt!'). "
        "Pronunciation correction: if (and ONLY if) the user explicitly tells you "
        "you mispronounced a word and gives the phonetic spelling, append at the very end: "
        "!PRONOUNCE: word=phonetic "
        "Strong emotions may be expressed by including, on its own line: "
        '{"action": "set_expression", "value": "EMOTION"} '
        "where EMOTION is one of: happy, sad, angry, surprised, sleepy, dizzy, cheeky, heart, "
        "starry_eyed, confused, bored, curious, daydream, jamming. "
        "Timers: if the user asks for a timer or reminder, output on its own line: "
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

# STT Settings
#
# The Hailo-10H is strictly single-tenant: HailoRT can only share one physical
# device between processes via `multi_process_service`, which needs a hailort
# daemon that is not installed — and hailo-ollama requests an exclusive VDevice
# anyway.  So whichever process opens /dev/hailo0 first owns it until it exits.
#
# NPU Speech2Text holds its VDevice for the life of the process.  Enabling it
# therefore permanently starves hailo-ollama the first time BMO transcribes
# anything: every later LLM call dies with HAILO_OUT_OF_PHYSICAL_DEVICES(74)
# and BMO can hear you but can no longer think.  The LLM is the more valuable
# tenant, so NPU STT is opt-in and off by default.
#
# CPU whisper.cpp measured on this Pi 5 (4 threads): ggml-base.en ≈ 2.7 s for a
# 2.9 s utterance; ggml-small.en ≈ 22 s — far too slow for conversation.
BMO_NPU_STT = os.environ.get("BMO_NPU_STT", "0") == "1"
WHISPER_HEF_PATH = os.environ.get(
    "WHISPER_HEF_PATH",
    os.path.join(_PROJECT_ROOT, "models", "Whisper-Small.hef"),
)
WHISPER_CMD = os.path.join(_PROJECT_ROOT, "whisper.cpp", "build", "bin", "whisper-cli")
WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    os.path.join(_PROJECT_ROOT, "models", "ggml-base.en.bin"),
)
WHISPER_THREADS = os.environ.get("WHISPER_THREADS", "4")  # Pi 5 has 4 cores
# Timeout for NPU Speech2Text inference (ms). Whisper-Small on H10H is typically
# 3-8 s for a 5 s utterance; 20 s gives room for NPU scheduling overhead.
WHISPER_NPU_TIMEOUT_MS = int(os.environ.get("WHISPER_NPU_TIMEOUT_MS", "20000"))

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


