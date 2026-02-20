from . import config
import logging
import subprocess

def transcribe_audio(filename):
    """
    Convert 48k audio to 16k and run Whisper
    """
    logging.info("Encoding for Whisper...")
    temp_wav = "input_16k.wav"
    subprocess.run(["ffmpeg", "-y", "-i", filename, "-ar", "16000", "-ac", "1", temp_wav], 
                   check=True, stderr=subprocess.DEVNULL)
    
    cmd = [config.WHISPER_CMD, "-m", config.WHISPER_MODEL, "-f", temp_wav, "-nt"]
    
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        # Clean [BLANK_AUDIO] or timestamp artifacts
        # e.g. [00:00:00.000 --> 00:00:02.000] Hello
        import re
        output = re.sub(r'\[.*?\]', '', output).strip()
        return output
    except Exception as e:
        logging.error(f"Whisper Error: {e}")
        return ""
