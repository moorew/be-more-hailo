import logging
import sys
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

from core.stt import transcribe_audio, get_inferencer

print("Testing Whisper STT...")
inf = get_inferencer()
if inf is None:
    print("Inferencer failed to load!")
else:
    print("Inferencer loaded successfully.")
