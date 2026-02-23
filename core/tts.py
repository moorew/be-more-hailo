import subprocess
import logging
import os
import re
from .config import PIPER_CMD, PIPER_MODEL

logger = logging.getLogger(__name__)

def clean_text_for_speech(text: str) -> str:
    """Removes markdown and special characters that shouldn't be spoken."""
    # Remove asterisks used for emphasis or actions (e.g., *beep boop*)
    text = text.replace('*', '')
    # Remove other common markdown like bold/italics
    text = re.sub(r'[_~`]', '', text)
    # Remove URLs
    text = re.sub(r'http[s]?://\S+', '', text)
    return text.strip()

def play_audio_on_hardware(text: str):
    """Plays audio directly out of the Pi's speakers using Piper and aplay."""
    try:
        clean_text = clean_text_for_speech(text)
        if not clean_text:
            return
            
        logger.info(f"Playing audio on hardware: {clean_text[:30]}...")
        # Escape single quotes in text to prevent shell injection
        safe_text = clean_text.replace("'", "'\\''")
        piper_cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_raw | aplay -r 22050 -f S16_LE -t raw"
        subprocess.run(piper_cmd, shell=True, check=True)
    except Exception as e:
        logger.error(f"Hardware TTS Error: {e}")

def generate_audio_file(text: str, filename: str) -> str:
    """Generates a WAV file using Piper for the browser to play."""
    try:
        clean_text = clean_text_for_speech(text)
        if not clean_text:
            return None
            
        logger.info(f"Generating audio file: {filename}")
        safe_text = clean_text.replace("'", "'\\''")
        filepath = os.path.join("static", "audio", filename)
        piper_cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_file {filepath}"
        subprocess.run(piper_cmd, shell=True, check=True)
        return f"/static/audio/{filename}"
    except Exception as e:
        logger.error(f"File TTS Error: {e}")
        return None
