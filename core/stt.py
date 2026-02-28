import logging
import os
import re
import soundfile as sf
import librosa
import numpy as np
from .config import WHISPER_MODEL

try:
    from hailo_whisper import HailoWhisper
except ImportError:
    HailoWhisper = None
    print("WARNING: hailo-whisper is not installed. STT will fail.")

logger = logging.getLogger(__name__)

# Global inferencer to avoid reloading the HEF model for every sentence
_inferencer = None

def get_inferencer():
    global _inferencer
    if _inferencer is None:
        if HailoWhisper is None:
            logger.error("hailo-whisper library is missing!")
            return None
        
        if not os.path.exists(WHISPER_MODEL):
            logger.error(f"Whisper HEF model not found at: {WHISPER_MODEL}")
            logger.error("Please ensure Whisper-Base.hef is in the models directory.")
            return None
            
        logger.info(f"Loading Hailo Whisper model from {WHISPER_MODEL}...")
        try:
            _inferencer = HailoWhisper(WHISPER_MODEL)
            logger.info("Hailo Whisper model loaded successfully on the NPU.")
        except Exception as e:
            logger.error(f"Failed to load Hailo Whisper model: {e}")
            return None
            
    return _inferencer

def transcribe_audio(audio_filepath: str) -> str:
    """
    Transcribes the audio file using the Hailo-10H NPU via hailo-whisper.
    """
    if not os.path.exists(audio_filepath):
        logger.error(f"Audio file not found: {audio_filepath}")
        return ""

    inferencer = get_inferencer()
    if inferencer is None:
        return ""

    try:
        logger.info(f"Loading and resampling {audio_filepath} to 16kHz for NPU inference...")
        # Load and convert to 16kHz mono explicitly using librosa
        audio_data, _ = librosa.load(audio_filepath, sr=16000, mono=True)
        
        # Write back to a clean 16k wav temp file since HailoWhisper transcribe() takes a file path
        temp_wav = f"{audio_filepath}_16k.wav"
        sf.write(temp_wav, audio_data, 16000)
        
        logger.info("Transcribing audio on the Hailo NPU...")
        result = inferencer.transcribe(temp_wav)
        
        # Clean up temp file
        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except Exception as e:
                logger.warning(f"Could not remove temp file {temp_wav}: {e}")
            
        # Parse the result
        if isinstance(result, dict) and 'text' in result:
            output = result['text'].strip()
        else:
            output = str(result).strip()

        # Clean up tags or timestamp brackets that may leak
        output = re.sub(r'\[.*?\]', '', output).strip()

        # Fix capitalization of BMO
        output = re.sub(r'\b[Bb]emo\b', 'BMO', output)
        output = re.sub(r'\b[Bb]eemo\b', 'BMO', output)

        return output

    except Exception as e:
        logger.error(f"Hailo Transcription Error: {e}")
        return ""
