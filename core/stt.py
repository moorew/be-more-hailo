import logging
import os
import re
import subprocess
import threading

import numpy as np
import soundfile as sf

from .config import WHISPER_CMD, WHISPER_HEF_PATH, WHISPER_MODEL, WHISPER_NPU_TIMEOUT_MS

logger = logging.getLogger(__name__)

# ─── NPU Speech2Text singleton ────────────────────────────────────────────────
# Lazy-initialised on first call so hailo-ollama (which loads the LLM HEF at
# startup) always gets the VDevice before we try to share it.  If the HEF is
# absent or init fails the CPU whisper.cpp path is used for every call.

_s2t_lock = threading.Lock()
_s2t = None           # Speech2Text instance once ready
_s2t_vdevice = None   # VDevice kept alive for the lifetime of _s2t
_s2t_tried = False    # True after the first init attempt (success or failure)


def _init_npu_stt():
    """Try to create the Hailo Speech2Text singleton.  Called once, under lock."""
    global _s2t, _s2t_vdevice, _s2t_tried
    _s2t_tried = True
    hef = WHISPER_HEF_PATH
    if not os.path.exists(hef):
        logger.info(f"Whisper HEF not found at {hef} — using CPU whisper.cpp")
        return
    try:
        from hailo_platform import VDevice
        from hailo_platform.genai import Speech2Text
        vdev = VDevice()
        try:
            instance = Speech2Text(vdev, hef)
        except Exception:
            try:
                vdev.release()
            except Exception:
                pass
            del vdev
            raise
        _s2t_vdevice = vdev
        _s2t = instance
        logger.info(f"NPU Speech2Text ready — {hef}")
    except Exception as exc:
        logger.warning(f"NPU Speech2Text init failed ({exc}) — falling back to CPU whisper.cpp")


def _get_s2t():
    """Return the Speech2Text singleton, initialising it on first call."""
    with _s2t_lock:
        if not _s2t_tried:
            _init_npu_stt()
        return _s2t


# ─── Shared output cleaning ───────────────────────────────────────────────────

def _clean_transcript(text: str) -> str:
    """Remove timestamps, fix BMO spelling, filter hallucinations."""
    text = re.sub(r'\[.*?\]', '', text).strip()
    text = re.sub(r'\b[Bb]emo\b', 'BMO', text)
    text = re.sub(r'\b[Bb]eemo\b', 'BMO', text)

    lowered = text.lower()
    hallucinations = [
        "[silence]", "(silence)", "you", "thanks for watching!",
        "[blank_audio]", "thank you.", "thank you", "thanks.",
    ]
    is_parenthetical = bool(re.match(r'^\s*[\(\[].*[\)\]]\s*$', text.strip()))
    if is_parenthetical or lowered in hallucinations or not re.search(r'[a-zA-Z0-9]', lowered):
        logger.info(f"Whisper hallucination filtered: {repr(text)}")
        return ""
    return text


# ─── NPU transcription ────────────────────────────────────────────────────────

def _transcribe_npu(audio_filepath: str) -> str | None:
    """Run Whisper-Small on the Hailo NPU.  Returns None on any error."""
    s2t = _get_s2t()
    if s2t is None:
        return None
    try:
        audio, sr = sf.read(audio_filepath, dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio[:, 0]  # keep mono
        if sr != 16000:
            # Resample to 16 kHz if the file was written at a different rate
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(16000, sr)
            audio = resample_poly(audio, 16000 // g, sr // g).astype(np.float32)

        from hailo_platform.genai import Speech2TextTask
        logger.info("Running NPU Speech2Text (Whisper-Small)...")
        with _s2t_lock:
            result = s2t.generate_all_text(
                audio_data=audio,
                task=Speech2TextTask.TRANSCRIBE,
                language="en",
                timeout_ms=WHISPER_NPU_TIMEOUT_MS,
            )
        return _clean_transcript(result or "")
    except Exception as exc:
        logger.warning(f"NPU Speech2Text inference failed ({exc}) — falling back to CPU")
        return None


# ─── CPU transcription ────────────────────────────────────────────────────────

def _transcribe_cpu(audio_filepath: str) -> str:
    """Run whisper.cpp on the CPU."""
    try:
        cmd = [WHISPER_CMD, "-m", WHISPER_MODEL, "-f", audio_filepath, "-nt", "-t", "3", "-l", "en"]
        logger.info(f"Running CPU whisper.cpp... CMD: {' '.join(cmd)}")
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        return _clean_transcript(output)
    except subprocess.CalledProcessError as exc:
        logger.error(f"Whisper CPU process failed (exit {exc.returncode})")
        return ""
    except Exception as exc:
        logger.error(f"Whisper CPU error: {exc}")
        return ""


# ─── Public entry point ───────────────────────────────────────────────────────

def transcribe_audio(audio_filepath: str) -> str:
    """
    Transcribe a 16 kHz mono WAV file.

    Tries Whisper-Small on the Hailo-10H NPU first; falls back to whisper.cpp
    on the CPU if the HEF is absent or inference fails.
    """
    if not os.path.exists(audio_filepath):
        logger.error(f"Audio file not found: {audio_filepath}")
        return ""

    result = _transcribe_npu(audio_filepath)
    if result is not None:
        return result
    return _transcribe_cpu(audio_filepath)
