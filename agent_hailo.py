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

# Import unified core modules
from core.llm import Brain
from core.tts import play_audio_on_hardware
from core.stt import transcribe_audio
from core.config import MIC_DEVICE_INDEX, MIC_SAMPLE_RATE, WAKE_WORD_MODEL, WAKE_WORD_THRESHOLD, ALSA_DEVICE

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
    DISPLAY_IMAGE = "display_image"
    SCREENSAVER = "screensaver"
    # New Expressions
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    SLEEPY = "sleepy"
    DIZZY = "dizzy"
    CHEEKY = "cheeky"
    HEART = "heart"
    STARRY_EYED = "starry_eyed"
    CONFUSED = "confused"
    SHHH = "shhh"
    JAMMING = "jamming"
    FOOTBALL = "football"
    DETECTIVE = "detective"
    SIR_MANO = "sir_mano"
    LOW_BATTERY = "low_battery"
    BEE = "bee"

class BotGUI:

    BG_WIDTH, BG_HEIGHT = 800, 480 
    OVERLAY_WIDTH, OVERLAY_HEIGHT = 400, 300 

    def __init__(self, master):
        self.master = master
        master.title("Pi Assistant")
        master.attributes('-fullscreen', True) 
        master.configure(cursor='none') # Hide cursor for kiosk display
        master.bind('<Escape>', self.exit_fullscreen)
        master.bind('<Button-1>', self.mute_bmo)
        
        # Events
        self.stop_event = threading.Event()
        self.thinking_sound_active = threading.Event()
        self.tts_active = threading.Event()
        self.current_state = BotStates.WARMUP
        self.last_state_change = time.time()
        
        # Audio State
        self.current_audio_process = None
        self.tts_queue = []
        
        # Memory
        self.brain = Brain()

        # Init UI
        self.background_label = tk.Label(master, bg='black')
        self.background_label.place(x=0, y=0, width=self.BG_WIDTH, height=self.BG_HEIGHT)
        
        # BMO-themed captions: dark green text on translucent lime-green background
        self.status_label = tk.Label(
            master,
            text="Initializing...",
            font=('Courier New', 14, 'bold'),
            fg='#1a5c2a',       # Dark forest green text
            bg='#bdffcb',       # BMO's signature green
            padx=12, pady=4,
            relief='flat',
            highlightthickness=0
        )
        self.status_label.place(relx=0.5, rely=0.92, anchor=tk.S)

        self.is_muted = False
        self.mute_label = tk.Label(
            master,
            text="🔇 Muted",
            font=('Courier New', 16, 'bold'),
            fg='#f44336',
            bg='#bdffcb',       # BMO's signature green
            padx=10, pady=5,
            relief='flat',
            highlightthickness=0
        )

        self.animations = {}
        self.current_frame = 0
        self.load_animations()
        self.load_sounds()
        self.update_animation()

        # Start Main Thread
        threading.Thread(target=self.main_loop, daemon=True).start()
        
        # Start Screensaver Audio Thread
        self.last_screensaver_audio_time = time.time()
        threading.Thread(target=self.screensaver_audio_loop, daemon=True).start()

    def exit_fullscreen(self, event=None):
        self.stop_event.set()
        self.master.quit()

    def set_state(self, state, msg=""):
        if state != self.current_state:
            self.current_state = state
            self.current_frame = 0
            self.last_state_change = time.time()
            print(f"[STATE] {state.upper()}: {msg}")
        if msg:
            self.status_label.config(text=msg)

    def mute_bmo(self, event=None):
        """Toggle audio mute and sets the whimsical 'shhh' face."""
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.mute_label.place(relx=0.95, rely=0.05, anchor=tk.NE)
            try:
                # Kill any hardware audio playing via aplay immediately
                subprocess.run(["killall", "-9", "aplay"], capture_output=True)
                print("[MUTE] Killed aplay process.")
            except Exception as e:
                print(f"[MUTE] Error stopping aplay: {e}")
                
            old_state = self.current_state
            self.set_state(BotStates.SHHH, "Muted")
            
            # Stop background thinking audio loops too if they're active
            if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                try:
                    self.thinking_audio_process.terminate()
                except Exception:
                    pass
                self.thinking_audio_process = None

            # After 3 seconds, resume natural state
            def revert_state():
                if self.current_state == BotStates.SHHH:
                    self.set_state(old_state if old_state != BotStates.SHHH else BotStates.IDLE, "Muted")
            self.master.after(3000, revert_state)
        else:
            self.mute_label.place_forget()
            self.set_state(BotStates.HAPPY, "Unmuted!")
            def revert_state():
                if self.current_state == BotStates.HAPPY:
                    self.set_state(BotStates.IDLE, "Ready...")
            self.master.after(2000, revert_state)

    # --- ANIMATION & SOUND ENGINE ---
    def load_sounds(self):
        self.sounds = {
            "greeting_sounds": [],
            "ack_sounds": [],
            "thinking_sounds": [],
            "music": []
        }
        base = "sounds"
        for category in self.sounds.keys():
            path = os.path.join(base, category)
            if os.path.exists(path):
                self.sounds[category] = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith('.wav')]

    def play_sound(self, category):
        if self.is_muted:
            return None
        sounds = self.sounds.get(category, [])
        if not sounds:
            return None
        sound_file = random.choice(sounds)
        try:
            return subprocess.Popen(['aplay', '-D', ALSA_DEVICE, '-q', sound_file])
        except Exception as e:
            print(f"Error playing sound {sound_file}: {e}")
            return None

    def load_animations(self):
        base = "faces"
        all_face_paths = []
        for state in [BotStates.IDLE, BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING, BotStates.ERROR, BotStates.HAPPY, BotStates.SAD, BotStates.ANGRY, BotStates.SURPRISED, BotStates.SLEEPY, BotStates.DIZZY, BotStates.CHEEKY, BotStates.HEART, BotStates.STARRY_EYED, BotStates.CONFUSED, BotStates.SHHH, BotStates.JAMMING, BotStates.FOOTBALL, BotStates.DETECTIVE, BotStates.SIR_MANO, BotStates.LOW_BATTERY, BotStates.BEE]:
            path = os.path.join(base, state)
            self.animations[state] = []
            if os.path.exists(path):
                files = sorted([f for f in os.listdir(path) if f.lower().endswith('.png')])
                for f in files:
                    img_path = os.path.join(path, f)
                    img = Image.open(img_path).resize((self.BG_WIDTH, self.BG_HEIGHT))
                    self.animations[state].append(ImageTk.PhotoImage(img))
                    
        # Load screensaver as full animation sequences per expression
        # Only include expressions that make sense without audio context
        SCREENSAVER_STATES = [
            "idle", "happy", "sleepy", "heart", "starry_eyed",
            "cheeky", "dizzy", "confused",
            "daydream", "bored", "jamming", "curious",
            "football", "detective", "sir_mano", "low_battery", "bee"
        ]
        self.screensaver_sequences = []  # List of (state_name, [frames])
        for state_dir in SCREENSAVER_STATES:
            path = os.path.join(base, state_dir)
            if not os.path.isdir(path):
                continue
            files = sorted([f for f in os.listdir(path) if f.lower().endswith('.png')])
            if files:
                seq_frames = []
                for f in files:
                    try:
                        img = Image.open(os.path.join(path, f)).resize((self.BG_WIDTH, self.BG_HEIGHT))
                        seq_frames.append(ImageTk.PhotoImage(img))
                    except Exception as e:
                        print(f"Failed to load screensaver image {f}: {e}")
                if seq_frames:
                    self.screensaver_sequences.append((state_dir, seq_frames))
        
        # Build the screensaver animation: play each expression's full sequence
        random.shuffle(self.screensaver_sequences)
        self.animations[BotStates.SCREENSAVER] = []
        for name, seq in self.screensaver_sequences:
            # Play each expression's sequence 2x so you can see the animation
            self.animations[BotStates.SCREENSAVER].extend(seq * 2)
    
    def update_animation(self):
        if self.current_state == BotStates.DISPLAY_IMAGE:
            # Don't animate, just wait
            self.master.after(500, self.update_animation)
            return

        # Check for screensaver trigger
        if self.current_state == BotStates.IDLE and (time.time() - self.last_state_change) > 60:
            self.set_state(BotStates.SCREENSAVER, "Screensaver...")

        # If entering listening from screensaver, immediately break out
        if self.current_state == BotStates.LISTENING and self.current_frame > 0 and 'screensaver' in str(self.animations.get(self.current_state, [])):
            self.current_frame = 0 # reset cleanly

        # Hide text status label during screensaver
        if self.current_state == BotStates.SCREENSAVER:
            if self.status_label.winfo_ismapped():
                self.status_label.place_forget()
        else:
            if not self.status_label.winfo_ismapped():
                self.status_label.place(relx=0.5, rely=0.92, anchor=tk.S)

        frames = self.animations.get(self.current_state, []) or self.animations.get(BotStates.IDLE, [])
        if frames:
            self.current_frame = (self.current_frame + 1) % len(frames)
            
            # Re-shuffle screensaver sequences when loop completes
            if self.current_state == BotStates.SCREENSAVER and self.current_frame == 0:
                random.shuffle(self.screensaver_sequences)
                self.animations[BotStates.SCREENSAVER] = []
                for name, seq in self.screensaver_sequences:
                    self.animations[BotStates.SCREENSAVER].extend(seq * 2)
                
            self.background_label.config(image=frames[self.current_frame])
        
        # Match web UI animation speeds
        speed = 500
        if self.current_state == BotStates.SPEAKING:
            speed = 90   # Fix: 90ms for natural lip sync
        elif self.current_state == BotStates.THINKING:
            speed = 500
        elif self.current_state == BotStates.LISTENING:
            speed = 400
        elif self.current_state == BotStates.SCREENSAVER or self.current_state == BotStates.SHHH:
            speed = 400 # Smooth animation speed for sequences

        self.master.after(speed, self.update_animation)

    # --- AUDIO INPUT ---
    def wait_for_wakeword(self, oww):
        """Block until wake word is heard."""
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
        has_spoken = False

        def callback(indata, frames_count, time, status):
            nonlocal silent_chunks, has_spoken
            vol = np.linalg.norm(indata) * 10 
            frames.append(indata.copy())
            if vol < 50000: # Silence threshold
                silent_chunks += 1
            else:
                silent_chunks = 0
                has_spoken = True
            
        try:
            with sd.InputStream(samplerate=MIC_SAMPLE_RATE, device=MIC_DEVICE_INDEX, channels=1, dtype='int16', callback=callback):
                while not self.stop_event.is_set():
                    sd.sleep(50)
                    if not has_spoken and silent_chunks > 100:
                        break
                    if has_spoken and silent_chunks > 40:
                        break
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

    # --- TIMERS & REMINDERS ---
    def start_timer_thread(self, minutes, message):
        def timer_worker():
            print(f"[TIMER SET] for {minutes} minutes. Message: {message}")
            time.sleep(minutes * 60)
            print(f"[TIMER DONE] {message}")
            
            # Wait for BMO to finish speaking/listening to avoid ALSA conflicts
            while self.current_state in [BotStates.SPEAKING, BotStates.LISTENING]:
                time.sleep(1)
                
            # Interject the alarm
            old_state = self.current_state
            self.set_state(BotStates.HAPPY, "Reminder!")
            # Play an alert noise if we have one
            alert_proc = self.play_sound("ack_sounds")
            if alert_proc:
                alert_proc.wait()
                
            self.speak(message, msg="Reminder!")
            
            # Return BMO to whatever they were doing (e.g. IDLE or SCREENSAVER)
            time.sleep(1)
            if self.current_state == BotStates.IDLE:
                self.set_state(old_state if old_state != BotStates.HAPPY else BotStates.IDLE, "Ready")
                
        threading.Thread(target=timer_worker, daemon=True).start()

    # --- STT & TTS ---
    def transcribe(self, filename):
        print("Transcribing...")
        return transcribe_audio(filename)

    def speak(self, text, msg="Speaking..."):
        from core.tts import clean_text_for_speech
        from core.config import PIPER_CMD, PIPER_MODEL, ALSA_DEVICE
        
        clean_text = clean_text_for_speech(text)
        if not clean_text or not any(c.isalnum() for c in clean_text):
            return
            
        print(f"Speaking: {clean_text[:30]}...")
        try:
            safe_text = clean_text.replace("'", "'\\''")
            
            # 1. Synthesize audio first. (Runs silently, mouth stays idle/thinking)
            piper_cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_raw"
            res = subprocess.run(piper_cmd, shell=True, capture_output=True)
            if res.returncode != 0:
                print(f"Piper error: {res.stderr}")
                return
            
            # 2. Audio is ready! Set SPEAKING state so mouth starts moving.
            if msg is not None:
                self.set_state(BotStates.SPEAKING, msg)
            else:
                self.current_state = BotStates.SPEAKING
                self.current_frame = 0
                self.last_state_change = time.time()
            
            # 3. Play the generated audio bytes
            if not self.is_muted:
                aplay_cmd = ["aplay", "-D", ALSA_DEVICE, "-r", "22050", "-f", "S16_LE", "-t", "raw"]
                subprocess.run(aplay_cmd, input=res.stdout)
            else:
                # If muted, just hold the speaking pose for a moment to simulate talking
                time.sleep(1.5)
            
            # 4. Enforce an immediate IDLE state and a short visual breath pause
            # This ensures the mouth closes definitively before the next sentence chunk arrives,
            # unless a background thread (like play_music) has already hijacked the state to JAMMING
            if self.current_state == BotStates.SPEAKING:
                if msg is not None:
                    self.set_state(BotStates.IDLE, "Ready...")
                else:
                    self.current_state = BotStates.IDLE
                    self.current_frame = 0
                    self.last_state_change = time.time()
                time.sleep(0.3)
            
        except Exception as e:
            print(f"Hardware TTS Error: {e}")

    def record_followup(self, timeout_sec=8):
        """
        After BMO responds, listen briefly for a follow-up question.
        Returns audio filepath if speech was detected within timeout_sec, or None.

        Notes:
        - A 1-second ignore window at the start lets the echo of BMO's own voice
          die down before we start watching for human speech.
        - A hard cap (max_deadline) ensures we always exit even if the mic
          keeps picking up ambient noise and has_spoken stays True.
        """
        print("Listening for follow-up...")
        frames = []
        silent_chunks = 0
        has_spoken = False
        max_vol_seen = 0.0                        
        ignore_until = time.time() + 0.2          # ignore first 0.2s for ALSA buffer clear
        deadline = time.time() + timeout_sec       # give up if no speech by here
        max_deadline = time.time() + timeout_sec + 8  # hard cap regardless

        def callback(indata, frames_count, time_info, status):
            nonlocal silent_chunks, has_spoken, max_vol_seen
            if time.time() < ignore_until:
                return  # still in echo dead-zone — ignore all audio
            vol = np.linalg.norm(indata) * 10
            max_vol_seen = max(max_vol_seen, vol)
            
            frames.append(indata.copy())
            if vol < 50000:  # Matching main record_audio silence threshold
                silent_chunks += 1
            else:
                silent_chunks = 0
                has_spoken = True

        try:
            with sd.InputStream(samplerate=MIC_SAMPLE_RATE, device=MIC_DEVICE_INDEX,
                                channels=1, dtype='int16', callback=callback):
                while not self.stop_event.is_set():
                    sd.sleep(50)
                    now = time.time()
                    # Human speech detected and gone quiet — we have a follow-up
                    if has_spoken and silent_chunks > 40:
                        break
                    # No speech in the listen window — give up quietly
                    if now > deadline and not has_spoken:
                        print(f"Follow-up timeout. Max mic volume detected was: {max_vol_seen:.2f} (threshold is 50000)")
                        return None
                    # Hard cap — break out and attempt transcription rather than discarding!
                    if now > max_deadline:
                        print(f"Follow-up max deadline hit. Breaking to transcribe. Max volume: {max_vol_seen:.2f}")
                        break
        except Exception as e:
            print(f"Follow-up listen error: {e}")
            return None

        # Give ALSA/PortAudio time to fully close the stream context at OS level
        time.sleep(0.5)

        print(f"Speech finished! Max mic volume was: {max_vol_seen:.2f}")
        if not has_spoken or not frames:
            return None

        filename = "followup.wav"
        try:
            # Filter out any empty arrays from the callback race before concatenating
            valid_frames = [f for f in frames if f is not None and len(f) > 0]
            if not valid_frames:
                return None
            audio_data = np.concatenate(valid_frames)
        except Exception as e:
            print(f"Follow-up audio concat error: {e}")
            return None

        with wave.open(filename, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(MIC_SAMPLE_RATE)
            wf.writeframes(audio_data.tobytes())
        return filename



    # --- MAIN LOOP ---
    def main_loop(self):
        time.sleep(1) # Let UI settle
        
        # Load Wake Word
        self.set_state(BotStates.WARMUP, "Loading Ear...")
        try:
            oww = Model(wakeword_model_paths=[WAKE_WORD_MODEL])
        except Exception as e:
            print(f"Failed to load wakeword model: {e}")
            self.set_state(BotStates.ERROR, "Wake Word Error")
            return

        self.set_state(BotStates.SPEAKING, "Ready!")
        greeting_proc = self.play_sound("greeting_sounds")
        if greeting_proc:
            # Wait for greeting to finish before going idle
            threading.Thread(target=lambda: (greeting_proc.wait(), self.set_state(BotStates.IDLE, "Waiting...") if self.current_state == BotStates.SPEAKING else None), daemon=True).start()
        else:
            self.set_state(BotStates.IDLE, "Waiting...")

        while not self.stop_event.is_set():
            # 1. Wait for Wake Word
            if self.wait_for_wakeword(oww):
                # 2. Record
                self.set_state(BotStates.LISTENING, "Listening...")
                wav_file = self.record_audio()
                
                # 3. Transcribe
                self.set_state(BotStates.THINKING, "Transcribing...")
                
                def play_thinking_sequence():
                    ack_proc = self.play_sound("ack_sounds")
                    if ack_proc:
                        ack_proc.wait()
                    
                    while self.current_state == BotStates.THINKING:
                        self.thinking_audio_process = self.play_sound("thinking_sounds")
                        if self.thinking_audio_process:
                            self.thinking_audio_process.wait()
                        # Wait 8 seconds before playing again, but check state frequently
                        for _ in range(80):
                            if self.current_state != BotStates.THINKING:
                                break
                            time.sleep(0.1)
                
                threading.Thread(target=play_thinking_sequence, daemon=True).start()

                user_text = self.transcribe(wav_file)
                print(f"User Transcribed: {user_text}")
                
                if len(user_text) < 2:
                    self.set_state(BotStates.IDLE, "Ready")
                    if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                        try:
                            self.thinking_audio_process.terminate()
                        except Exception:
                            pass
                        self.thinking_audio_process = None
                    continue

                # 4. LLM
                self.set_state(BotStates.THINKING, "Thinking...")

                # Stop the thinking sound loop
                if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                    try:
                        self.thinking_audio_process.terminate()
                    except Exception:
                        pass
                    self.thinking_audio_process = None

                try:
                    full_response = ""
                    image_url = None
                    taking_photo = False
                    
                    for chunk in self.brain.stream_think(user_text):
                        if not chunk.strip():
                            continue
                            
                        full_response += chunk
                        
                        # Handle json actions
                        if '{"action": "take_photo"}' in chunk:
                            taking_photo = True
                            break
                            
                        json_match = re.search(r'\{.*?\}', chunk, re.DOTALL)
                        if json_match:
                            try:
                                action_data = json.loads(json_match.group(0))
                                if action_data.get("action") == "display_image" and action_data.get("image_url"):
                                    image_url = action_data.get("image_url")
                                    chunk = chunk.replace(json_match.group(0), '').strip()
                                elif action_data.get("action") == "set_expression" and action_data.get("value"):
                                    expr = action_data.get("value").lower()
                                    if expr in [BotStates.HAPPY, BotStates.SAD, BotStates.ANGRY, BotStates.SURPRISED, BotStates.SLEEPY, BotStates.DIZZY, BotStates.CHEEKY, BotStates.HEART, BotStates.STARRY_EYED, BotStates.CONFUSED]:
                                        self.set_state(expr, f"Feeling {expr}...")
                                        # Let it show the expression for ~3 seconds, then we will revert back
                                        # (it will revert to SPEAKING when the next chunk comes in, or IDLE at the end)
                                    chunk = chunk.replace(json_match.group(0), '').strip()
                                elif action_data.get("action") == "set_timer" and action_data.get("minutes") is not None:
                                    mins = float(action_data.get("minutes"))
                                    msg = action_data.get("message", "Timer is up!")
                                    self.start_timer_thread(mins, msg)
                                    chunk = chunk.replace(json_match.group(0), '').strip()
                                elif action_data.get("action") == "play_music":
                                    # Spawns a background thread to play music and animate
                                    def music_worker():
                                        # Wait for current speaking to finish
                                        while self.current_state in [BotStates.SPEAKING, BotStates.THINKING]:
                                            time.sleep(0.5)
                                        
                                        music_proc = self.play_sound("music")
                                        if music_proc:
                                            old_state = self.current_state
                                            self.set_state(BotStates.JAMMING, "Jamming!")
                                            music_proc.wait()
                                            time.sleep(1) # Extra buffer
                                            if self.current_state == BotStates.JAMMING:
                                                self.set_state(old_state if old_state != BotStates.JAMMING else BotStates.IDLE, "Ready")
                                    
                                    threading.Thread(target=music_worker, daemon=True).start()
                                    chunk = chunk.replace(json_match.group(0), '').strip()
                            except Exception as e:
                                print(f"JSON Parse Error: {e}")
                                
                        if chunk.strip():
                            self.speak(chunk)

                    if taking_photo:
                        self.set_state(BotStates.CAPTURING, "Taking Photo...")
                        try:
                            # Try libcamera-still (older) or rpicam-still (newer Pi OS)
                            cam_cmd = None
                            for candidate in ['libcamera-still', 'rpicam-still']:
                                r = subprocess.run(['which', candidate], capture_output=True)
                                if r.returncode == 0:
                                    cam_cmd = candidate
                                    break
                            if cam_cmd is None:
                                raise FileNotFoundError("No camera command found (libcamera-still / rpicam-still)")
                            subprocess.run([cam_cmd, '-o', 'temp.jpg', '--width', '640', '--height', '480', '--nopreview', '-t', '1000'], check=True)
                            import base64
                            with open('temp.jpg', 'rb') as img_file:
                                b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                            self.set_state(BotStates.THINKING, "Analyzing...")
                            threading.Thread(target=play_thinking_sequence, daemon=True).start()
                            response = self.brain.analyze_image(b64_string, user_text)
                            if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                                try:
                                    self.thinking_audio_process.terminate()
                                except Exception:
                                    pass
                                self.thinking_audio_process = None
                            self.speak(response)
                        except FileNotFoundError as e:
                            print(f"Camera Error: {e}")
                            self.speak("Hmm, BMO doesn't seem to have a camera connected right now. I can't take a photo!")

                        except Exception as e:
                            print(f"Camera Error: {e}")
                            self.speak("I tried to take a photo, but my camera isn't working.")
                    
                    # 5. Display Image (if any)
                    if image_url:
                        self.set_state(BotStates.DISPLAY_IMAGE, "Showing Image...")
                        try:
                            # Migrate old pollinations URL if the LLM emitted the old format
                            image_url = image_url.replace("image.pollinations.ai/prompt/", "gen.pollinations.ai/image/")
                            print(f"[IMAGE] Downloading: {image_url}")
                            req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=15) as u:
                                raw_data = u.read()
                            print(f"[IMAGE] Downloaded: {len(raw_data)} bytes")
                            from io import BytesIO
                            from PIL import ImageOps, ImageDraw
                            
                            def apply_bmo_border(pil_img):
                                # Resize and crop image to fit inside the inner LCD screen
                                lcd_w, lcd_h = self.BG_WIDTH - 60, self.BG_HEIGHT - 60
                                # Cover/resize logic
                                img_ratio = pil_img.width / pil_img.height
                                target_ratio = lcd_w / lcd_h
                                if img_ratio > target_ratio:
                                    # Image is wider, scale to height and crop width
                                    new_h = lcd_h
                                    new_w = int(new_h * img_ratio)
                                else:
                                    # Image is taller, scale to width and crop height
                                    new_w = lcd_w
                                    new_h = int(new_w / img_ratio)
                                
                                pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                                # Crop center
                                left = (new_w - lcd_w) / 2
                                top = (new_h - lcd_h) / 2
                                right = (new_w + lcd_w) / 2
                                bottom = (new_h + lcd_h) / 2
                                pil_img = pil_img.crop((left, top, right, bottom))
                                
                                # Add inner thick dark LCD bezel
                                pil_img = ImageOps.expand(pil_img, border=10, fill="#1c201a")
                                # Add BMO Teal outer casing
                                pil_img = ImageOps.expand(pil_img, border=20, fill="#38b5a0")
                                return pil_img

                            img = Image.open(BytesIO(raw_data))
                            img = apply_bmo_border(img)
                            
                            # Schedule Tkinter update on main thread for thread safety
                            def show_image(pil_img=img):
                                try:
                                    self.current_display_image = ImageTk.PhotoImage(pil_img)
                                    self.background_label.config(image=self.current_display_image)
                                    print("[IMAGE] Displayed on screen")
                                except Exception as e:
                                    print(f"[IMAGE] Tkinter display error: {e}")
                            
                            self.master.after(0, show_image)
                        except Exception as e:
                            print(f"[IMAGE] Download/Display Error: {e}")

                except Exception as e:
                    print(f"ERROR in LLM/TTS pipeline: {e}")
                    traceback.print_exc()

                self.set_state(BotStates.IDLE, "Ready")

                # Conversation follow-up: let user reply repeatedly as long as they respond within 8 seconds
                while True:
                    self.set_state(BotStates.LISTENING, "Still listening...")
                    followup_wav = self.record_followup(timeout_sec=8)
                    
                    if not followup_wav:
                        # User didn't reply within 8 seconds, end conversation thread
                        self.set_state(BotStates.IDLE, "Waiting...")
                        break
                        
                    self.set_state(BotStates.THINKING, "Transcribing...")
                    threading.Thread(target=play_thinking_sequence, daemon=True).start()
                    user_text = self.transcribe(followup_wav)
                    print(f"Follow-up Transcribed: {user_text}")
                    
                    if len(user_text) < 2:
                        # Mic picked up noise, but no actual speech. End conversation.
                        if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                            try:
                                self.thinking_audio_process.terminate()
                            except Exception:
                                pass
                            self.thinking_audio_process = None
                        self.set_state(BotStates.IDLE, "Waiting...")
                        break

                    self.set_state(BotStates.THINKING, "Thinking...")
                    if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                        try:
                            self.thinking_audio_process.terminate()
                        except Exception:
                            pass
                        self.thinking_audio_process = None
                        
                    try:
                        for chunk in self.brain.stream_think(user_text):
                            if chunk.strip():
                                self.speak(chunk)
                    except Exception as e:
                        print(f"Follow-up LLM error: {e}")
                        
                    self.set_state(BotStates.IDLE, "Ready")
                    # Loop back around and listen again!
                    
                # Guarantee a 1 second cool-down before we loop all the way back up
                # and call wait_for_wakeword(). This ensures ALSA capture locks are fully
                # released by the kernel, preventing PaErrorCode -9999 crashes.
                time.sleep(1.0)

    def screensaver_audio_loop(self):
        import datetime
        import requests as http_requests
        from core.search import search_web
        from core.config import LLM_URL, FAST_LLM_MODEL
        
        # Topics BMO might wonder about — used as web search seeds
        search_topics = [
            "interesting fun fact of the day",
            "inspirational quote of the day",
            "weather forecast today in Brantford, Ontario",
            "this day in history",
            "cool science discovery this week",
            "funny animal fact",
            "motivational thought for the day",
            "random wholesome internet story",
            "video game history fact",
            "weird food fact",
            "riddle of the day",
            "Adventure Time lore or trivia",
            "today's astronomy picture",
            "best joke of the day",
        ]
        
        # Fallback phrases if search/LLM fails
        fallback_phrases = [
            "I wonder what Finn and Jake are doing right now.",
            "Does anyone want to play a video game? No? ...Okay.",
            "La la la la la... BMO is the best!",
            "Sometimes BMO just likes to hum a little tune.",
            "Football... is a tough little guy.",
        ]
        
        def is_llm_reachable():
            """Quick health check — ping the Ollama base URL before making a full LLM call."""
            try:
                base_url = LLM_URL.replace("/api/chat", "")
                r = http_requests.get(base_url, timeout=5)
                return r.status_code == 200
            except Exception:
                return False
        
        def generate_thought(search_result):
            """Generate a BMO musing using a direct (non-streaming) LLM call.
            Returns the thought string, or None on failure."""
            thought_prompt = (
                "You are BMO, a cute little robot. You just learned something interesting from the real world. "
                "Based on the info below, share what you found OUT LOUD. "
                "RULES:\n"
                "1. You MUST include the SPECIFIC name, title, number, date, or fact. NEVER be vague.\n"
                "2. Talk for 2-3 sentences. First sentence states the specific thing. Second adds your charming opinion.\n"
                "3. Do NOT ask questions to the user.\n\n"
                "EXAMPLES of GOOD vs BAD:\n"
                "BAD: 'I just read about an amazing book!' (too vague, no title)\n"
                "GOOD: 'BMO just learned about a book called The Hitchhiker's Guide to the Galaxy! It says the answer to everything is 42. BMO wonders what the question is...'\n\n"
                "BAD: 'I found a cool fact about space!' (too vague, no detail)\n"
                "GOOD: 'Did you know that Jupiter's Great Red Spot is a storm bigger than Earth? It has been spinning for over 350 years! BMO thinks that is one grumpy planet.'\n\n"
                "BAD: 'There is a funny joke I heard!' (no punchline)\n"
                "GOOD: 'Why did the scarecrow win an award? Because he was outstanding in his field! Hehe, BMO loves that one.'\n\n"
                "If the topic is highly visual (like a nebula, space photo, or cute animal), generate an image using this "
                "EXACT JSON format anywhere in your response: "
                '{"action": "display_image", "image_url": "https://gen.pollinations.ai/image/URL_ENCODED_SUBJECT"}. '
                "Do NOT use JSON unless you are creating an image.\n\n"
                f"Info: {search_result[:1200]}"
            )
            payload = {
                "model": FAST_LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "You are BMO, a cute little robot who muses to yourself. Always mention specific names, titles, numbers, and facts."},
                    {"role": "user", "content": thought_prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.8,
                    "num_predict": 300,
                }
            }
            try:
                resp = http_requests.post(LLM_URL, json=payload, timeout=60)
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "").strip()
                    # Filter out error-like responses the model might echo
                    if content and "connect" not in content.lower() and "error" not in content.lower():
                        return content
                else:
                    print(f"[SCREENSAVER] LLM returned status {resp.status_code}")
            except http_requests.exceptions.RequestException as e:
                print(f"[SCREENSAVER] LLM request failed: {e}")
            return None
        
        while not self.stop_event.is_set():
            time.sleep(30) # Check every 30 seconds
            if self.current_state != BotStates.SCREENSAVER:
                continue
                
            now = datetime.datetime.now()
            hour = now.hour
            
            # Quiet Hours: 10 PM to 8 AM
            if hour >= 22 or hour < 8:
                continue
            
            # Skip if user was recently interacting
            if time.time() - self.last_state_change < 60:
                continue
                
            # Random visual-only boredom animations (~10% chance every 30s)
            if random.random() < 0.10:
                expr = random.choice([BotStates.HEART, BotStates.SLEEPY, BotStates.STARRY_EYED, BotStates.DIZZY])
                self.set_state(expr, "Zzz..." if expr == BotStates.SLEEPY else "...")
                # Hold the expression for 4 seconds, then revert to Screensaver
                def revert():
                    if self.current_state == expr:
                        self.set_state(BotStates.SCREENSAVER, "Screensaver...")
                self.master.after(4000, revert)
                
            # Random Persona Gags (~5% chance every 30s)
            elif random.random() < 0.05:
                persona = random.choice([BotStates.FOOTBALL, BotStates.DETECTIVE, BotStates.SIR_MANO, BotStates.LOW_BATTERY, BotStates.BEE])
                self.set_state(persona, "...")
                
                # Play the matching sound effect
                sound_file = os.path.join("sounds", "personas", f"{persona}.wav")
                if not self.is_muted and os.path.exists(sound_file):
                    try:
                        subprocess.Popen(['aplay', '-D', ALSA_DEVICE, '-q', sound_file])
                    except Exception as e:
                        pass
                
                # Hold the persona animation for 8 seconds
                def revert_persona():
                    if self.current_state == persona:
                        self.set_state(BotStates.SCREENSAVER, "Screensaver...")
                self.master.after(8000, revert_persona)
                continue
                
            # ~2% chance every 30 seconds = roughly once every 25-30 minutes for audio vocalizations
            if random.random() < 0.02:
                # Ensure at least 20 minutes since last utterance
                if time.time() - self.last_screensaver_audio_time > 1200:
                    phrase = None
                    
                    # Check if LLM server is even reachable before trying
                    if is_llm_reachable():
                        try:
                            topic = random.choice(search_topics)
                            print(f"[SCREENSAVER] Searching for: {topic}")
                            search_result = search_web(topic)
                            
                            if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR"):
                                # Try up to 2 times with a short delay
                                for attempt in range(2):
                                    phrase = generate_thought(search_result)
                                    if phrase:
                                        print(f"[SCREENSAVER] BMO muses: {phrase}")
                                        
                                        # Check for image generation action
                                        img_url = None
                                        json_match = re.search(r'\{.*?\}', phrase, re.DOTALL)
                                        if json_match:
                                            try:
                                                action_data = json.loads(json_match.group(0))
                                                if action_data.get("action") == "display_image" and action_data.get("image_url"):
                                                    img_url = action_data.get("image_url")
                                                    # Migrate old pollinations URL if the LLM emitted the old format
                                                    img_url = img_url.replace("image.pollinations.ai/prompt/", "gen.pollinations.ai/image/")
                                                    phrase = phrase.replace(json_match.group(0), '').strip()
                                                    print(f"[SCREENSAVER] Image URL extracted: {img_url}")
                                            except Exception as e:
                                                print(f"[SCREENSAVER] JSON parse error in thought: {e}")
                                                
                                        # Speak out loud
                                        if phrase:
                                            self.speak(phrase, msg="Pondering...")
                                            
                                        # Display the image if an action was yielded
                                        if img_url:
                                            print(f"[SCREENSAVER] Downloading image from: {img_url}")
                                            self.set_state(BotStates.DISPLAY_IMAGE, "Visualizing...")
                                            try:
                                                req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
                                                with urllib.request.urlopen(req, timeout=15) as u:
                                                    raw_data = u.read()
                                                print(f"[SCREENSAVER] Image downloaded: {len(raw_data)} bytes")
                                                from io import BytesIO
                                                from PIL import ImageOps
                                                
                                                # Need to replicate apply_bmo_border for screensaver
                                                def apply_bmo_border(pil_img):
                                                    lcd_w, lcd_h = self.BG_WIDTH - 60, self.BG_HEIGHT - 60
                                                    img_ratio = pil_img.width / pil_img.height
                                                    target_ratio = lcd_w / lcd_h
                                                    if img_ratio > target_ratio:
                                                        new_h = lcd_h
                                                        new_w = int(new_h * img_ratio)
                                                    else:
                                                        new_w = lcd_w
                                                        new_h = int(new_w / img_ratio)
                                                    pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                                                    left = (new_w - lcd_w) / 2
                                                    top = (new_h - lcd_h) / 2
                                                    right = (new_w + lcd_w) / 2
                                                    bottom = (new_h + lcd_h) / 2
                                                    pil_img = pil_img.crop((left, top, right, bottom))
                                                    pil_img = ImageOps.expand(pil_img, border=10, fill="#1c201a")
                                                    pil_img = ImageOps.expand(pil_img, border=20, fill="#38b5a0")
                                                    return pil_img

                                                img = Image.open(BytesIO(raw_data))
                                                img = apply_bmo_border(img)
                                                print(f"[SCREENSAVER] Image processed, displaying on screen")
                                                
                                                # Schedule Tkinter update on main thread for thread safety
                                                def show_image_on_screen(pil_img=img):
                                                    try:
                                                        self.current_display_image = ImageTk.PhotoImage(pil_img)
                                                        self.background_label.config(image=self.current_display_image)
                                                        print(f"[SCREENSAVER] Image displayed successfully")
                                                    except Exception as e:
                                                        print(f"[SCREENSAVER] Tkinter display error: {e}")
                                                
                                                self.master.after(0, show_image_on_screen)
                                                
                                                # Show the image for 10 seconds, then revert to screensaver
                                                time.sleep(10)
                                                if self.current_state == BotStates.DISPLAY_IMAGE:
                                                    self.set_state(BotStates.SCREENSAVER, "Sleeping...")
                                                
                                            except urllib.error.URLError as e:
                                                print(f"[SCREENSAVER] Image download failed (network): {e}")
                                                if self.current_state == BotStates.DISPLAY_IMAGE:
                                                    self.set_state(BotStates.SCREENSAVER, "Sleeping...")
                                            except Exception as e:
                                                print(f"[SCREENSAVER] Image display error: {e}")
                                                import traceback as tb
                                                tb.print_exc()
                                                if self.current_state == BotStates.DISPLAY_IMAGE:
                                                    self.set_state(BotStates.SCREENSAVER, "Sleeping...")
                                        
                                        self.last_screensaver_audio_time = time.time()
                                        break
                                    print(f"[SCREENSAVER] Attempt {attempt + 1} failed, retrying...")
                                    time.sleep(5)
                        except Exception as e:
                            print(f"[SCREENSAVER] Dynamic thought failed: {e}")
                    else:
                        print("[SCREENSAVER] LLM server not reachable, skipping thought")
                    
                    # Fallback if dynamic generation failed
                    if not phrase:
                        phrase = random.choice(fallback_phrases)
                        print(f"[SCREENSAVER] Fallback: {phrase}")
                    
                    # Speak the thought
                    if self.current_state == BotStates.SCREENSAVER:
                        old_state = self.current_state
                        self.speak(phrase, msg="")
                        self.set_state(old_state, "")
                        self.last_screensaver_audio_time = time.time()

if __name__ == "__main__":
    root = tk.Tk()
    app = BotGUI(root)
    root.mainloop()
