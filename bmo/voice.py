import logging
from core.tts import play_audio_on_hardware

class Voice:
    def __init__(self, ui_controller):
        self.ui = ui_controller

    def speak(self, text):
        """
        Text-to-Speech using Piper and ALSA
        """
        if not text: return
        self.ui.set_state("speaking", text[:20] + "...")
        
        # Use unified TTS core
        play_audio_on_hardware(text)
            
        self.ui.set_state("idle", "Ready")
