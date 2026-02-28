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
        self.last_state_change = time.time()
        
        # Audio State
        self.current_audio_process = None
        self.tts_queue = []
        
        # Memory
        self.brain = Brain()

        # Init UI
        self.background_label = tk.Label(master, bg='black')
        self.background_label.place(x=0, y=0, width=self.BG_WIDTH, height=self.BG_HEIGHT)
        
        self.status_label = tk.Label(master, text="Initializing...", font=('Courier New', 16, 'bold'), fg='white', bg='black')
        self.status_label.place(relx=0.5, rely=0.9, anchor=tk.S)

        self.animations = {}
        self.current_frame = 0
        self.load_animations()
        self.load_sounds()
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
            self.last_state_change = time.time()
            print(f"[STATE] {state.upper()}: {msg}")
        if msg:
            self.status_label.config(text=msg)

    # --- ANIMATION & SOUND ENGINE ---
    def load_sounds(self):
        self.sounds = {
            "greeting_sounds": [],
            "ack_sounds": [],
            "thinking_sounds": []
        }
        base = "sounds"
        for category in self.sounds.keys():
            path = os.path.join(base, category)
            if os.path.exists(path):
                self.sounds[category] = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith('.wav')]

    def play_sound(self, category):
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
        for state in [BotStates.IDLE, BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING, BotStates.ERROR]:
            path = os.path.join(base, state)
            self.animations[state] = []
            if os.path.exists(path):
                files = sorted([f for f in os.listdir(path) if f.lower().endswith('.png')])
                for f in files:
                    img_path = os.path.join(path, f)
                    img = Image.open(img_path).resize((self.BG_WIDTH, self.BG_HEIGHT))
                    self.animations[state].append(ImageTk.PhotoImage(img))
                    
        # Load screensaver frames (all images recursively, excluding 'warmup')
        self.animations[BotStates.SCREENSAVER] = []
        for root, dirs, files in os.walk(base):
            if "warmup" in root:
                continue
            for f in files:
                if f.lower().endswith('.png'):
                    img_path = os.path.join(root, f)
                    try:
                        img = Image.open(img_path).resize((self.BG_WIDTH, self.BG_HEIGHT))
                        self.animations[BotStates.SCREENSAVER].append(ImageTk.PhotoImage(img))
                    except Exception as e:
                        print(f"Failed to load screensaver image {f}: {e}")
        
        # Shuffle screensaver sequence so it's fresh each run
        random.shuffle(self.animations[BotStates.SCREENSAVER])
    
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
                self.status_label.place(relx=0.5, rely=0.9, anchor=tk.S)

        frames = self.animations.get(self.current_state, []) or self.animations.get(BotStates.IDLE, [])
        if frames:
            self.current_frame = (self.current_frame + 1) % len(frames)
            
            # Re-shuffle screensaver when it loops completely
            if self.current_state == BotStates.SCREENSAVER and self.current_frame == 0:
                random.shuffle(self.animations[BotStates.SCREENSAVER])
                
            self.background_label.config(image=frames[self.current_frame])
        
        # Match web UI animation speeds
        speed = 500
        if self.current_state == BotStates.SPEAKING:
            speed = 150
        elif self.current_state == BotStates.THINKING:
            speed = 500
        elif self.current_state == BotStates.LISTENING:
            speed = 400
        elif self.current_state == BotStates.SCREENSAVER:
            speed = 5000 # 5 seconds per image like old script

        self.master.after(speed, self.update_animation)

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

    # --- STT & TTS ---
    def transcribe(self, filename):
        print("Transcribing...")
        return transcribe_audio(filename)

    def speak(self, text):
        print(f"Speaking: {text}")
        play_audio_on_hardware(text)

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
        ignore_until = time.time() + 1.0          # ignore first second (echo die-down)
        deadline = time.time() + timeout_sec       # give up if no speech by here
        max_deadline = time.time() + timeout_sec + 8  # hard cap regardless

        def callback(indata, frames_count, time_info, status):
            nonlocal silent_chunks, has_spoken
            if time.time() < ignore_until:
                return  # still in echo dead-zone — ignore all audio
            vol = np.linalg.norm(indata) * 10
            frames.append(indata.copy())
            if vol < 50000:
                silent_chunks += 1
            else:
                silent_chunks = 0
                has_spoken = True

        try:
            with sd.InputStream(samplerate=MIC_SAMPLE_RATE, device=MIC_DEVICE_INDEX,
                                channels=1, dtype='int16', callback=callback):
                while not self.stop_event.is_set():
                    sd.sleep(100)
                    now = time.time()
                    # Human speech detected and gone quiet — we have a follow-up
                    if has_spoken and silent_chunks > 40:
                        break
                    # No speech in the listen window — give up quietly
                    if now > deadline and not has_spoken:
                        return None
                    # Hard cap — always exit (catches lingering echo)
                    if now > max_deadline:
                        return None
        except Exception as e:
            print(f"Follow-up listen error: {e}")
            return None

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
        except:
            print("Failed to load wakeword model!")
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
                        except:
                            pass
                        self.thinking_audio_process = None
                    continue

                # 4. LLM
                self.set_state(BotStates.THINKING, "Thinking...")

                # Stop the thinking sound loop
                if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                    try:
                        self.thinking_audio_process.terminate()
                    except:
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
                            except Exception as e:
                                print(f"JSON Parse Error: {e}")
                                
                        if chunk.strip():
                            self.set_state(BotStates.SPEAKING, "Speaking...")
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
                                except:
                                    pass
                                self.thinking_audio_process = None
                            self.set_state(BotStates.SPEAKING, "Speaking...")
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
                            req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req) as u:
                                raw_data = u.read()
                            from io import BytesIO
                            img = Image.open(BytesIO(raw_data)).resize((self.BG_WIDTH, self.BG_HEIGHT))
                            self.current_display_image = ImageTk.PhotoImage(img)
                            self.background_label.config(image=self.current_display_image)
                        except Exception as e:
                            print(f"Image Download Error: {e}")

                except Exception as e:
                    print(f"ERROR in LLM/TTS pipeline: {e}")
                    traceback.print_exc()

                self.set_state(BotStates.IDLE, "Ready")

                # Conversation follow-up: listen briefly for a natural reply
                self.set_state(BotStates.LISTENING, "Still listening...")
                followup_wav = self.record_followup(timeout_sec=8)
                if followup_wav:
                    self.set_state(BotStates.THINKING, "Transcribing...")
                    threading.Thread(target=play_thinking_sequence, daemon=True).start()
                    user_text = self.transcribe(followup_wav)
                    print(f"Follow-up Transcribed: {user_text}")
                    if len(user_text) >= 2:
                        self.set_state(BotStates.THINKING, "Thinking...")
                        if hasattr(self, 'thinking_audio_process') and self.thinking_audio_process:
                            try:
                                self.thinking_audio_process.terminate()
                            except:
                                pass
                            self.thinking_audio_process = None
                        try:
                            for chunk in self.brain.stream_think(user_text):
                                if chunk.strip():
                                    self.set_state(BotStates.SPEAKING, "Speaking...")
                                    self.speak(chunk)
                        except Exception as e:
                            print(f"Follow-up LLM error: {e}")
                        self.set_state(BotStates.IDLE, "Ready")
                    else:
                        self.set_state(BotStates.IDLE, "Waiting...")
                else:
                    self.set_state(BotStates.IDLE, "Waiting...")

if __name__ == "__main__":
    root = tk.Tk()
    app = BotGUI(root)
    root.mainloop()
