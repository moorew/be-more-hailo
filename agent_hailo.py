# =========================================================================
#  Be More Agent (Hailo Optimized) 🤖
#  Simplified for Pi 5 + Hailo-10H + USB Mic
# =========================================================================

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageOps, ImageDraw
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
import math
from collections import deque
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
    DAYDREAM = "daydream"
    BORED = "bored"
    CURIOUS = "curious"

class BotGUI:

    BG_WIDTH, BG_HEIGHT = 800, 480 
    OVERLAY_WIDTH, OVERLAY_HEIGHT = 400, 300 

    def __init__(self, master):
        self.master = master
        master.title("Pi Assistant")
        master.attributes('-fullscreen', True) 
        master.configure(cursor='none') # Hide cursor for kiosk display
        master.bind('<Escape>', self.exit_fullscreen)
        
        # Events
        self.stop_event = threading.Event()
        self.thinking_sound_active = threading.Event()
        self.tts_active = threading.Event()
        self.current_state = BotStates.WARMUP
        self.last_state_change = time.time()
        
        # Audio State
        self.active_sounds = []
        self.current_audio_process = None
        self.tts_queue = []
        
        # Concurrency & Resource Management
        self.speak_lock = threading.Lock()
        self.llm_lock = threading.Lock()
        self.is_busy = False # True when interacting with human
        
        # Memory
        self.brain = Brain()
        self.recent_thoughts = deque(maxlen=20)
        
        # Mood System
        self.current_mood = 'neutral'
        self.last_mood_change = 0
        self.mood_duration = 300 # 5 minutes
        self.mouth_open = 0 # For lip sync
        self.eye_offset_x = 0
        self.eye_offset_y = 0
        self.blink_state = 0 # 0=open, 1=closed, 0.5=half
        
        self.expressions_map = {
            'happy': [BotStates.HAPPY, BotStates.HEART, BotStates.STARRY_EYED, BotStates.FOOTBALL],
            'neutral': [BotStates.IDLE, BotStates.DETECTIVE, BotStates.SIR_MANO, BotStates.BEE, BotStates.BORED, BotStates.CURIOUS],
            'sad': [BotStates.SAD, BotStates.CONFUSED],
            'sleepy': [BotStates.SLEEPY, BotStates.DAYDREAM],
            'jamming': [BotStates.JAMMING]
        }


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
        
        # Use a master click handler for hot corners and muting
        master.bind('<Button-1>', self.handle_click)

        self.animations = {}
        self.current_frame = 0
        self.mouth_ema = 0.0 # Exponential moving average for smooth transitions
        self.mouth_viseme_jitter = 0 # Offset for different "phoneme" looks
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
            self.master.after(0, lambda: self.status_label.config(text=msg))


    def handle_click(self, event):
        """Map screen clicks to hot corners or mute toggle."""
        # Only process clicks if not currently displaying a full-screen image
        if self.current_state == BotStates.DISPLAY_IMAGE:
            # Clicking an image clears it back to IDLE/SCREENSAVER
            self.set_state(BotStates.IDLE, "Ready...")
            return

        x, y = event.x, event.y
        # Get actual current window size for relative corner math
        win_w = self.master.winfo_width()
        win_h = self.master.winfo_height()
        
        # Corners are roughly the outer 25% of the screen
        corner_w = win_w // 4
        corner_h = win_h // 4
        
        if x < corner_w and y < corner_h:
            print(f"[CLICK] Top-Left Hot Corner: Generate Image (at {x},{y})")
            self.trigger_generate_image()
        elif x > win_w - corner_w and y < corner_h:
            print(f"[CLICK] Top-Right Hot Corner: Random Pondering (at {x},{y})")
            self.trigger_random_thought()
        elif x > win_w - corner_w and y > win_h - corner_h:
            print(f"[CLICK] Bottom-Right Hot Corner: Play Music (at {x},{y})")
            self.trigger_music()
        else:
            print(f"[CLICK] Center/Body: Toggle Mute (at {x},{y})")
            self.mute_bmo()

    def mute_bmo(self, event=None):
        """Toggle audio mute and sets the whimsical 'shhh' face."""
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.mute_label.place(relx=0.95, rely=0.05, anchor=tk.NE)
            
            # Stop all active audio processes cleanly
            for proc in self.active_sounds[:]: # Copy to avoid mutation during iteration
                try:
                    proc.terminate()
                    print(f"[MUTE] Terminated active sound process: {proc.pid}")
                except Exception:
                    pass
            self.active_sounds = []

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
            # For pre-recorded sounds, we'll manually set mouth_open to animate
            # while the sound plays, since aplay doesn't give us volume data.
            def animate_mouth_simple(proc):
                while proc.poll() is None:
                    # Randomly fluctuate mouth between 15 and 45 for pre-recorded speech
                    self.mouth_open = random.randint(15, 45)
                    time.sleep(0.08)
                self.mouth_open = 0

            proc = subprocess.Popen(['aplay', '-D', ALSA_DEVICE, '-q', sound_file])
            self.active_sounds.append(proc)
            
            # Start mouth animation thread for this sound
            if category in ["greeting_sounds", "thinking_sounds"]:
                threading.Thread(target=animate_mouth_simple, args=(proc,), daemon=True).start()

            # Cleanup thread to remove finished processes
            def cleanup():
                proc.wait()
                if proc in self.active_sounds:
                    self.active_sounds.remove(proc)
            threading.Thread(target=cleanup, daemon=True).start()
            return proc
        except Exception as e:
            print(f"Error playing sound {sound_file}: {e}")
            return None

    def load_animations(self):
        """Load PNG frames for each state from the faces/ directory."""
        self.animations = {}
        states = [d for d in os.listdir("faces") if os.path.isdir(os.path.join("faces", d))]
        for state in states:
            path = os.path.join("faces", state)
            files = sorted([f for f in os.listdir(path) if f.lower().endswith('.png')])
            frames = []
            for f in files:
                try:
                    img = Image.open(os.path.join(path, f))
                    # Ensure it's the right size
                    if img.size != (self.BG_WIDTH, self.BG_HEIGHT):
                        img = img.resize((self.BG_WIDTH, self.BG_HEIGHT), Image.Resampling.LANCZOS)
                    frames.append(ImageTk.PhotoImage(img))
                except Exception as e:
                    print(f"Error loading frame {f}: {e}")
            if frames:
                self.animations[state] = frames
        
        print(f"Loaded animations for: {list(self.animations.keys())}")
        self.tk_img = None

    def update_animation(self):
        if self.current_state == BotStates.DISPLAY_IMAGE:
            self.master.after(500, self.update_animation)
            return

        now = time.time()
        # Mood Logic
        if now - self.last_mood_change > self.mood_duration:
            self.current_mood = random.choice(list(self.expressions_map.keys()))
            self.last_mood_change = now
            print(f"[MOOD] BMO is now feeling: {self.current_mood}")

        # Screensaver Auto-Trigger
        if self.current_state == BotStates.IDLE and (now - self.last_state_change) > 60:
            self.set_state(BotStates.SCREENSAVER, "Screensaver...")

        # If in screensaver, pick expression from current mood
        display_state = self.current_state
        if self.current_state == BotStates.SCREENSAVER:
            # Change expression every 10 seconds
            expr_idx = int((now / 10) % len(self.expressions_map[self.current_mood]))
            display_state = self.expressions_map[self.current_mood][expr_idx]

        # Hide text status label during screensaver
        if self.current_state == BotStates.SCREENSAVER:
            if self.status_label.winfo_ismapped(): self.status_label.place_forget()
        else:
            if not self.status_label.winfo_ismapped():
                self.status_label.place(relx=0.5, rely=0.92, anchor=tk.S)

        # Animation Loop
        frames = self.animations.get(display_state, self.animations.get(BotStates.IDLE, []))
        if frames:
            if display_state == BotStates.SPEAKING:
                # 1. Smooth out mouth movement with Exponential Moving Average (EMA)
                # This prevents the mouth from "jumping" instantly to closed
                # 0.4 weight on new value, 0.6 on old gives a nice ~100ms decay
                self.mouth_ema = (self.mouth_ema * 0.6) + (self.mouth_open * 0.4)
                
                num_frames = len(frames)
                if self.mouth_ema > 1:
                    # 2. Base intensity mapping from smoothed EMA
                    base_idx = int((self.mouth_ema / 60) * (num_frames - 1))
                    
                    # 3. Simulate Visemes (different mouth positions for different sounds)
                    # We cycle a 'jitter' offset every few frames to simulate shifting phonemes
                    # even when the volume is relatively steady.
                    if int(time.time() * 20) % 2 == 0:
                        self.mouth_viseme_jitter = random.randint(-2, 2)
                        
                    idx = (base_idx + self.mouth_viseme_jitter) % num_frames
                    self.current_frame = min(num_frames - 1, max(0, idx))
                else:
                    self.current_frame = 0 # Closed
            else:
                self.current_frame = (self.current_frame + 1) % len(frames)

            self.tk_img = frames[self.current_frame]
            self.background_label.config(image=self.tk_img)

        # Dynamic frame rate: 40ms (25fps) for speaking lip-sync, 120ms for everything else
        interval = 40 if display_state == BotStates.SPEAKING else 120
        self.master.after(interval, self.update_animation)

    # --- AUDIO INPUT ---
    def wait_for_wakeword(self, oww):
        """Block until wake word is heard with retry logic for mic errors."""
        CHUNK = 1280
        capture_rate = MIC_SAMPLE_RATE # 48000
        target_rate = 16000
        downsample_factor = capture_rate // target_rate
        
        print(f"[EARS] Waiting for wake word... (Index: {MIC_DEVICE_INDEX}, Rate: {capture_rate})")
        
        # Prepare fast resampling indices once
        # Downsample from capture_rate to 16000 by picking every Nth sample
        resample_indices = np.arange(0, CHUNK * downsample_factor, downsample_factor).astype(np.int32)
        
        retry_count = 0
        while not self.stop_event.is_set():
            try:
                # Use a smaller blocksize to reduce latency
                with sd.InputStream(samplerate=capture_rate, device=MIC_DEVICE_INDEX, channels=1, dtype='int16', blocksize=CHUNK * downsample_factor) as stream:
                    retry_count = 0 # Reset on success
                    while not self.stop_event.is_set():
                        if self.is_busy:
                            time.sleep(0.5)
                            continue
                            
                        data, overflowed = stream.read(CHUNK * downsample_factor)
                        if not data.any(): continue
                        
                        # 1. Quick Volume Check (Skip OWW if it's too quiet)
                        current_max = np.max(np.abs(data))
                        if current_max < 250: # Adjust threshold as needed
                            continue

                        # 2. Fast Resampling (Nearest Neighbor slicing is much faster than scipy.signal.resample)
                        audio_16k = data[resample_indices].flatten() 
                        
                        # 3. Predict
                        oww.predict(audio_16k)
                        
                        for key in oww.prediction_buffer.keys():
                            score = oww.prediction_buffer[key][-1]
                            if score > WAKE_WORD_THRESHOLD:
                                print(f"[EARS] Wake Word Detected: {key} (Score: {score:.2f})")
                                oww.reset()
                                return True
            except Exception as e:
                retry_count += 1
                print(f"[EARS] Audio Input Error (Attempt {retry_count}): {e}")
                self.set_state(BotStates.ERROR, "Mic Error")
                if retry_count > 5:
                    print("[EARS] Too many mic errors, restarting audio system...")
                    # Possible attempt to reset ALSA? subprocess.run(["alsactl", "init"])
                    time.sleep(5)
                    retry_count = 0
                time.sleep(2)
                # Try to go back to IDLE if we were in ERROR
                if self.current_state == BotStates.ERROR:
                    self.set_state(BotStates.IDLE, "Retrying mic...")
        return False

    def record_audio(self):
        """Record until silence with volume-driven lip sync, with retry logic for mic errors."""
        print("Recording...")
        filename = "input.wav"
        frames = []
        silent_chunks = 0
        has_spoken = False

        def callback(indata, frames_count, time, status):
            nonlocal silent_chunks, has_spoken
            vol = np.linalg.norm(indata)
            # Update mouth_open for real-time lip sync during recording (listening mode)
            if self.current_state == BotStates.LISTENING:
                self.mouth_open = min(60, vol / 500)

            frames.append(indata.copy())
            if vol < 500: # Silence threshold
                silent_chunks += 1
            else:
                silent_chunks = 0
                has_spoken = True

        retry_count = 0
        while retry_count < 3:
            try:
                with sd.InputStream(samplerate=MIC_SAMPLE_RATE, device=MIC_DEVICE_INDEX, channels=1, dtype='int16', callback=callback):
                    while not self.stop_event.is_set():
                        sd.sleep(50)
                        if not has_spoken and silent_chunks > 100: break
                        if has_spoken and silent_chunks > 40: break
                        if len(frames) > (MIC_SAMPLE_RATE * 10 / 512): break
                    break # Success!
            except Exception as e:
                retry_count += 1
                print(f"Recording Error (Attempt {retry_count}): {e}")
                time.sleep(1)
                if retry_count >= 3:
                    self.set_state(BotStates.ERROR, "Mic Error")
                    return None

        self.mouth_open = 0 # Reset
        if not frames: return None
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

    def play_audio_with_sync(self, audio_data_input):
        """Play PCM audio and update mouth_open in real-time for sync. 
        Supports both bytes and file-like streams."""
        from core.config import ALSA_DEVICE
        import io

        # 22050 Hz, 16-bit, Mono (Piper default)
        sample_rate = 22050
        # Reduced chunk size for more reactive lip-sync updates (roughly every 23ms)
        chunk_size = 512 # samples 

        if isinstance(audio_data_input, bytes):
            stream = io.BytesIO(audio_data_input)
        else:
            stream = audio_data_input

        # Start aplay with a much smaller buffer to minimize sound-to-mouth lag
        # --buffer-time=50000 is 50ms, which is roughly one animation frame (50ms)
        aplay_cmd = ["aplay", "-D", ALSA_DEVICE, "-r", str(sample_rate), "-f", "S16_LE", "-t", "raw", "-q", "--buffer-time=50000"]
        proc = subprocess.Popen(aplay_cmd, stdin=subprocess.PIPE)

        try:
            start_time = time.time()
            chunk_idx = 0

            while not self.stop_event.is_set():
                if self.is_muted: break
                
                # 1024 samples * 2 bytes per sample (S16_LE)
                raw_chunk = stream.read(chunk_size * 2)
                if not raw_chunk:
                    break

                try:
                    proc.stdin.write(raw_chunk)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    break

                # volume analysis on the chunk we just fed to the speaker
                audio_chunk = np.frombuffer(raw_chunk, dtype=np.int16)
                vol = np.sqrt(np.mean(audio_chunk.astype(np.float32)**2))

                # Scale volume for better mouth movement sensitivity
                if self.current_state == BotStates.SPEAKING:
                    # Increased sensitivity (vol/25 instead of 100)
                    self.mouth_open = min(60, vol / 25)

                # Basic sync: sleep to match playback rate
                chunk_idx += 1
                elapsed = time.time() - start_time
                expected = (chunk_idx * chunk_size) / sample_rate
                if expected > elapsed:
                    time.sleep(expected - elapsed)
        finally:
            if proc.stdin:
                try: proc.stdin.close()
                except Exception: pass
            try:
                proc.terminate()
                proc.wait(timeout=0.2)
            except Exception: pass
            self.mouth_open = 0
            self.mouth_ema = 0 # Final reset to closed

    def speak(self, text, msg="Speaking...", end_of_turn=True):
        from core.tts import clean_text_for_speech
        from core.config import PIPER_CMD, PIPER_MODEL

        clean_text = clean_text_for_speech(text)
        if not clean_text or not any(c.isalnum() for c in clean_text):
            return

        print(f"Speaking: {clean_text[:30]}...")

        with self.speak_lock:
            try:
                # 1. Start streaming synthesis for instant response
                safe_text = clean_text.replace("'", "'\\''")
                piper_cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_raw"
                proc = subprocess.Popen(piper_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

                # 2. Set SPEAKING state immediately
                if self.current_state != BotStates.DISPLAY_IMAGE:
                    if msg is not None:
                        self.set_state(BotStates.SPEAKING, msg)
                    elif self.current_state != BotStates.SPEAKING:
                        self.current_state = BotStates.SPEAKING
                        self.current_frame = 0
                        self.last_state_change = time.time()

                # 3. Play stream with real-time lip-sync
                if not self.is_muted:
                    self.play_audio_with_sync(proc.stdout)
                else:
                    time.sleep(1.0) # Shorter wait for muted streaming chunks

                # Cleanup Piper process
                try:
                    proc.wait(timeout=0.5)
                except Exception:
                    try: proc.terminate()
                    except: pass

                # 4. Return to IDLE state ONLY if this is the last chunk
                if end_of_turn and self.current_state == BotStates.SPEAKING:
                    if msg is not None:
                        self.set_state(BotStates.IDLE, "Ready...")
                    else:
                        self.current_state = BotStates.IDLE
                        self.current_frame = 0
                        self.last_state_change = time.time()

            except Exception as e:
                print(f"Hardware TTS Error: {e}")
                self.mouth_open = 0

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
            self.is_busy = False
            if self.wait_for_wakeword(oww):
                self.is_busy = True
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
                    self.is_busy = False
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
                    
                    # Lock LLM access to prevent screensaver interference
                    with self.llm_lock:
                        chunks = list(self.brain.stream_think(user_text))
                        for i, chunk in enumerate(chunks):
                            if not chunk.strip():
                                continue
                            
                            is_last = (i == len(chunks) - 1)
                            full_response += chunk
                            print(f"[AGENT] Chunk {i+1}/{len(chunks)}: '{chunk[:40]}...'")
                            
                            # Handle json actions
                            if '{"action": "take_photo"}' in chunk:
                                print("[AGENT] take_photo action detected!")
                                taking_photo = True
                                break
                                
                            json_match = re.search(r'\{.*?\}', chunk, re.DOTALL)
                            if json_match:
                                try:
                                    action_data = json.loads(json_match.group(0))
                                    if action_data.get("action") == "display_image":
                                        image_url = action_data.get("image_url")
                                        chunk = chunk.replace(json_match.group(0), '').strip()
                                    elif action_data.get("action") == "set_expression":
                                        expr = action_data.get("value").lower()
                                        if expr in [BotStates.HAPPY, BotStates.SAD, BotStates.ANGRY, BotStates.SURPRISED, BotStates.SLEEPY, BotStates.DIZZY, BotStates.CHEEKY, BotStates.HEART, BotStates.STARRY_EYED, BotStates.CONFUSED]:
                                            self.set_state(expr, f"Feeling {expr}...")
                                        chunk = chunk.replace(json_match.group(0), '').strip()
                                    elif action_data.get("action") == "play_music":
                                        def music_worker():
                                            while self.current_state in [BotStates.SPEAKING, BotStates.THINKING]:
                                                time.sleep(0.5)
                                            music_proc = self.play_sound("music")
                                            if music_proc:
                                                self.set_state(BotStates.JAMMING, "Jamming!")
                                                music_proc.wait()
                                                if self.current_state == BotStates.JAMMING:
                                                    self.set_state(BotStates.IDLE, "Ready")
                                        threading.Thread(target=music_worker, daemon=True).start()
                                        chunk = chunk.replace(json_match.group(0), '').strip()
                                except Exception: pass
                                    
                            if chunk.strip():
                                self.speak(chunk, msg=None, end_of_turn=is_last)


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
                        # Speak confirmation before downloading
                        self.speak("Ooh, let BMO draw something for you!")
                        self.set_state(BotStates.DISPLAY_IMAGE, "Showing Image...")
                        print(f"[IMAGE] Starting image display for: {image_url}")
                        try:
                            # Note: migrated to loremflickr
                            print(f"[IMAGE] Downloading: {image_url}")
                            req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=30) as u:
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
                        with self.llm_lock:
                            for chunk in self.brain.stream_think(user_text):
                                if chunk.strip():
                                    self.speak(chunk)
                    except Exception as e:
                        print(f"Follow-up LLM error: {e}")

                        
                    self.set_state(BotStates.IDLE, "Ready")
                    # Loop back around and listen again!
                
                self.is_busy = False
                # Guarantee a 1 second cool-down before we loop all the way back up

                # and call wait_for_wakeword(). This ensures ALSA capture locks are fully
                # released by the kernel, preventing PaErrorCode -9999 crashes.
                time.sleep(1.0)

    def trigger_random_thought(self, event=None):
        """Manually trigger a random pondering thought (BMO's red button)."""
        if self.is_busy or self.current_state in [BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING]:
            return

        def run_thought():
            from core.search import search_web, search_images
            from core.config import LLM_URL, FAST_LLM_MODEL
            import requests as http_requests

            try:
                self.is_busy = True
                topics = [
                    "interesting fun fact of the day", "weather forecast today in Brantford, Ontario",
                    "this day in history", "cool science discovery this week", "funny animal fact",
                    "random wholesome internet story", "video game history fact", "weird food fact",
                    "Adventure Time lore or trivia", "today's astronomy picture", "best joke of the day",
                    "funny dad jokes", "hilarious puns", "unusual world records"
                ]

                topic = random.choice(topics)
                for _ in range(3):
                    if topic in self.recent_thoughts:
                        topic = random.choice(topics)
                    else:
                        break

                print(f"[BUTTON] Manually triggering thought for: {topic}")
                self.set_state(BotStates.THINKING, "Thinking...")

                search_result = search_web(topic)
                if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR"):
                    phrase = self.generate_thought_internal(search_result)

                    if phrase:
                        self.recent_thoughts.append(topic)
                        # Check for image URL or subject
                        image_url = None
                        json_match = re.search(r'\{.*?\}', phrase, re.DOTALL)
                        if json_match:
                            try:
                                action_data = json.loads(json_match.group(0))
                                if action_data.get("action") == "display_image":
                                    subject = action_data.get("subject") or action_data.get("image_url")
                                    if subject:
                                        if "://" in subject:
                                            image_url = subject
                                        else:
                                            image_url = search_images(subject)
                                    phrase = phrase.replace(json_match.group(0), '').strip()
                            except Exception: pass

                        self.speak(phrase, msg="Pondering...")
                        if image_url:
                            # Wait for BMO to start speaking before showing image
                            time.sleep(1.5)
                            self.display_remote_image(image_url, commentary_prompt=topic)
                        else:
                            self.set_state(BotStates.IDLE, "Ready...")
                    else:
                        self.set_state(BotStates.IDLE, "Ready...")
                else:
                    self.set_state(BotStates.IDLE, "Ready...")
            except Exception as e:
                print(f"[BUTTON] Thought error: {e}")
                self.set_state(BotStates.IDLE, "Ready...")
            finally:
                self.is_busy = False

        threading.Thread(target=run_thought, daemon=True).start()

    def trigger_music(self, event=None):
        """Manually trigger BMO to play music and jam."""
        if self.is_busy or self.current_state in [BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING, BotStates.JAMMING]:
            return
            
        def run_music():
            try:
                self.is_busy = True
                # Wait for current speaking to finish if any
                while self.current_state in [BotStates.SPEAKING, BotStates.THINKING]:
                    time.sleep(0.5)
                
                intros = [
                    "Oh yeah! BMO is going to jam out!",
                    "Time for music! La la la!",
                    "BMO loves this song!",
                    "Let BMO play you a tune!",
                    "Music time! BMO is so excited!",
                ]
                self.speak(random.choice(intros), msg="Getting ready to jam...")
                print("[MUSIC] Starting music playback...")
                music_proc = self.play_sound("music")
                if music_proc:
                    self.set_state(BotStates.JAMMING, "Jamming!")
                    music_proc.wait()
                    time.sleep(1) # Extra buffer
                    if self.current_state == BotStates.JAMMING:
                        self.set_state(BotStates.IDLE, "Ready")
                else:
                    self.speak("BMO wants to play music, but there are no songs loaded!")
            finally:
                self.is_busy = False
                
        threading.Thread(target=run_music, daemon=True).start()

    def trigger_generate_image(self, event=None):
        """Manually trigger an image generation."""
        if self.is_busy or self.current_state in [BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING]:
            return
            
        def run_image_thought():
            from core.config import LLM_URL, FAST_LLM_MODEL
            from core.search import search_images
            import requests as http_requests
            
            try:
                self.is_busy = True
                self.set_state(BotStates.THINKING, "Imagining...")
                
                # Say something generic first
                intros = [
                    "BMO is feeling creative! Let me draw something for you.",
                    "I am going to make some art!",
                    "Time for BMO's art class! One moment...",
                    "Let me paint a beautiful picture for you."
                ]
                self.speak(random.choice(intros), msg="Imagining...")
                
                prompt = "You are BMO. You want to show a picture. Output ONLY a short, vivid 3-5 word descriptive search term for an image (e.g. 'cute baby penguin' or 'colorful deep space nebula'). Do NOT say anything else."
                payload = {
                    "model": FAST_LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are BMO. You only output short image search terms."},
                        {"role": "user", "content": prompt}
                    ],
                    "stream": False,
                    "options": {"temperature": 0.9, "num_predict": 20}
                }
                
                search_term = "cute robot"
                resp = http_requests.post(LLM_URL, json=payload, timeout=30)
                if resp.status_code == 200:
                    search_term = resp.json().get("message", {}).get("content", "").strip()
                    search_term = search_term.replace('"', '').replace('\n', '').strip()
                
                image_url = search_images(search_term)
                if image_url:
                    self.display_remote_image(image_url, commentary_prompt=f"a picture of {search_term}")
                else:
                    self.speak("My imagination is a bit fuzzy right now, I couldn't draw that.")
                    self.set_state(BotStates.IDLE, "Ready...")
            except Exception as e:
                print(f"[BUTTON] Image generation error: {e}")
                self.set_state(BotStates.IDLE, "Ready...")
            finally:
                self.is_busy = False
                        
                    # Find a real image
                    url = search_images(search_term)
                    
                    if not url:
                        # Fallback to a placeholder if search fails
                        import random
                        lock_id = random.randint(1, 100000)
                        url = f"https://loremflickr.com/640/480/{search_term.replace(' ', ',')}?lock={lock_id}"
                    
                    # Wait for BMO to finish speaking the intro
                    while self.current_state in [BotStates.SPEAKING, BotStates.THINKING]:
                        time.sleep(0.5)
                        
                    self.display_remote_image(url, commentary_prompt=search_term)
                    return
            except Exception as e:
                print(f"[IMAGE] Generator failed: {e}")
                self.is_busy = False
                self.set_state(BotStates.IDLE, "Ready...")

        threading.Thread(target=run_image_thought, daemon=True).start()

    def display_remote_image(self, image_url, commentary_prompt=None):
        """Fetch and display an image from a URL with BMO styling."""
        def run_display():
            self.set_state(BotStates.DISPLAY_IMAGE, "Visualizing...")
            try:
                import urllib.request
                import urllib.parse
                
                # Safely encode the URL path and query
                parts = urllib.parse.urlparse(image_url)
                safe_path = urllib.parse.quote(urllib.parse.unquote(parts.path))
                safe_query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe='=&')
                safe_url = urllib.parse.urlunparse((parts.scheme, parts.netloc, safe_path, parts.params, safe_query, parts.fragment))
                
                req = urllib.request.Request(safe_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as u:
                    raw_data = u.read()
                            
                if not raw_data:
                    raise Exception("Failed to download image data.")
                
                from io import BytesIO
                from PIL import ImageOps, Image
                
                img = Image.open(BytesIO(raw_data))
                
                # Apply BMO border
                lcd_w, lcd_h = self.BG_WIDTH - 60, self.BG_HEIGHT - 60
                img_ratio = img.width / img.height
                target_ratio = lcd_w / lcd_h
                if img_ratio > target_ratio:
                    new_h = lcd_h
                    new_w = int(new_h * img_ratio)
                else:
                    new_w = lcd_w
                    new_h = int(new_w / img_ratio)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                left = (new_w - lcd_w) / 2
                top = (new_h - lcd_h) / 2
                right = (new_w + lcd_w) / 2
                bottom = (new_h + lcd_h) / 2
                img = img.crop((left, top, right, bottom))
                img = ImageOps.expand(img, border=10, fill="#1c201a")
                img = ImageOps.expand(img, border=20, fill="#38b5a0")
                
                def show_img(p_img=img):
                    try:
                        self.current_display_image = ImageTk.PhotoImage(p_img)
                        self.background_label.config(image=self.current_display_image)
                    except Exception: pass
                
                self.master.after(0, show_img)
                
                if commentary_prompt:
                    from core.config import LLM_URL, FAST_LLM_MODEL
                    import requests as http_requests
                    
                    thought_prompt = f"You just drew a picture of: {commentary_prompt}. React to your artwork in one short sentence as BMO. Be proud of it!"
                    payload = {
                        "model": FAST_LLM_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are BMO, a cute little robot. Keep it under 20 words."},
                            {"role": "user", "content": thought_prompt}
                        ],
                        "stream": False,
                        "options": {"temperature": 0.8, "num_predict": 40}
                    }
                    try:
                        resp = http_requests.post(LLM_URL, json=payload, timeout=20)
                        if resp.status_code == 200:
                            commentary = resp.json().get("message", {}).get("content", "").strip()
                            self.speak(commentary, msg="Admiring art...")
                    except Exception as e:
                        pass
                
                time.sleep(12)
                if self.current_state == BotStates.DISPLAY_IMAGE:
                    self.set_state(BotStates.IDLE, "Ready...")
            except Exception as e:
                print(f"[IMAGE] Failed to display: {e}")
                self.set_state(BotStates.IDLE, "Ready...")
            finally:
                self.is_busy = False
        
        threading.Thread(target=run_display, daemon=True).start()

    def generate_thought_internal(self, search_result):
        """Shared logic for generating a BMO thought from search results."""
        from core.config import LLM_URL, FAST_LLM_MODEL
        from core.llm import strip_prompt_leakage
        import requests as http_requests

        if not self.llm_lock.acquire(blocking=False):
            return None
        try:
            thought_prompt = (
                "You are BMO, a cute little robot. You just learned something interesting from the real world. "
                "Share what you found as a short, charming 'pondering' to yourself. "
                "RULES:\n"
                "1. You MUST start your response with the tag '[BMO]'. \n"
                "2. After the tag, say: 'I found this today, [Summarize the specific fact].' \n"
                "3. Then, share your own charming reaction or opinion naturally. \n"
                "4. If the topic is visual, you SHOULD include exactly one JSON action on a new line: \n"
                "   {\"action\": \"display_image\", \"subject\": \"[CUTE_WHIMSICAL_DESCRIPTION]\"} \n"
                "5. CRITICAL: Your entire response MUST be under 60 words. You must finish your thought completely. \n"
                "6. Do NOT include labels like 'Summarize:' or 'Fact:' or repeat these rules.\n"
                f"Info: {search_result[:1500]}"
            )
            payload = {
                "model": FAST_LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "You are BMO, a cute little robot who muses to yourself. Be concise, specific, and always finish your thought within 60 words. Do NOT repeat instructions."},
                    {"role": "user", "content": thought_prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.8, "num_predict": 512}
            }
            resp = http_requests.post(LLM_URL, json=payload, timeout=60)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "").strip()
                return strip_prompt_leakage(content)
        except Exception as e:
            print(f"[LLM] Thought generation error: {e}")
        finally:
            self.llm_lock.release()
        return None

    def screensaver_audio_loop(self):
        import datetime
        import requests as http_requests
        from core.search import search_web
        from core.config import LLM_URL, FAST_LLM_MODEL
        
        # Topics BMO might wonder about — used as web search seeds
        search_topics = [
            "interesting fun fact of the day",
            "weather forecast today in Brantford, Ontario",
            "this day in history",
            "cool science discovery this week",
            "funny animal fact",
            "random wholesome internet story",
            "video game history fact",
            "weird food fact",
            "Adventure Time lore or trivia",
            "today's astronomy picture",
            "best joke of the day",
            "random Wikipedia article summary",
            "latest space news from NASA",
            "strange laws in Canada",
            "mythology fun fact",
            "how a computer works for kids",
            "cool deep sea creatures",
            "interesting insect facts",
            "history of robots",
            "why do cats purr",
            "fastest land animals",
            "tallest buildings in the world",
            "invention of the telephone",
            "what is a black hole",
            "funny dad jokes",
            "hilarious puns",
            "knock knock jokes",
            "short funny stories",
            "unusual world records",
            "history of board games",
            "how honey is made",
            "origins of common idioms",
            "mysteries of the pyramids",
            "first mission to the moon",
            "evolution of video game consoles",
            "how to make a paper airplane",
            "why the sky is blue",
            "fun facts about penguins",
            "discovery of dinosaurs",
            "life on Mars possibilities",
            "history of ice cream",
            "how the internet works for kids",
            "cool chemistry experiments",
            "amazing origami facts",
            "the world's oldest trees",
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
        
        while not self.stop_event.is_set():
            time.sleep(30) # Check every 30 seconds
            
            # Watchdog: if is_busy is True for too long (e.g. > 2 mins), clear it.
            # This prevents BMO from being 'stuck' forever if a thread dies.
            if self.is_busy and (time.time() - self.last_state_change > 120):
                print("[WATCHDOG] BMO was busy for > 120s. Force-clearing is_busy.")
                self.is_busy = False
                self.set_state(BotStates.IDLE, "Ready...")

            if self.current_state != BotStates.SCREENSAVER or self.is_busy:
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
            
            # Random Pondering (~4% chance every 30s)
            elif random.random() < 0.04:
                if is_llm_reachable():
                    try:
                        # 1. Ask the LLM for a random topic
                        topic = None
                        try:
                            topic_messages = [
                                {"role": "system", "content": "You are BMO's brain. Suggest one very specific, random, and interesting topic for BMO to learn about today. Examples: 'history of the first toaster', 'why do wombats have square poop', 'the mystery of the Voynich manuscript'. Keep it under 10 words. Provide ONLY the topic, no quotes or preamble."},
                                {"role": "user", "content": "Give me a random topic."}
                            ]
                            topic_payload = {
                                "model": FAST_LLM_MODEL,
                                "messages": topic_messages,
                                "stream": False,
                                "options": {"temperature": 1.0, "num_predict": 20}
                            }
                            topic_resp = http_requests.post(LLM_URL, json=topic_payload, timeout=10)
                            if topic_resp.status_code == 200:
                                topic = topic_resp.json().get("message", {}).get("content", "").strip().strip('"').strip("'")
                                topic = re.sub(r'^Topic:|^BMO topic:|^I want to learn about: ', '', topic, flags=re.IGNORECASE)
                        except Exception as e:
                            print(f"[SCREENSAVER] LLM topic generation failed: {e}")

                        if not topic or len(topic) < 3:
                            topic = random.choice(search_topics)
                            for _ in range(3):
                                if topic in self.recent_thoughts:
                                    topic = random.choice(search_topics)
                                else:
                                    break
                                
                        print(f"[SCREENSAVER] Searching for: {topic}")
                        search_result = search_web(topic)
                        
                        phrase = None
                        if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR"):
                            phrase = self.generate_thought_internal(search_result)
                            
                            if phrase:
                                self.recent_thoughts.append(topic)
                                # Check for image URL or subject
                                image_url = None
                                json_match = re.search(r'\{.*?\}', phrase, re.DOTALL)
                                if json_match:
                                    try:
                                        action_data = json.loads(json_match.group(0))
                                        if action_data.get("action") == "display_image":
                                            subject = action_data.get("subject") or action_data.get("image_url")
                                            if subject:
                                                if "://" in subject:
                                                    image_url = subject
                                                else:
                                                    image_url = search_images(subject)
                                            phrase = phrase.replace(json_match.group(0), '').strip()
                                    except Exception: pass
                                
                                # Speak the thought
                                if phrase and self.current_state == BotStates.SCREENSAVER and not self.is_busy:
                                    self.is_busy = True
                                    self.speak(phrase, msg="Pondering...")
                                    self.last_screensaver_audio_time = time.time()
                                    
                                    # Handle image display
                                    if image_url:
                                        # Wait for BMO to start speaking
                                        time.sleep(1.5)
                                        self.display_remote_image(image_url, commentary_prompt=topic)
                                    else:
                                        self.is_busy = False
                    except Exception as e:
                        print(f"[SCREENSAVER] Thought failed: {e}")
                        self.is_busy = False
                        self.set_state(BotStates.SCREENSAVER, "Sleeping...")
                
                # Revert to screensaver state if needed
                if self.current_state != BotStates.SCREENSAVER and not self.is_busy and self.current_state != BotStates.DISPLAY_IMAGE:
                    self.set_state(BotStates.SCREENSAVER, "Sleeping...")

if __name__ == "__main__":
    root = tk.Tk()
    app = BotGUI(root)
    root.mainloop()

