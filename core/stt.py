import subprocess
import logging
import os
import re
from .config import WHISPER_CMD, WHISPER_MODEL

logger = logging.getLogger(__name__)

def transcribe_audio(audio_filepath: str) -> str:
    """
    Run whisper.cpp on a 16 kHz mono WAV file produced by record_audio().
    The recording side now down-samples in NumPy, so the ffmpeg pre-conversion
    step has been removed (saves ~50–150 ms per turn on Pi 5 SD storage).
    """
    if not os.path.exists(audio_filepath):
        logger.error(f"Audio file not found: {audio_filepath}")
        return ""

    try:
        # Run whisper.cpp directly on the 16 kHz WAV.
        # -nt  no timestamps (we strip them anyway, skip the compute)
        # -t 3 leave one of the Pi 5's four cores free for Piper / Tk so we
        #      don't thermal-throttle when STT and TTS overlap mid-turn
        # -l en force English, skipping the language-detection pass
        cmd = [WHISPER_CMD, "-m", WHISPER_MODEL, "-f", audio_filepath, "-nt", "-t", "3", "-l", "en"]
        logger.info(f"Running whisper.cpp transcription on the CPU... CMD: {' '.join(cmd)}")
        try:
            # stderr=DEVNULL: whisper prints verbose debug/timing info to stderr.
            # We only want the clean transcript from stdout.
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Whisper CPU process failed with exit code {e.returncode}")
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
        
        # Whisper often hallucinates sound descriptions when mic picks up silence or
        # ambient audio — e.g. "(eerie music)", "(background music)", "[SOUND]".
        # Reject any output that is entirely inside parentheses or brackets.
        is_parenthetical = bool(re.match(r'^\s*[\(\[].*[\)\]]\s*$', output.strip()))
        
        # If output is purely punctuation/noise (no letters or numbers) or a known hallucination
        if is_parenthetical or lowered in hallucinations or not re.search(r'[a-zA-Z0-9]', lowered):
            logger.info(f"Whisper hallucination filtered: {repr(output)}")
            return ""

        return output


    except subprocess.CalledProcessError as e:
        logger.error(f"Whisper CPU process failed: {e}")
        return ""
    except Exception as e:
        logger.error(f"Transcription Error: {e}")
        return ""
