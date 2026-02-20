from . import config
import logging
import subprocess
import os

class Voice:
    def __init__(self, ui_controller):
        self.ui = ui_controller

    def speak(self, text):
        """
        Text-to-Speech using Piper and ALSA
        """
        if not text: return
        self.ui.set_state("speaking", text[:20] + "...")
        logging.info(f"Speaking: {text}")
        
        # Piper (Local) -> ALSA
        # Ensure we pipe to aplay for compatibility with Pi audio
        
        piper_cmd = f"echo '{text}' | {config.PIPER_CMD} --model {config.PIPER_MODEL} --output_raw | aplay -r 22050 -f S16_LE -t raw"
        try:
            subprocess.run(piper_cmd, shell=True, check=True)
        except Exception as e:
            logging.error(f"TTS Error: {e}")
            
        self.ui.set_state("idle", "Ready")
