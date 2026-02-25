# AUDIO CAPTURE & WAKE WORD
import sounddevice as sd
import numpy as np
import threading
from openwakeword.model import Model
from . import config

class Ears:
    def __init__(self, callback=None):
        self.stop_event = threading.Event()
        self.model = None # Lazy load
        self.wakeword_active = False
        
    def load_model(self):
        try:
            # Fix for openwakeword v0.5+ vs v0.4
            try:
                self.model = Model(wakeword_model_paths=[config.WAKE_WORD_MODEL])
            except TypeError:
                self.model = Model(wakeword_models=[config.WAKE_WORD_MODEL])
        except Exception as e:
            print(f"[EARS] Failed to load OpenWakeWord: {e}")
            
    def listen_loop(self, on_wake, on_audio_chunk):
        """
        Main audio loop capturing 48kHz, downsampling to 16kHz for WakeWord,
        passing raw audio chunks for processing.
        """
        if not self.model: self.load_model()
        
        CHUNK = 1280 # ~80ms at 16k
        capture_rate = config.MIC_RATE
        target_rate = 16000
        ds_factor = capture_rate // target_rate
        
        def audio_callback(indata, frames, time, status):
            if status: print(status)
            # 1. Check Wake Word 
            # Downsample: simple slice [::3] for 48->16k
            audio_16k = indata[::ds_factor, 0].flatten() # take channel 0
            
            if self.model:
                self.model.predict(audio_16k)
                if self.model.prediction_buffer[list(self.model.prediction_buffer.keys())[0]][-1] > config.WAKE_THRESHOLD:
                    self.model.reset()
                    on_wake()

            # 2. Pass data (for recording if needed)
            if on_audio_chunk:
                on_audio_chunk(indata.copy())

        with sd.InputStream(samplerate=capture_rate, device=config.MIC_INDEX, 
                            channels=1, dtype='int16', callback=audio_callback, blocksize=CHUNK*ds_factor):
            self.stop_event.wait()

    def stop(self):
        self.stop_event.set()
