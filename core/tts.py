import subprocess
import logging
import os
import re
import json
from .config import PIPER_CMD, PIPER_MODEL, ALSA_DEVICE

logger = logging.getLogger(__name__)

PRONUNCIATION_FILE = "pronunciations.json"

def load_pronunciations() -> dict:
    """Loads the pronunciation dictionary from a JSON file."""
    if os.path.exists(PRONUNCIATION_FILE):
        try:
            with open(PRONUNCIATION_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading pronunciations: {e}")
    
    # Default dictionary if file doesn't exist or fails to load
    default_dict = {
        "cheesy": "cheezy",
        "poutine": "poo-teen",
        "bmo": "beemo"
    }
    save_pronunciations(default_dict)
    return default_dict

def save_pronunciations(pronunciations: dict):
    """Saves the pronunciation dictionary to a JSON file."""
    try:
        with open(PRONUNCIATION_FILE, "w") as f:
            json.dump(pronunciations, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving pronunciations: {e}")

def add_pronunciation(word: str, phonetic: str):
    """Adds a new pronunciation rule and saves it."""
    pronunciations = load_pronunciations()
    pronunciations[word.lower()] = phonetic
    save_pronunciations(pronunciations)

def replace_years_with_words(text: str) -> str:
    """Converts 4-digit years into their spoken equivalents (e.g., 1980 -> nineteen eighty)."""
    def number_to_words(n):
        units = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
        tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
        if 0 <= n < 20:
            return units[n]
        else:
            return (tens[n // 10] + " " + units[n % 10]).strip()

    def year_to_words(match):
        year_str = match.group(0)
        year = int(year_str)
        if 1000 <= year <= 1999:
            first_half = year // 100
            second_half = year % 100
            if second_half == 0:
                return f"{number_to_words(first_half)} hundred"
            elif second_half < 10:
                return f"{number_to_words(first_half)} oh {number_to_words(second_half)}"
            else:
                return f"{number_to_words(first_half)} {number_to_words(second_half)}"
        elif 2000 <= year <= 2009:
            second_half = year % 100
            if second_half == 0:
                return "two thousand"
            else:
                return f"two thousand and {number_to_words(second_half)}"
        elif 2010 <= year <= 2099:
            first_half = year // 100
            second_half = year % 100
            if second_half == 0:
                return f"{number_to_words(first_half)} hundred"
            elif second_half < 10:
                 return f"{number_to_words(first_half)} oh {number_to_words(second_half)}"
            else:
                return f"{number_to_words(first_half)} {number_to_words(second_half)}"
        return year_str

    # Match 4 digit years that are likely years (starting with 10-20)
    # and not immediately preceded or followed by other digits
    return re.sub(r'\b(1[0-9]{3}|20[0-9]{2})\b', year_to_words, text)

def clean_text_for_speech(text: str) -> str:
    """Removes markdown and special characters that shouldn't be spoken."""
    # Convert years to words first (e.g., 1980 -> nineteen eighty)
    text = replace_years_with_words(text)
    # Remove JSON blocks
    text = re.sub(r'\{.*?\}', '', text, flags=re.DOTALL)
    # Replace newlines with spaces to prevent shell line breaks during Piper TTS
    text = text.replace('\n', ' ').replace('\r', ' ')
    # Remove asterisks used for emphasis or actions (e.g., *beep boop*)
    text = text.replace('*', '')
    # Remove other common markdown like bold/italics, headers, and list bullets
    text = re.sub(r'[_~`#\-]', '', text)
    # Replace common abbreviations with spoken words
    text = re.sub(r'\bkm/h\b', 'kilometers per hour', text, flags=re.IGNORECASE)
    text = re.sub(r'\bmph\b', 'miles per hour', text, flags=re.IGNORECASE)
    # Replace slashes in units (e.g., m/s, km/h) with " per "
    text = re.sub(r'([a-zA-Z])\/([a-zA-Z])', r'\1 per \2', text)
    # Remove URLs
    text = re.sub(r'http[s]?://\S+', '', text)
    # Remove emojis and other symbols (keep ASCII, common punctuation, and accents)
    text = re.sub(r'[^\x00-\x7F\xC0-\xFF\u0100-\u017F\u0180-\u024F\u1E00-\u1EFF\u2018-\u201F\u2028-\u202F]', '', text)
    
    # Apply pronunciation fixes (case-insensitive)
    pronunciations = load_pronunciations()
    for word, replacement in pronunciations.items():
        # Use regex word boundaries (\b) to ensure we only replace whole words
        pattern = r"\b" + re.escape(word) + r"\b"
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
    return text.strip()

def play_audio_on_hardware(text: str):
    """Plays audio directly out of the Pi's speakers using Piper and aplay."""
    try:
        clean_text = clean_text_for_speech(text)
        if not clean_text or not any(c.isalnum() for c in clean_text):
            return
            
        logger.info(f"Playing audio on hardware: {clean_text[:30]}...")
        # Escape single quotes in text to prevent shell injection
        safe_text = clean_text.replace("'", "'\\''")
        piper_cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_raw | aplay -D {ALSA_DEVICE} -r 22050 -f S16_LE -t raw"
        subprocess.run(piper_cmd, shell=True, check=True)
    except Exception as e:
        logger.error(f"Hardware TTS Error: {e}")

def generate_audio_file(text: str, filename: str) -> str:
    """Generates a WAV file using Piper for the browser to play."""
    try:
        clean_text = clean_text_for_speech(text)
        if not clean_text or not any(c.isalnum() for c in clean_text):
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
