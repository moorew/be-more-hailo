import subprocess
import logging
import os
import re
from .config import WHISPER_CMD, WHISPER_MODEL

logger = logging.getLogger(__name__)

def transcribe_audio(audio_filepath: str) -> str:
    """
    Converts any audio file to 16kHz WAV and runs whisper.cpp to transcribe it.
    """
    if not os.path.exists(audio_filepath):
        logger.error(f"Audio file not found: {audio_filepath}")
        return ""

    temp_wav = f"{audio_filepath}_16k.wav"

    try:
        # 1. Convert audio to 16kHz mono WAV (required by whisper.cpp)
        logger.info(f"Converting {audio_filepath} to 16kHz WAV for whisper.cpp CPU inference...")
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_filepath, "-ar", "16000", "-ac", "1", temp_wav],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # 2. Run whisper.cpp
        logger.info(f"Running whisper.cpp transcription on the CPU... CMD: {' '.join(cmd)}")
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8").strip()
        except subprocess.CalledProcessError as e:
            output_err = e.output.decode("utf-8") if e.output else "No output"
            logger.error(f"Whisper CPU process failed: {e}. Output: {output_err}")
            return ""

        # 3. Clean up output (remove timestamps like [00:00:00.000 --> 00:00:02.000] or [BLANK_AUDIO])
        output = re.sub(r'\[.*?\]', '', output).strip()

        # Fix capitalization of BMO
        output = re.sub(r'\b[Bb]emo\b', 'BMO', output)
        output = re.sub(r'\b[Bb]eemo\b', 'BMO', output)
        
        # Clean hallucinated whispers from silence
        lowered = output.lower()
        hallucinations = [
            "[silence]", "(silence)", "you", "thanks for watching!", 
            "[blank_audio]", "thank you.", "thank you", "thanks."
        ]
        
        # If output is purely punctuation/noise (no letters or numbers) or a known hallucination
        if lowered in hallucinations or not re.search(r'[a-zA-Z0-9]', lowered):
            return ""

        return output

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg or Whisper CPU process failed: {e}")
        return ""
    except Exception as e:
        logger.error(f"Transcription Error: {e}")
        return ""
    finally:
        # Clean up the temporary 16k wav file
        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except Exception as e:
                logger.warning(f"Could not remove temp file {temp_wav}: {e}")
