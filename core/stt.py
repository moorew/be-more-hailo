import subprocess
import logging
import os
import re
import wave
import numpy as np
import sys
from .config import WHISPER_MODEL

# Ensure system packages are available inside the venv so we can access the native Hailo SDK
sys.path.append("/usr/lib/python3/dist-packages")

try:
    from hailo_platform import VDevice
    from hailo_platform.genai import Speech2Text, Speech2TextTask
except ImportError:
    VDevice, Speech2Text, Speech2TextTask = None, None, None
    print("WARNING: hailo_platform is not installed. NPU STT will fail.")

logger = logging.getLogger(__name__)

# Global inferencer to avoid reloading the HEF model for every sentence
_vdevice = None
_speech2text = None
_SHARED_VDEVICE_GROUP_ID = "hailo_shared_vdevice"

def get_inferencer():
    global _vdevice, _speech2text
    if _speech2text is None:
        if Speech2Text is None:
            logger.error("hailo_platform library is missing! Cannot initialize NPU STT.")
            return None
        
        if not os.path.exists(WHISPER_MODEL):
            logger.error(f"Whisper HEF model not found at: {WHISPER_MODEL}")
            return None
            
        logger.info(f"Loading Hailo Whisper model from {WHISPER_MODEL}...")
        try:
            params = VDevice.create_params()
            params.group_id = _SHARED_VDEVICE_GROUP_ID
            _vdevice = VDevice(params)
            
            _speech2text = Speech2Text(_vdevice, WHISPER_MODEL)
            logger.info("Hailo Whisper model loaded successfully on the NPU.")
        except Exception as e:
            logger.error(f"Failed to load Hailo Whisper model: {e}")
            if _vdevice:
                try:
                    _vdevice.release()
                except Exception:
                    pass
                _vdevice = None
            return None
            
    return _speech2text

def transcribe_audio(audio_filepath: str) -> str:
    """
    Transcribes the audio file using the Hailo-10H NPU via hailo_platform.genai.
    """
    if not os.path.exists(audio_filepath):
        logger.error(f"Audio file not found: {audio_filepath}")
        return ""

    inferencer = get_inferencer()
    if inferencer is None:
        return ""

    temp_wav = f"{audio_filepath}_16k.wav"

    try:
        # Convert audio to 16kHz mono WAV 
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_filepath, "-ar", "16000", "-ac", "1", temp_wav],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        with wave.open(temp_wav, 'rb') as wav_file:
            frames = wav_file.getnframes()
            raw_audio = wav_file.readframes(frames)
            
        # Convert to numpy array based on 16-bit PCM
        audio_data = np.frombuffer(raw_audio, dtype=np.int16)
        # Convert 16-bit to float32 and normalize
        audio_data = audio_data.astype(np.float32) / 32768.0
        # Ensure little-endian format as expected by the model
        audio_data = audio_data.astype('<f4')

        # Generate segments
        segments = inferencer.generate_all_segments(
            audio_data=audio_data,
            task=Speech2TextTask.TRANSCRIBE,
            language="en",
            timeout_ms=15000
        )

        if not segments:
            return ""

        output = ''.join([seg.text for seg in segments]).strip()

        # Clean up output (remove timestamps like [00:00:00.000 --> 00:00:02.000] or [BLANK_AUDIO])
        output = re.sub(r'\[.*?\]', '', output).strip()

        # Fix capitalization of BMO
        output = re.sub(r'\b[Bb]emo\b', 'BMO', output)
        output = re.sub(r'\b[Bb]eemo\b', 'BMO', output)

        return output

    except Exception as e:
        logger.error(f"Hailo Transcription Error: {e}")
        return ""
    finally:
        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except Exception:
                pass
