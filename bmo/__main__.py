from . import ears, brain, voice, ui, transcribe, config
import tkinter as tk
import threading
import time
import logging
import queue
import os
import signal
import sys

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class BmoApp:
    def __init__(self, root):
        self.root = root
        self.gui = ui.BotGUI(root)
        self.ears = ears.Ears() # No callback yet, handled in loop
        self.brain = brain.Brain(self.gui)
        self.voice = voice.Voice(self.gui)
        
        self.running = True
        self.audio_queue = queue.Queue()
        
        # Start the listening thread
        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()
        
    def listen_loop(self):
        # Callback when wake word is heard
        def on_wake():
            if not self.running: return
            logging.info("Wake Word Detected!")
            
            # Update UI
            self.gui.set_state("listening", "Listening...")
            
            # Record Audio (Blocking)
            wav_file = self.ears.capture_audio()
            self.process_audio(wav_file)
            
        # Start listening
        self.ears.listen_loop(on_wake)

    def process_audio(self, filename):
        if not self.running: return
        
        # 1. Transcribe
        self.gui.set_state("thinking", "Hearing...")
        text = transcribe.transcribe_audio(filename)
        logging.info(f"Heard: {text}")
        
        if not text or len(text) < 2:
            self.gui.set_state("idle", "...")
            return

        # 2. Think
        self.gui.set_state("thinking", "Thinking...")
        response = self.brain.think(text)
        
        # 3. Speak
        self.voice.speak(response)
        
        # 4. Reset
        self.gui.set_state("idle", "Ready")

    def shutdown(self):
        self.running = False
        self.ears.stop()
        self.root.quit()

def main():
    root = tk.Tk()
    # Handle Ctrl+C
    def signal_handler(sig, frame):
        print('Exiting...')
        root.quit()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    
    app = BmoApp(root)
    root.protocol("WM_DELETE_WINDOW", app.shutdown)
    
    # Check dependencies
    if not os.path.exists(config.WAKE_WORD_MODEL):
        logging.error(f"Missing Wake Word: {config.WAKE_WORD_MODEL}")
    
    root.mainloop()

if __name__ == "__main__":
    main()
