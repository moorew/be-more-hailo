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

# =========================================================================
# 1. HARDWARE CONFIGURATION
# =========================================================================

# AUDIO SETTINGS (Locked to your USB Mic)
MIC_DEVICE_INDEX = 1      # Your USB Mic Index (Detected on Pi as Device 1)
MIC_SAMPLE_RATE = 48000   # Standard USB Audio Rate
WAKE_WORD_MODEL = "./wakeword.onnx"
WAKE_WORD_THRESHOLD = 0.5

# HAILO SERVER SETTINGS
LLM_HOST = "http://127.0.0.1:8000"
LLM_MODEL = "llama3.2:3b"

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
        self.history = [{"role": "system", "content": "You are a helpful robot assistant. Keep answers short and fun."}]

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
        
        speed = 50 if self.current_state == BotStates.SPEAKING else 500
        self.master.after(speed, self.update_animation)

    # --- LLM CLIENT (CUSTOM FOR HAILO) ---
    def chat_with_llm(self, user_text):
        url = f"{LLM_HOST}/api/chat"
        self.history.append({"role": "user", "content": user_text})
        
        # Prepare JSON payload
        data = {
            "model": LLM_MODEL,
            "messages": self.history,
            "stream": False # Disable streaming to prevent crashes for now
        }
        
        try:
            req = urllib.request.Request(url, json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                # Handle Hailo/Ollama response structure
                content = result.get("message", {}).get("content", "")
                
                self.history.append({"role": "assistant", "content": content})
                return content
        except Exception as e:
            print(f"LLM Error: {e}")
            return f"Error: {e}"

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
        
        with sd.InputStream(samplerate=capture_rate, device=MIC_DEVICE_INDEX, channels=1, dtype='int16') as stream:
            while not self.stop_event.is_set():
                data, _ = stream.read(CHUNK * downsample_factor)
                # Simple integer decimation for 48k -> 16k
                audio_16k = data[::downsample_factor].flatten() 
                
                oww.predict(audio_16k)
                if oww.prediction_buffer["wakeword"][-1] > WAKE_WORD_THRESHOLD:
                    oww.reset()
                    return True
        return False

    def record_audio(self):
        """Record until silence"""
        print("Recording...")
        filename = "input.wav"
        sr = MIC_SAMPLE_RATE # 48000
        buffer = []
        silent_chunks = 0
        MAX_SILENCE = 30 # chunks (~1.5s)
        
        def callback(indata, frames, time, status):
            nonlocal silent_chunks
            vol = np.linalg.norm(indata) / np.sqrt(len(indata))
            buffer.append(indata.copy())
            if vol < 0.01: # Silence threshold
                silent_chunks += 1
            else:
                silent_chunks = 0

        with sd.InputStream(samplerate=sr, device=MIC_DEVICE_INDEX, channels=1, dtype='int16', callback=callback):
            while silent_chunks < MAX_SILENCE and not self.stop_event.is_set():
                sd.sleep(50)
                if len(buffer) > 200: break # Max length safety (10s)
        
        # Save file
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
        # Convert to 16k
        subprocess.run(f"ffmpeg -y -i {filename} -ar 16000 -ac 1 input_16k.wav", shell=True, stderr=subprocess.DEVNULL)
        
        # Using existing whisper.cpp setup
        cmd = ["./whisper.cpp/build/bin/whisper-cli", "-m", "./whisper.cpp/models/ggml-base.en.bin", "-f", "input_16k.wav", "-nt"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            # Rough parsing of whisper output
            text = res.stdout.strip()
            # Clean up [timestamps] if present
            text = re.sub(r'\[.*?\]', '', text).strip()
            return text
        except Exception as e:
            print(f"Whisper Error: {e}")
            return ""

    def speak(self, text):
        clean = re.sub(r"[^\w\s,.!?:-]", "", text)
        print(f"Speaking: {clean}")
        
        voice_path = "piper/en_GB-semaine-medium.onnx"
        
        # Run Piper -> Output directly to aplay (ALSA player) to avoid sounddevice output issues
        # Since input is Card 2, Output is likely Card 0 (Jack/HDMI) which is the default for aplay.
        
        piper_cmd = f"./piper/piper --model {voice_path} --output-raw | aplay -r 22050 -f S16_LE -t raw"
        subprocess.run(piper_cmd, input=clean.encode(), shell=True)

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
