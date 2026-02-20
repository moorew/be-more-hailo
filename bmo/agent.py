from . import ears, brain, voice, ui
import threading
import logging
import time

class Bmo:
    def __init__(self, master_ui):
        self.ui = ui.BotGUI(master_ui)
        self.ears = ears.Ears(callback=self.on_audio)
        self.brain = brain.Brain(self.ui)
        self.voice = voice.Voice(self.ui)
        self.stop_event = threading.Event()
        
    def start(self):
        self.ears_thread = threading.Thread(target=self.ears.listen_loop, args=(self.on_wake,), daemon=True)
        self.ears_thread.start()
        
    def on_wake(self):
        self.ui.set_state("listening", "Listening...")
        self.brain.history.append({"role": "user", "content": "I heard you."}) # Optional

        # Record Audio
        filename = self.ears.capture_audio()
        
        # Transcribe
        self.ui.set_state("thinking", "Hearing...")
        from . import transcribe
        text = transcribe.transcribe_audio(filename)
        logging.info(f"User: {text}")
        
        if len(text) > 1:
            # Think
            self.ui.set_state("thinking", "Hmm...")
            reply = self.brain.think(text)
            
            # Speak
            self.voice.speak(reply)
            
        else:
            self.ui.set_state("idle", "Ignore")

    def stop(self):
        self.stop_event.set()
        self.ears.stop()
