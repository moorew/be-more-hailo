# =========================================================================
#  Be More Agent (Hailo Optimized) 🤖
#  Simplified for Pi 5 + Hailo-10H + USB Mic
# =========================================================================

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import threading
import time
import json
import os
import subprocess
import random
import re
import sys
import select
import traceback
import atexit
import datetime
import warnings
import wave
import struct 
import urllib.request
import urllib.error

# Core audio dependencies
import sounddevice as sd
import numpy as np
import scipy.signal 

# AI Engines
from openwakeword.model import Model
from duckduckgo_search import DDGS 

# Import unified core modules
from core.llm import Brain
from core.tts import play_audio_on_hardware
from core.stt import transcribe_audio
from core.config import MIC_DEVICE_INDEX, MIC_SAMPLE_RATE, WAKE_WORD_MODEL, WAKE_WORD_THRESHOLD

# =========================================================================
# 1. HARDWARE CONFIGURATION
# =========================================================================

# VISION SETTINGS
# Set to True only if you have the rpicam-detect setup
VISION_ENABLED = False 

# =========================================================================
# 2. GUI & STATE
# =========================================================================

class BotStates:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    CAPTURING = "capturing"
    WARMUP = "warmup"

class BotGUI:
    BG_WIDTH, BG_HEIGHT = 800, 480 
    OVERLAY_WIDTH, OVERLAY_HEIGHT = 400, 300 

    def __init__(self, master):
        self.master = master
        master.title("Pi Assistant")
        master.attributes('-fullscreen', True) 
        master.bind('<Escape>', self.exit_fullscreen)
        
        # Events
        self.stop_event = threading.Event()
        self.thinking_sound_active = threading.Event()
        self.tts_active = threading.Event()
        self.current_state = BotStates.WARMUP
        
        # Audio State
        self.current_audio_process = None
        self.tts_queue = []
        
        # Memory
        self.brain = Brain()

        # Init UI
        self.background_label = tk.Label(master, bg='black')
        self.background_label.place(x=0, y=0, width=self.BG_WIDTH, height=self.BG_HEIGHT)
        
        self.status_label = tk.Label(master, text="Initializing...", font=('Arial', 16), fg='white', bg='black')
        self.status_label.place(relx=0.5, rely=0.9, anchor=tk.S)

        self.animations = {}
        self.current_frame = 0
        self.load_animations()
        self.update_animation()

        # Start Main Thread
        threading.Thread(target=self.main_loop, daemon=True).start()

    def exit_fullscreen(self, event=None):
        self.stop_event.set()
        self.master.quit()

    def set_state(self, state, msg=""):
        if state != self.current_state:
            self.current_state = state
            self.current_frame = 0
            print(f"[STATE] {state.upper()}: {msg}")
        if msg:
            self.status_label.config(text=msg)

    # --- ANIMATION ENGINE ---
    def load_animations(self):
        base = "faces"
        for state in [BotStates.IDLE, BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING, BotStates.ERROR]:
            path = os.path.join(base, state)
            self.animations[state] = []
            if os.path.exists(path):
                files = sorted([f for f in os.listdir(path) if f.lower().endswith('.png')])
                for f in files:
                    img = Image.open(os.path.join(path, f)).resize((self.BG_WIDTH, self.BG_HEIGHT))
                    self.animations[state].append(ImageTk.PhotoImage(img))
    
    def update_animation(self):
        frames = self.animations.get(self.current_state, []) or self.animations.get(BotStates.IDLE, [])
        if frames:
            self.current_frame = (self.current_frame + 1) % len(frames)
            self.background_label.config(image=frames[self.current_frame])
        
        # Match web UI animation speeds
        speed = 500
        if self.current_state == BotStates.SPEAKING:
            speed = 150
        elif self.current_state == BotStates.THINKING:
            speed = 300
            
        self.master.after(speed, self.update_animation)

    # --- LLM CLIENT (CUSTOM FOR HAILO) ---
    def chat_with_llm(self, user_text):
        return self.brain.think(user_text)

    # --- AUDIO INPUT ---
    def wait_for_wakeword(self, oww):
        """Bloch until wake word is heard"""
        CHUNK = 1280
        # If openwakeword expects 16k, we must capture higher and downsample if needed
        # But let's try capturing at 16k directly first if the HW supports it, 
        # otherwise capture 48k and decimate.
        
        capture_rate = MIC_SAMPLE_RATE # 48000
        target_rate = 16000
        downsample_factor = capture_rate // target_rate
        
        try:
            with sd.InputStream(samplerate=capture_rate, device=MIC_DEVICE_INDEX, channels=1, dtype='int16') as stream:
                while not self.stop_event.is_set():
                    data, _ = stream.read(CHUNK * downsample_factor)
                    # Simple integer decimation for 48k -> 16k
                    audio_16k = data[::downsample_factor].flatten() 
                    
                    # Feed to model. 
                    # Assuming model name is 'wakeword' if you only loaded that one onnx file
                    # but openwakeword usually keys predictions by model name.
                    oww.predict(audio_16k)
                    
                    # Dynamically find the score so we don't crash on key error
                    for key in oww.prediction_buffer.keys():
                        if oww.prediction_buffer[key][-1] > WAKE_WORD_THRESHOLD:
                            print(f"Wake Word Detected: {key}")
                            oww.reset()
                            return True
        except Exception as e:
            print(f"Audio Input Error: {e}")
            self.set_state(BotStates.ERROR)
            time.sleep(2) # Prevent rapid looping on error
            return False
            
        return False

    def record_audio(self):
        """Record until silence"""
        print("Recording...")
        filename = "input.wav"
        frames = []
        silent_chunks = 0
        MAX_SILENCE_CHUNKS = 40 # approx 2 seconds of silence

        def callback(indata, frames_count, time, status):
            nonlocal silent_chunks
            vol = np.linalg.norm(indata) * 10 
            frames.append(indata.copy())
            if vol < 50: # Silence threshold
                silent_chunks += 1
            else:
                silent_chunks = 0
            
        try:
            with sd.InputStream(samplerate=MIC_SAMPLE_RATE, device=MIC_DEVICE_INDEX, channels=1, dtype='int16', callback=callback):
                while silent_chunks < MAX_SILENCE_CHUNKS and not self.stop_event.is_set():
                    sd.sleep(50)
                    if len(frames) > (MIC_SAMPLE_RATE * 10 / 512): # Max 10 seconds approx
                        break 
        except Exception as e:
            print(f"Recording Error: {e}")
            return None
        
        # Save file
        if not frames:
            return None

        data = np.concatenate(frames, axis=0)
        import scipy.io.wavfile
        scipy.io.wavfile.write(filename, MIC_SAMPLE_RATE, data)
        return filename
        audio_data = np.concatenate(buffer, axis=0)
        with wave.open(filename, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio_data.tobytes())
            
        return filename

    # --- STT & TTS ---
    def transcribe(self, filename):
        print("Transcribing...")
        return transcribe_audio(filename)

    def speak(self, text):
        print(f"Speaking: {text}")
        play_audio_on_hardware(text)

    # --- MAIN LOOP ---
    def main_loop(self):
        time.sleep(1) # Let UI settle
        
        # Load Wake Word
        self.set_state(BotStates.WARMUP, "Loading Ear...")
        try:
            oww = Model(wakeword_model_paths=[WAKE_WORD_MODEL])
        except:
            print("Failed to load wakeword model!")
            self.set_state(BotStates.ERROR, "Wake Word Error")
            return

        self.set_state(BotStates.IDLE, "Waiting...")
        
        while not self.stop_event.is_set():
            # 1. Wait for Wake Word
            if self.wait_for_wakeword(oww):
                # 2. Record
                self.set_state(BotStates.LISTENING, "Listening...")
                wav_file = self.record_audio()
                
                # 3. Transcribe
                self.set_state(BotStates.THINKING, "Transcribing...")
                user_text = self.transcribe(wav_file)
                print(f"User Transcribed: {user_text}")
                
                if len(user_text) < 2:
                    self.set_state(BotStates.IDLE, "Unknown Input")
                    continue

                # 4. LLM
                self.set_state(BotStates.THINKING, "Thinking...")
                response = self.chat_with_llm(user_text)
                
                # 5. Speak
                self.set_state(BotStates.SPEAKING, response[:20] + "...")
                self.speak(response)
                
                self.set_state(BotStates.IDLE, "Ready")

if __name__ == "__main__":
    root = tk.Tk()
    app = BotGUI(root)
    root.mainloop()
