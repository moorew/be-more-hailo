# =========================================================================
#  Be More Agent (Hailo Optimized) 🤖
#  Simplified for Pi 5 + Hailo-10H + USB Mic
# =========================================================================

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageOps, ImageDraw
import queue
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
from core.llm import Brain, extract_json_object, strip_prompt_leakage, sanitize_messages
from core.tts import play_audio_on_hardware
from core.stt import transcribe_audio
from core.endpoint import EndpointDetector
from core.reminders import ReminderRegistry
from core.volume import HardwareVolume, scaled_wav
from core.briefing.settings import load_briefing_settings, update_settings
from core.briefing.scheduler import BriefingScheduler, prepare_briefing
from core.briefing import ui as briefing_ui
from core.config import LLM_KEEP_ALIVE, MIC_DEVICE_INDEX, MIC_SAMPLE_RATE, WAKE_WORD_MODEL, WAKE_WORD_THRESHOLD, ALSA_DEVICE, VOLUME

# Live face rig (bmo_face/): morphs the artwork instead of flipping PNG frames.
# Set BMO_FACE_RIG=0 to go back to the PNG faces; any load error does the same.
try:
    from bmo_face import SILENT as FACE_SILENT, LipSync, analyse_wav
    from bmo_face.tk_face import FaceView
    FACE_RIG_OK = True
except Exception as _face_err:
    print(f"[FACE] Rig unavailable, using PNG faces: {_face_err}")
    FACE_RIG_OK = False
USE_FACE_RIG = FACE_RIG_OK and os.environ.get("BMO_FACE_RIG", "1") != "0"
FACE_FPS_ACTIVE = 30   # talking / listening
FACE_FPS_CALM = 24     # everything else the rig draws
WAV_LIPSYNC_DELAY = 0.05  # aplay start-up latency for pre-recorded clips
# Mic buffer.  PortAudio's default (160 ms here) overflowed whenever the Tk
# thread held the GIL a little too long, restarting the capture stream.
MIC_LATENCY_S = 0.5
# Footer caption's bottom edge (fraction of screen height).  At 0.92 the 32 px
# label sat in y 410-442 and clipped open mouths (heart, shhh, error).
STATUS_RELY = 0.97

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
    LADYBUG = "ladybug"
    WORM = "worm"
    BRIEFING = "briefing"  # morning briefing playing: small face + cards

# --briefing-now: (start, end) "HH:MM" window opened at start-up for testing.
BRIEFING_NOW_WINDOW = None

# Every face is drawn live by the rig, mapped to a rig expression
# (bmo_face/expressions.json). SPEAKING uses the current talk mood instead
# (see TALK_MOODS). The PNG frames in faces/ are only loaded if the rig fails.
RIG_EXPRESSIONS = {
    BotStates.IDLE: "idle",
    BotStates.LISTENING: "listening",
    BotStates.THINKING: "thinking",
    BotStates.SPEAKING: None,
    BotStates.WARMUP: "sleepy",
    BotStates.ERROR: "error",
    BotStates.CAPTURING: "capturing",
    BotStates.HAPPY: "happy",
    BotStates.SAD: "sad",
    BotStates.ANGRY: "angry",
    BotStates.SURPRISED: "surprised",
    BotStates.SLEEPY: "sleepy",
    BotStates.DIZZY: "dizzy",
    BotStates.CHEEKY: "cheeky",
    BotStates.HEART: "heart",
    BotStates.STARRY_EYED: "starry",
    BotStates.CONFUSED: "confused",
    BotStates.SHHH: "shhh",
    BotStates.JAMMING: "jamming",
    BotStates.FOOTBALL: "football",
    BotStates.DETECTIVE: "detective",
    BotStates.SIR_MANO: "sir_mano",
    BotStates.LOW_BATTERY: "low_battery",
    BotStates.BEE: "bee",
    BotStates.DAYDREAM: "daydream",
    BotStates.BORED: "bored",
    BotStates.CURIOUS: "curious",
    BotStates.LADYBUG: "ladybug",
    BotStates.WORM: "worm",
    BotStates.BRIEFING: "happy",  # drawn in the briefing's talk mood (settings talk_mood)
}

# When the LLM sets an expression and then speaks, BMO talks in that mood:
# the mouth follows the voice while the eyes, brows and extras stay (heart
# eyes, stars, spirals...). Curious talks as surprised so the ring eyes don't
# stare through a whole sentence; daydream talks without its butterfly.
TALK_MOODS = {
    BotStates.HAPPY: "happy", BotStates.HEART: "heart", BotStates.CHEEKY: "cheeky",
    BotStates.STARRY_EYED: "starry", BotStates.JAMMING: "jamming", BotStates.FOOTBALL: "football",
    BotStates.SAD: "sad", BotStates.ANGRY: "angry", BotStates.DIZZY: "dizzy",
    BotStates.SURPRISED: "surprised", BotStates.CURIOUS: "surprised", BotStates.CONFUSED: "confused",
    BotStates.SLEEPY: "sleepy", BotStates.LOW_BATTERY: "low_battery", BotStates.DAYDREAM: "relaxed",
    BotStates.BORED: "bored",
}

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
        self.manual_wake_event = threading.Event()
        self.current_state = BotStates.WARMUP
        self.last_state_change = time.time()
        # Tracks the last real user/agent interaction.  Updated on wake fire,
        # tap, and trigger entry — NOT on every state transition.  Watchdog
        # uses this so a long DISPLAY_IMAGE view doesn't false-fire as "stuck".
        self.last_user_interaction = time.time()
        
        # Triple-tap-to-exit: tracks timestamps of the last 3 taps
        self._triple_tap_times = []

        # Audio State
        self.active_sounds = []
        self.current_audio_process = None
        self.tts_queue = []
        
        # Concurrency & Resource Management
        self.speak_lock = threading.Lock()
        self.llm_lock = threading.Lock()
        self._busy_lock = threading.Lock()  # Authoritative claim — use _try_claim_busy/_release_busy
        self.is_busy = False  # Read-only mirror of _busy_lock state for legacy read sites
        self._tts_aplay = None   # Shared aplay process kept alive across sentences in a turn
        self._piper_proc = None  # Persistent Piper process for the turn
        self._piper_reader_thread = None  # Thread piping Piper stdout → aplay stdin

        # Thinking sound — single controller (no more dueling threads)
        self.is_thinking_sound_playing = False
        self.thinking_audio_process = None
        self._thinking_lock = threading.Lock()
        self._thinking_thread = None

        # Per-turn LLM-action handoffs from _handle_response_chunk → main_loop
        self.taking_photo = False
        self.current_image_url = None
        
        # Pending timers/reminders (reminders.json); re-armed after the UI is up.
        self.reminders = ReminderRegistry()

        # Memory
        self.brain = Brain()
        threading.Thread(target=self.brain.warm_up, daemon=True).start()
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
            'happy':   [BotStates.HAPPY, BotStates.HEART, BotStates.STARRY_EYED,
                        BotStates.FOOTBALL, BotStates.CHEEKY, BotStates.JAMMING],
            'neutral': [BotStates.IDLE, BotStates.DETECTIVE, BotStates.SIR_MANO,
                        BotStates.BEE, BotStates.BORED, BotStates.CURIOUS,
                        BotStates.DAYDREAM, BotStates.LADYBUG, BotStates.WORM],
            'sad':     [BotStates.SAD, BotStates.CONFUSED, BotStates.BORED, BotStates.SHHH],
            'sleepy':  [BotStates.SLEEPY, BotStates.DAYDREAM, BotStates.LOW_BATTERY],
            'jamming': [BotStates.JAMMING, BotStates.HAPPY, BotStates.CHEEKY],
        }
        # Screensaver expression state (randomised, not time-modulo)
        self.screensaver_expr        = BotStates.IDLE
        self.screensaver_expr_until  = 0   # epoch when to pick next expression
        self.screensaver_expr_dur    = 10  # seconds (refreshed randomly each pick)


        # Init UI
        self.background_label = tk.Label(master, bg='black')
        self.background_label.place(x=0, y=0, width=self.BG_WIDTH, height=self.BG_HEIGHT)
        
        # BMO-themed captions: dark green text on translucent lime-green background
        self.status_label = tk.Label(
            master,
            text="Initializing...",
            font=('Courier New', 14, 'bold'),
            fg='#1a5c2a',       # Dark forest green text
            bg='#C9E4C3',       # BMO's face green
            padx=12, pady=4,
            relief='flat',
            highlightthickness=0
        )
        self.status_label.place(relx=0.5, rely=STATUS_RELY, anchor=tk.S)

        self.is_muted = False
        self.mute_label = tk.Label(
            master,
            text="🔇 Muted",
            font=('Courier New', 16, 'bold'),
            fg='#f44336',
            bg='#C9E4C3',       # BMO's face green
            padx=10, pady=5,
            relief='flat',
            highlightthickness=0
        )

        # Load persisted volume (falls back to config default)
        try:
            import json as _j
            with open("settings.json") as _f:
                _saved = _j.load(_f)
            self.volume = float(_saved.get("volume", VOLUME))
        except Exception:
            _saved, self.volume = {}, VOLUME
        # One volume control: when the speaker has a hardware mixer, BMO's
        # slider drives it (the same control as the desktop slider) instead
        # of scaling audio in software on top of it.  See core/volume.py.
        self.hw_volume = HardwareVolume.for_device(ALSA_DEVICE)
        self._hw_vol_pending = None
        self._hw_vol_lock = threading.Lock()
        if self.hw_volume is not None:
            if _saved.get("volume_control") != "hardware":
                # First run with hardware volume: carry the old BMO level over
                # once, so BMO isn't suddenly louder than it was.
                self.hw_volume.set(self.volume)
                update_settings({"volume_control": "hardware"})
            else:
                hw = self.hw_volume.get()
                self.volume = hw if hw is not None else self.volume
            print(f"[VOLUME] Using {self.hw_volume.card} '{self.hw_volume.control}' mixer, at {self.volume:.0%}")
        self._volume_overlay = None
        self._volume_hide_job = None

        # Use a master click handler for hot corners and muting
        master.bind('<Button-1>', self.handle_click)

        self.animations = {}
        self.current_frame = 0
        self.mouth_ema = 0.0 # Asymmetric envelope of mouth_open (fast attack, slow release)
        self.mouth_viseme_jitter = 0 # Offset for different "phoneme" looks
        # Viseme palette state. speaking_frame indexes the 6-shape palette
        # produced by generate_faces.gen_speaking(): 0=closed, 1=tiny,
        # 2=small, 3=oh, 4=wide, 5=ah. The vowel-swap timer drives 3-way
        # alternation between OH/WIDE/AH while sustained vowel energy is
        # detected — keeps the mouth visibly articulating instead of locking
        # onto one open shape.
        self.speaking_frame = 0
        self.speaking_frame_hold_until = 0.0
        self._vowel_swap_until = 0.0
        # Lip-sync envelope schedule. The TTS reader thread pumps audio into
        # aplay's 500 ms buffer as fast as it can (to stay ahead of CPU/NPU
        # spikes), which means it races several seconds AHEAD of the audio the
        # user actually hears. If it drove self.mouth_open directly, the mouth
        # would finish "speaking" long before playback and then sit closed —
        # the exact bug. Instead the reader timestamps each chunk's envelope by
        # its playback offset here, and update_animation replays the value for
        # the audio that's playing *right now*, keeping the mouth in sync.
        self._lip_lock = threading.Lock()
        self._lip_sched = []      # list of (play_offset_seconds, mouth_open)
        self._lip_start = None    # wall-clock time the first audio chunk was queued
        self._lip_end = None      # play_offset of the most recent chunk

        # Live face rig. Schedule entries become (play_offset, mouth_open, speech)
        # where speech is the rig's lip-sync result; index 1 stays the legacy
        # loudness so the PNG path keeps working unchanged.
        self.face_view = None
        self._lip_sync = None
        self._rig_state = None
        self._rig_speech = FACE_SILENT if FACE_RIG_OK else None
        self._rig_frames = 0
        self._talk_mood = "idle"
        if USE_FACE_RIG:
            try:
                self.face_view = FaceView(self.background_label, size=(self.BG_WIDTH, self.BG_HEIGHT))
                self._lip_sync = LipSync(22050)
                print("[FACE] Live face rig enabled")
            except Exception as e:
                print(f"[FACE] Rig failed to start, using PNG faces: {e}")
                self.face_view = None
        # Morning briefing: the sun icon is drawn over the rig's frames while
        # one is ready; BriefingView takes over the screen while it plays.
        self.icon_overlay = briefing_ui.IconOverlay()
        self._icon_label = None          # PNG-face fallback for the icon
        if self.face_view is not None:
            self.face_view.overlay = self._draw_overlays
        self.briefing_view = None
        self._briefing_photo = None
        self._briefing_skip = threading.Event()
        self._briefing_stop = threading.Event()
        self._briefing_mood = "happy"
        self._briefing_frame_ms = []     # draw + paste cost per frame, logged after each play
        self.briefing_scheduler = BriefingScheduler(
            settings_fn=self._briefing_settings,
            prepare_fn=lambda now, s: prepare_briefing(now, s, self.reminders,
                                                       fun_fact=self._briefing_fun_fact),
            is_idle=self._briefing_can_show,
            chime_fn=lambda: self.play_sound("briefing_sounds"),
            on_icon=self._on_briefing_icon)
        # "Good morning" only plays a briefing that's waiting; Brain asks here.
        self.brain.briefing_ready = self.briefing_scheduler.is_ready_unplayed
        self.brain.reminders = self.reminders

        self.load_animations()
        self.load_sounds()
        self.update_animation()

        # Start Main Thread
        threading.Thread(target=self.main_loop, daemon=True).start()
        self._rearm_reminders()
        threading.Thread(target=self._briefing_loop, daemon=True).start()

        # Start Screensaver Audio Thread
        self.last_screensaver_audio_time = time.time()
        threading.Thread(target=self.screensaver_audio_loop, daemon=True).start()

        # NOTE: do NOT pre-warm the VLM here. The Hailo NPU is single-device
        # and exclusive; warming the VLM at startup grabs /dev/hailo0 before
        # hailo-ollama can load the LLM HEF, leaving the LLM service crashing
        # in a SEGV loop. Pay the ~3 s VLM init the first time the user asks
        # for vision instead.

    def exit_fullscreen(self, event=None):
        # Signal all background threads to wind down before tearing the UI.
        self.stop_event.set()
        # Best-effort kill of any running audio so we don't leave aplay holding the device.
        try:
            self._kill_tts_pipeline()
        except Exception:
            pass
        try:
            for proc in list(self.active_sounds):
                try: proc.terminate()
                except Exception: pass
        except Exception:
            pass
        # Flush any pending memory.json throttled writes
        try:
            self.brain.save_history(force=True)
        except Exception:
            pass
        self.master.quit()

    def set_state(self, state, msg=""):
        if state != self.current_state:
            self.current_state = state
            self.current_frame = 0
            self.last_state_change = time.time()
            print(f"[STATE] {state.upper()}: {msg}")
        if state in TALK_MOODS:
            self._talk_mood = TALK_MOODS[state]
        elif state in (BotStates.IDLE, BotStates.LISTENING):
            self._talk_mood = "idle"
        if msg:
            self.master.after(0, lambda: self.status_label.config(text=msg))

    # ── Busy-lock helpers ────────────────────────────────────────────────────
    def _try_claim_busy(self) -> bool:
        """Atomic check-and-set. Returns True iff this thread now owns the busy state."""
        if self._busy_lock.acquire(blocking=False):
            self.is_busy = True
            self.last_user_interaction = time.time()
            return True
        return False

    def _release_busy(self):
        """Release the busy lock. Safe to call from any thread; idempotent."""
        self.is_busy = False
        try:
            self._busy_lock.release()
        except RuntimeError:
            pass  # already unlocked

    def _wait_until_idle(self, states, poll_s: float = 0.5, timeout_s: float = 60.0) -> bool:
        """Block until current_state is OUT of `states` or stop_event fires.
        Returns True if we exited because we're no longer in those states,
        False on shutdown / timeout.  Bounded so worker threads can't hang."""
        end = time.time() + timeout_s
        while self.current_state in states:
            if self.stop_event.is_set() or time.time() >= end:
                return False
            time.sleep(poll_s)
        return True

    # ── Thinking-sound controller ────────────────────────────────────────────
    def _thinking_sound_start(self):
        """Start the thinking-sound loop. Idempotent — if a previous loop is
        still alive, no second thread is spawned (eliminates the prior race
        where post-STT and post-photo each spawned their own loop)."""
        with self._thinking_lock:
            if self.is_thinking_sound_playing:
                return  # Already running
            self.is_thinking_sound_playing = True
            t = threading.Thread(target=self._thinking_sound_loop, daemon=True)
            self._thinking_thread = t
            t.start()

    def _thinking_sound_stop(self):
        """Signal the loop to exit; terminate the current sound process."""
        self.is_thinking_sound_playing = False
        proc = self.thinking_audio_process
        self.thinking_audio_process = None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _thinking_sound_loop(self):
        try:
            ack_proc = self.play_sound("ack_sounds")
            if ack_proc:
                ack_proc.wait()
            while self.current_state == BotStates.THINKING and self.is_thinking_sound_playing:
                self.thinking_audio_process = self.play_sound("thinking_sounds")
                if self.thinking_audio_process:
                    self.thinking_audio_process.wait()
                # Randomized 0.4–1.2 s gap between repeats — feels alive
                gap_total = random.uniform(0.4, 1.2)
                elapsed = 0.0
                while elapsed < gap_total:
                    if self.current_state != BotStates.THINKING or not self.is_thinking_sound_playing:
                        break
                    time.sleep(0.1)
                    elapsed += 0.1
        finally:
            self.thinking_audio_process = None

    def handle_click(self, event):
        """Map screen clicks to hot corners, mouth-tap mute, or tap-to-speak."""
        now = time.time()

        # Triple-tap anywhere within 0.8 s → clean exit (useful without keyboard)
        self._triple_tap_times.append(now)
        self._triple_tap_times = [t for t in self._triple_tap_times if now - t <= 0.8]
        if len(self._triple_tap_times) >= 3:
            print("[TRIPLE-TAP] Exiting BMO...")
            self.exit_fullscreen()
            return

        # Any click counts as a user interaction — keeps the watchdog honest
        # regardless of which branch handles the tap.
        self.last_user_interaction = now

        if self.current_state == BotStates.DISPLAY_IMAGE:
            self.set_state(BotStates.IDLE, "Tap to speak")
            return

        x, y = event.x, event.y
        win_w = self.master.winfo_width()
        win_h = self.master.winfo_height()
        corner_w = win_w // 4
        corner_h = win_h // 4

        # Morning briefing playing: these come before every other zone, or the
        # mouth-tap mute zone would catch taps on the card.
        if self.current_state == BotStates.BRIEFING:
            if int(win_w * 0.30) <= x <= int(win_w * 0.70) and y < int(win_h * 0.15):
                print(f"[CLICK] Top-Centre: Volume overlay ({x},{y})")
                self.master.after(0, self._show_volume_overlay)
            elif self.face_view is not None and x < win_w / 3:
                print(f"[CLICK] Briefing: stop ({x},{y})")
                self._briefing_stop.set()
            else:
                print(f"[CLICK] Briefing: skip ({x},{y})")
                self._briefing_skip.set()
            return

        # The sun icon: checked before the top-right pondering corner and
        # before a screensaver tap wakes BMO to listen.
        if self.icon_overlay.visible and briefing_ui.icon_hit(x, y, win_w, win_h):
            print(f"[CLICK] Briefing icon ({x},{y})")
            self.start_briefing_from_tap()
            return

        # Mouth zone: centre-lower portion of the face (where BMO's mouth lives)
        mouth_x0 = int(win_w * 0.27)
        mouth_x1 = int(win_w * 0.73)
        mouth_y0 = int(win_h * 0.55)
        mouth_y1 = int(win_h * 0.80)
        in_mouth = mouth_x0 <= x <= mouth_x1 and mouth_y0 <= y <= mouth_y1

        # Top-centre volume zone: middle 40% of width, top 15% of height
        vol_x0 = int(win_w * 0.30)
        vol_x1 = int(win_w * 0.70)
        in_vol = vol_x0 <= x <= vol_x1 and y < int(win_h * 0.15)

        if in_vol:
            print(f"[CLICK] Top-Centre: Volume overlay ({x},{y})")
            self.master.after(0, self._show_volume_overlay)
        elif x < corner_w and y < corner_h:
            print(f"[CLICK] Top-Left: Generate Image ({x},{y})")
            self.trigger_generate_image()
        elif x > win_w - corner_w and y < corner_h:
            print(f"[CLICK] Top-Right: Random Pondering ({x},{y})")
            self.trigger_random_thought()
        elif x > win_w - corner_w and y > win_h - corner_h:
            print(f"[CLICK] Bottom-Right: Play Music ({x},{y})")
            self.trigger_music()
        elif x < corner_w and y > win_h - corner_h:
            print(f"[CLICK] Bottom-Left: Toggle Mute ({x},{y})")
            self.mute_bmo()
        elif in_mouth:
            # Tap BMO's mouth to toggle mute — works in any state
            print(f"[CLICK] Mouth: Toggle Mute ({x},{y})")
            self.mute_bmo()
        elif self.current_state in [BotStates.IDLE, BotStates.SCREENSAVER]:
            print(f"[CLICK] Body: Manual Wake ({x},{y})")
            self.manual_wake_event.set()
        else:
            print(f"[CLICK] Ignored in state {self.current_state} ({x},{y})")

    # ── Volume overlay ────────────────────────────────────────────────────────
    # Custom Canvas-based slider. tk.Scale's default thumb is ~15 px wide,
    # which is fiddly to grab on a finger-driven 800×480 panel; this draws
    # a chunky rounded track + 60 px knob + big readout in BMO's mouth
    # palette. Tap anywhere on the track to jump; drag the knob (or
    # anywhere on the track) to fine-tune.

    # BMO palette (matches the new viseme assets)
    _VOL_BG       = '#C9E4C3'   # body green
    _VOL_FILL     = '#396337'   # mouth dark green
    _VOL_TROUGH   = '#A2B36A'   # tongue light green
    _VOL_OUTLINE  = 'black'
    _VOL_TEXT     = '#1a3d18'   # nearly-black for readout
    _VOL_MUTE_FG  = '#8a1a1a'   # muted-red for the muted-state cues

    def _create_volume_overlay(self):
        win_w = self.master.winfo_width() or self.BG_WIDTH

        OW = min(720, int(win_w * 0.92))
        OH = 120
        PAD = 14
        ICON_W = 64
        PCT_W = 90
        TRACK_X0 = PAD + ICON_W
        TRACK_X1 = OW - PAD - PCT_W
        TRACK_H  = 32
        TRACK_Y  = (OH - TRACK_H) // 2
        KNOB_R   = 30

        cv = tk.Canvas(self.master, width=OW, height=OH,
                       bg=self._VOL_BG, highlightthickness=0, bd=0)

        # Outer pill: BMO body green with a thick dark-green outline so the
        # overlay reads as a unified card sitting on top of BMO's face.
        self._draw_rounded_rect(cv, 3, 3, OW-3, OH-3, r=22,
                                fill=self._VOL_BG, outline=self._VOL_FILL,
                                width=4)

        # Speaker glyph (left) — switches to 🔇 when muted (volume == 0).
        icon_id = cv.create_text(PAD + ICON_W//2, OH//2, text='🔊',
                                 font=('DejaVu Sans', 30),
                                 fill=self._VOL_TEXT, anchor='center')

        # Track background (the unfilled portion shows through this)
        self._draw_rounded_rect(cv, TRACK_X0, TRACK_Y,
                                TRACK_X1, TRACK_Y + TRACK_H, r=TRACK_H//2,
                                fill=self._VOL_TROUGH,
                                outline=self._VOL_OUTLINE, width=3)

        # Track fill — placeholder, redrawn on every level change
        fill_id = self._draw_rounded_rect(
            cv, TRACK_X0, TRACK_Y, TRACK_X0 + 1, TRACK_Y + TRACK_H,
            r=TRACK_H//2, fill=self._VOL_FILL, outline='',
        )

        # Knob — a fat circle with a black outline, like BMO's eyes
        cy = TRACK_Y + TRACK_H // 2
        knob_id = cv.create_oval(
            TRACK_X0 - KNOB_R, cy - KNOB_R,
            TRACK_X0 + KNOB_R, cy + KNOB_R,
            fill=self._VOL_FILL, outline=self._VOL_OUTLINE, width=4,
        )

        # Percentage readout (right)
        pct_id = cv.create_text(
            OW - PAD - PCT_W//2, OH//2, text='100%',
            font=('Courier New', 24, 'bold'),
            fill=self._VOL_TEXT, anchor='center',
        )

        cv.place(relx=0.5, rely=0.02, anchor=tk.N)

        # Stash geometry/IDs for the live update path
        self._vol_canvas    = cv
        self._vol_track_x0  = TRACK_X0
        self._vol_track_x1  = TRACK_X1
        self._vol_track_y   = TRACK_Y
        self._vol_track_h   = TRACK_H
        self._vol_knob_r    = KNOB_R
        self._vol_knob_id   = knob_id
        self._vol_fill_id   = fill_id
        self._vol_pct_id    = pct_id
        self._vol_icon_id   = icon_id

        # Tap = jump; drag = follow finger; release = persist to disk.
        cv.bind('<ButtonPress-1>',   self._on_vol_press)
        cv.bind('<B1-Motion>',       self._on_vol_drag)
        cv.bind('<ButtonRelease-1>', self._on_vol_release)

        self._volume_overlay = cv
        self._update_volume_visual()

    def _draw_rounded_rect(self, cv, x1, y1, x2, y2, r=10, **kwargs):
        """Draw an approximated rounded rectangle on cv. Returns the polygon
        id so callers can delete/re-create on update. Uses smooth=True on a
        12-point polygon, which is good enough at the chunky sizes we use
        and avoids juggling 6 canvas items per shape."""
        pts = [
            x1+r, y1,   x2-r, y1,   x2, y1,
            x2,   y1+r, x2,   y2-r, x2, y2,
            x2-r, y2,   x1+r, y2,   x1, y2,
            x1,   y2-r, x1,   y1+r, x1, y1,
        ]
        return cv.create_polygon(pts, smooth=True, **kwargs)

    def _software_gain(self) -> float:
        """Gain BMO applies to its own audio: 1.0 when the hardware mixer
        does the work, else the slider level (speakers without a mixer)."""
        if getattr(self, "hw_volume", None) is not None:
            return 1.0
        return getattr(self, "volume", VOLUME)

    def _apply_hw_volume(self):
        """Push self.volume to the mixer off the Tk thread, coalescing a drag's
        many events into whatever the latest level is."""
        if getattr(self, "hw_volume", None) is None:
            return
        with self._hw_vol_lock:
            start = self._hw_vol_pending is None
            self._hw_vol_pending = self.volume
        if not start:
            return

        def worker():
            while True:
                with self._hw_vol_lock:
                    level = self._hw_vol_pending
                self.hw_volume.set(level)
                with self._hw_vol_lock:
                    if self._hw_vol_pending == level:
                        self._hw_vol_pending = None
                        return
        threading.Thread(target=worker, daemon=True).start()

    def _show_volume_overlay(self):
        # The desktop slider moves the same mixer: show where it is now.
        if getattr(self, "hw_volume", None) is not None and self._hw_vol_pending is None:
            hw = self.hw_volume.get()
            if hw is not None:
                self.volume = hw
        if self._volume_overlay is None:
            self._create_volume_overlay()
        else:
            self._update_volume_visual()
            self._volume_overlay.place(relx=0.5, rely=0.02, anchor=tk.N)
            self._volume_overlay.tkraise()
        self._reset_volume_hide()

    def _hide_volume_overlay(self):
        if self._volume_overlay:
            self._volume_overlay.place_forget()
        self._volume_hide_job = None

    def _on_vol_press(self, event):
        self._set_volume_from_x(event.x)
        self._reset_volume_hide()

    def _on_vol_drag(self, event):
        self._set_volume_from_x(event.x)
        self._reset_volume_hide()

    def _on_vol_release(self, event):
        self._reset_volume_hide()
        # Debounce disk writes — drags fire many press/drag events but only
        # a single release. Schedule the write a beat later so a quick
        # repeat tap doesn't write twice.
        if getattr(self, '_volume_save_job', None):
            self.master.after_cancel(self._volume_save_job)
        self._volume_save_job = self.master.after(400, self._persist_volume)

    def _set_volume_from_x(self, x):
        x0, x1 = self._vol_track_x0, self._vol_track_x1
        x = max(x0, min(x1, x))
        self.volume = (x - x0) / (x1 - x0)
        self._apply_hw_volume()
        self._update_volume_visual()

    def _update_volume_visual(self):
        cv = self._vol_canvas
        x0, x1 = self._vol_track_x0, self._vol_track_x1
        ty, th = self._vol_track_y, self._vol_track_h
        r  = self._vol_knob_r
        cy = ty + th // 2
        x  = x0 + self.volume * (x1 - x0)

        # When the slider sits at 0 the speaker's mixer is switched off (or,
        # without a mixer, every audio path multiplies PCM by 0) → silent. That's a hard mute, so make it visually
        # unmistakable: 🔇 icon, red knob, "MUTED" readout. Otherwise an
        # accidental drag-to-zero looks identical to a stuck app.
        muted = self.volume <= 0.001
        knob_fill = self._VOL_MUTE_FG if muted else self._VOL_FILL
        text_fg   = self._VOL_MUTE_FG if muted else self._VOL_TEXT

        # Knob — recolour as well as reposition
        cv.coords(self._vol_knob_id, x - r, cy - r, x + r, cy + r)
        cv.itemconfig(self._vol_knob_id, fill=knob_fill)

        # Fill — easier to recreate than to mutate a smoothed polygon
        cv.delete(self._vol_fill_id)
        # Draw at least a rounded "cap" so the fill never becomes a sliver
        # that looks broken at the very-low end.
        x_end = max(x, x0 + th // 2)
        self._vol_fill_id = self._draw_rounded_rect(
            cv, x0, ty, x_end, ty + th, r=th // 2,
            fill=knob_fill, outline='',
        )
        cv.tag_raise(self._vol_knob_id)

        cv.itemconfig(self._vol_icon_id,
                      text='🔇' if muted else '🔊',
                      fill=text_fg)
        cv.itemconfig(self._vol_pct_id,
                      text='MUTED' if muted else f"{int(round(self.volume * 100))}%",
                      fill=text_fg,
                      font=('Courier New', 18, 'bold') if muted
                           else ('Courier New', 24, 'bold'))

    def _reset_volume_hide(self):
        if self._volume_hide_job:
            self.master.after_cancel(self._volume_hide_job)
        self._volume_hide_job = self.master.after(6000, self._hide_volume_overlay)

    def _persist_volume(self):
        self._volume_save_job = None
        try:
            # Merge, don't overwrite: settings.json also holds the briefing block.
            update_settings({"volume": self.volume})
        except Exception:
            pass

    def mute_bmo(self, event=None):
        """Toggle audio mute. Heavy cleanup is dispatched to a worker so the
        Tk thread (and the rest of the UI) never blocks on proc.wait/join."""
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.mute_label.place(relx=0.95, rely=0.05, anchor=tk.NE)

            old_state = self.current_state
            self.set_state(BotStates.SHHH, "Muted")

            # Snapshot processes to terminate, then clear lists immediately so
            # the worker can do its slow work without further race exposure.
            sounds_to_kill = self.active_sounds[:]
            self.active_sounds = []
            self.is_thinking_sound_playing = False
            thinking_proc = self.thinking_audio_process
            self.thinking_audio_process = None

            def _mute_cleanup_worker():
                for proc in sounds_to_kill:
                    try:
                        proc.terminate()
                        print(f"[MUTE] Terminated active sound process: {proc.pid}")
                    except Exception:
                        pass
                if thinking_proc is not None:
                    try:
                        thinking_proc.terminate()
                    except Exception:
                        pass
                self._kill_tts_pipeline()
            threading.Thread(target=_mute_cleanup_worker, daemon=True).start()

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
                    self.set_state(BotStates.IDLE, "Tap to speak")
            self.master.after(2000, revert_state)

    # --- ANIMATION & SOUND ENGINE ---
    def load_sounds(self):
        self.sounds = {
            "greeting_sounds": [],
            "ack_sounds": [],
            "thinking_sounds": [],
            "briefing_sounds": [],  # ready chime; not lip-synced (see play_sound)
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

            # Speakers without a hardware mixer: play a copy at the slider level.
            play_path = scaled_wav(sound_file, self._software_gain())
            proc = subprocess.Popen(['aplay', '-D', ALSA_DEVICE, '-q', '--buffer-time=500000', play_path])
            self.active_sounds.append(proc)
            
            # Start mouth animation for this sound
            if self.face_view is not None and category in ("greeting_sounds", "thinking_sounds", "ack_sounds"):
                self._schedule_wav_lipsync(sound_file)
            elif category in ["greeting_sounds", "thinking_sounds"]:
                threading.Thread(target=animate_mouth_simple, args=(proc,), daemon=True).start()
            elif category == "music":
                self.set_state(BotStates.JAMMING, "Jamming!")

            # Cleanup thread to remove finished processes (guard against zombies)
            def cleanup():
                try:
                    proc.wait(timeout=600)  # Music can be long; cap at 10 min
                except subprocess.TimeoutExpired:
                    print(f"[SOUND] Cleanup timeout — terminating stuck proc {proc.pid}")
                    try: proc.terminate()
                    except Exception: pass
                if proc in self.active_sounds:
                    self.active_sounds.remove(proc)
                if play_path != sound_file:
                    try: os.remove(play_path)
                    except OSError: pass
                if category == "music" and self.current_state == BotStates.JAMMING:
                    self.set_state(BotStates.IDLE, "Tap to speak")
            threading.Thread(target=cleanup, daemon=True).start()
            return proc
        except Exception as e:
            print(f"Error playing sound {sound_file}: {e}")
            return None

    def _schedule_wav_lipsync(self, path):
        """Lip-sync a pre-recorded clip that aplay has just started playing."""
        try:
            items, duration = analyse_wav(path)
        except Exception as e:
            print(f"[FACE] Could not analyse {path}: {e}")
            return
        with self._lip_lock:
            self._lip_sched = items
            self._lip_start = time.time() + WAV_LIPSYNC_DELAY
            self._lip_end = duration

    def _lip_speech(self, now):
        """Rig lip-sync state for the audio playing right now."""
        if self._lip_start is None:
            self._rig_speech = FACE_SILENT
            return self._rig_speech
        elapsed = now - self._lip_start
        latest, onset = None, False
        with self._lip_lock:
            sched = self._lip_sched
            consumed = 0
            while consumed < len(sched) and sched[consumed][0] <= elapsed:
                entry = sched[consumed]
                if len(entry) > 2 and entry[2] is not None:
                    latest = entry[2]
                    onset = onset or latest["onset"]
                consumed += 1
            if consumed:
                del sched[:consumed]
            lip_end = self._lip_end
        if latest is not None:
            self._rig_speech = {**latest, "onset": onset}
        elif lip_end is not None and elapsed > lip_end + 0.15:
            self._rig_speech = FACE_SILENT
        else:
            self._rig_speech = {**self._rig_speech, "onset": False}
        return self._rig_speech

    def _update_face_rig(self, display_state, now):
        """Advance and draw the live rig. Returns the delay (ms) until the next tick."""
        fv = self.face_view
        if display_state == BotStates.SPEAKING:
            want = self._talk_mood
        elif display_state == BotStates.BRIEFING:
            want = self._briefing_mood
        else:
            want = RIG_EXPRESSIONS[display_state]
        if display_state != self._rig_state:
            if self._rig_state == BotStates.WARMUP:
                fv.rig.play_intro()  # eyes shut, then open with a stretch
            fv.rig.set_expression(want)
            self._rig_state = display_state
        elif fv.rig.expr["name"] != want:
            fv.rig.set_expression(want)  # talk mood changed mid-sentence
        speech = self._lip_speech(now)
        if display_state == BotStates.BRIEFING and self.briefing_view is not None:
            t0 = time.perf_counter()
            fv.photo.paste(self.briefing_view.tick(speech, now))
            self._briefing_frame_ms.append((time.perf_counter() - t0) * 1000)
        else:
            fv.tick(speech, now)
        # Re-point the label if a PNG frame or photo was shown in between.
        if self.background_label.cget("image") != str(fv.photo):
            fv.attach()
        self._last_render_key = None  # make the PNG path redraw if we hand back
        self._rig_frames += 1
        if self._rig_frames == 300:
            print(f"[FACE] Rig costs ~{fv.render_ms:.1f} ms/frame")
        busy = speech["active"] or display_state in (BotStates.SPEAKING, BotStates.LISTENING, BotStates.BRIEFING)
        return int(1000 / (FACE_FPS_ACTIVE if busy else FACE_FPS_CALM))

    # States needed before the GUI can be useful — loaded synchronously.
    CORE_ANIMATION_STATES = (
        BotStates.IDLE, BotStates.LISTENING, BotStates.SPEAKING,
        BotStates.THINKING, BotStates.WARMUP, BotStates.ERROR,
        BotStates.CAPTURING,
    )

    def _load_state_frames(self, state):
        path = os.path.join("faces", state)
        if not os.path.isdir(path):
            return []
        files = sorted(f for f in os.listdir(path) if f.lower().endswith('.png'))
        frames = []
        for f in files:
            try:
                img = Image.open(os.path.join(path, f))
                if img.size != (self.BG_WIDTH, self.BG_HEIGHT):
                    img = img.resize((self.BG_WIDTH, self.BG_HEIGHT), Image.Resampling.LANCZOS)
                frames.append(ImageTk.PhotoImage(img))
            except Exception as e:
                print(f"Error loading frame {f}: {e}")
        return frames

    def load_animations(self):
        """Load core PNG frames synchronously; defer expressions to background."""
        self.animations = {}
        if self.face_view is not None:
            # The rig draws every face; PNGs load later only if it fails.
            self.tk_img = None
            print("[FACE] Rig draws every face; PNG frames not preloaded")
            return
        for state in self.CORE_ANIMATION_STATES:
            frames = self._load_state_frames(state)
            if frames:
                self.animations[state] = frames

        all_states = [d for d in os.listdir("faces") if os.path.isdir(os.path.join("faces", d))]
        self._pending_states = [s for s in all_states if s not in self.animations]
        print(f"Loaded core animations: {list(self.animations.keys())}; "
              f"deferring {len(self._pending_states)} expression states")
        self.tk_img = None
        # Kick off lazy load on the Tk event loop after first render.
        self.master.after(150, self._load_next_pending_state)

    def _load_next_pending_state(self):
        """Load one deferred animation per Tk tick to keep UI responsive."""
        if not getattr(self, '_pending_states', None):
            return
        state = self._pending_states.pop(0)
        frames = self._load_state_frames(state)
        if frames:
            self.animations[state] = frames
        # Yield to the event loop between dirs so the UI stays smooth.
        self.master.after(20, self._load_next_pending_state)

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

        # If in screensaver, pick expression randomly; change every 8-18 s
        display_state = self.current_state
        if self.current_state == BotStates.SCREENSAVER:
            if now >= self.screensaver_expr_until:
                mood_pool = self.expressions_map[self.current_mood]
                # 30 % chance to pull one extra from a random other mood for variety
                if random.random() < 0.30:
                    other = random.choice([m for m in self.expressions_map
                                           if m != self.current_mood])
                    candidates = mood_pool + self.expressions_map[other]
                else:
                    candidates = mood_pool
                self.screensaver_expr       = random.choice(candidates)
                self.screensaver_expr_dur   = random.uniform(8, 18)
                self.screensaver_expr_until = now + self.screensaver_expr_dur
            display_state = self.screensaver_expr

        # Hide text status label during screensaver and the briefing (cards say it all)
        if self.current_state in (BotStates.SCREENSAVER, BotStates.BRIEFING):
            if self.status_label.winfo_ismapped(): self.status_label.place_forget()
        else:
            if not self.status_label.winfo_ismapped():
                self.status_label.place(relx=0.5, rely=STATUS_RELY, anchor=tk.S)

        # Live face rig for the states it covers; everything else stays on PNGs.
        if self.face_view is not None and display_state in RIG_EXPRESSIONS:
            try:
                delay = self._update_face_rig(display_state, now)
                self.master.after(delay, self.update_animation)
                return
            except Exception as e:
                print(f"[FACE] Rig error, falling back to PNG faces: {e}")
                traceback.print_exc()
                self.face_view = None
                self._rig_state = None
                self._last_render_key = None
                if not self.animations:
                    try:
                        self.load_animations()
                    except Exception as load_err:
                        print(f"[FACE] Could not load PNG faces either: {load_err}")

        # PNG faces: the briefing draws its cards full width, without a face.
        if display_state == BotStates.BRIEFING and self.briefing_view is not None:
            img = self.briefing_view.compose(None, now)
            if self._briefing_photo is None:
                self._briefing_photo = ImageTk.PhotoImage(img)
            else:
                self._briefing_photo.paste(img)
            self.background_label.config(image=self._briefing_photo)
            self._last_render_key = None
            self.master.after(40, self.update_animation)
            return
        self._sync_icon_label()

        # Animation Loop
        frames = self.animations.get(display_state, self.animations.get(BotStates.IDLE, []))
        if frames:
            if display_state == BotStates.SPEAKING:
                # Drive a 6-shape viseme palette from the audio envelope.
                # Shapes come from Rhubarb-animated frames (24 fps, artist-drawn):
                # 0=CLOSED (flat line, B/P/M), 1=TINY (small curve, rest/H),
                # 2=SMALL (slightly open, medium vowels),
                # 3=OH (wide teeth smile, EE/open vowel),
                # 4=WIDE (round oval, OOH/W),
                # 5=AH (very wide open, emphatic vowels).
                # OH/WIDE/AH rotate on a timer so sustained vowels get visual
                # variety instead of locking onto one shape.

                # Pull the loudness of the audio that's playing RIGHT NOW from
                # the schedule the reader thread filled. `elapsed` is how long
                # since the first chunk was queued (~playback start); we advance
                # to the latest chunk whose playback offset has arrived and drop
                # what's already played. Past the final chunk, close the mouth.
                if self._lip_start is not None:
                    elapsed = now - self._lip_start
                    with self._lip_lock:
                        sched = self._lip_sched
                        val = None
                        consumed = 0
                        while consumed < len(sched) and sched[consumed][0] <= elapsed:
                            val = sched[consumed][1]
                            consumed += 1
                        if consumed:
                            del sched[:consumed]
                        lip_end = self._lip_end
                    if val is not None:
                        self.mouth_open = val
                    elif lip_end is not None and elapsed > lip_end + 0.15:
                        self.mouth_open = 0

                # Asymmetric envelope: vowel onsets pop the mouth open in one
                # tick (fast attack), then it relaxes over ~150 ms (slow
                # release). A symmetric EMA smooths attacks too much and
                # makes the mouth feel laggy.
                if self.mouth_open > self.mouth_ema:
                    self.mouth_ema = self.mouth_ema * 0.30 + self.mouth_open * 0.70
                else:
                    self.mouth_ema = self.mouth_ema * 0.85 + self.mouth_open * 0.15

                cur = self.speaking_frame
                lvl = self.mouth_ema

                if cur >= 3:
                    # In the open-vowel zone. Either drop out (energy fell)
                    # or rotate to a different open shape on the swap timer.
                    if lvl < 22:
                        target = 2
                    elif now >= self._vowel_swap_until:
                        # 3-way rotation among OH(3) / WIDE(4) / AH(5).
                        # random.choice keeps the variety unpredictable so
                        # sustained vowels never settle into a 2-step pattern.
                        choices = [i for i in (3, 4, 5) if i != cur]
                        target = random.choice(choices)
                        self._vowel_swap_until = now + random.uniform(0.12, 0.22)
                    else:
                        target = cur
                else:
                    # Closed/tiny/small zone — pick by energy with hysteresis.
                    if   lvl < 4:   target = 0
                    elif lvl < 13:  target = 1
                    elif lvl < 26:  target = 2
                    else:
                        target = 3   # enter vowel zone via OH
                        # Hold OH briefly on entry so the rotation above
                        # doesn't immediately swap on the next tick.
                        self._vowel_swap_until = now + random.uniform(0.12, 0.22)

                # Coarticulation gate: when CLOSING, step through intermediate
                # shapes one at a time so the mouth visibly relaxes instead of
                # popping shut. Opens can still jump freely so vowel onsets
                # feel snappy. The OH↔WIDE swap is treated as same-zone.
                if target < cur - 1 and not (cur >= 3 and target >= 3):
                    target = cur - 1

                # Min hold so a single audio blip doesn't change the shape
                # every 40 ms tick. Faster on opens, slower on closes — the
                # mouth should look like it's doing something deliberate.
                if target != cur and now >= self.speaking_frame_hold_until:
                    self.speaking_frame = target
                    self.speaking_frame_hold_until = now + (
                        0.06 if target > cur else 0.10
                    )
                self.current_frame = self.speaking_frame
            else:
                self.current_frame = (self.current_frame + 1) % len(frames)

            # Skip the Tk reconfigure when nothing actually changed — avoids
            # syscalls when the speaking EMA holds the same frame for a while.
            new_key = (display_state, self.current_frame)
            if getattr(self, '_last_render_key', None) != new_key:
                self.tk_img = frames[self.current_frame]
                self.background_label.config(image=self.tk_img)
                self._last_render_key = new_key

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
        
        retry_count = 0
        near_miss_at = 0.0
        while not self.stop_event.is_set():
            try:
                # Callback capture into a queue, with a generous ALSA buffer.
                # A blocking read() with the default 160 ms buffer overflowed about
                # once a second (the Tk thread drawing the face holds the GIL), and
                # each overflow restarts the stream: audio was dropped so the wake
                # word arrived in fragments, and occasionally the C-Media mic never
                # resumed after a restart, leaving BMO deaf until the next reopen.
                frames_q = queue.Queue(maxsize=64)  # ~5 s of 80 ms chunks

                def _on_audio(indata, frames, time_info, status, q=frames_q):
                    try:
                        q.put_nowait(indata.copy())
                    except queue.Full:
                        pass  # consumer is far behind; dropping beats blocking PortAudio

                with sd.InputStream(samplerate=capture_rate, device=MIC_DEVICE_INDEX, channels=1, dtype='int16',
                                    blocksize=CHUNK * downsample_factor, latency=MIC_LATENCY_S, callback=_on_audio):
                    retry_count = 0 # Reset on success
                    while not self.stop_event.is_set():
                        if self.manual_wake_event.is_set():
                            self.manual_wake_event.clear()
                            print("[EARS] Wake triggered via tap.")
                            return True

                        try:
                            data = frames_q.get(timeout=2.0)
                        except queue.Empty:
                            # No audio for 2 s from a running stream: the mic has
                            # stalled.  Reopen it rather than stay deaf.
                            print("[EARS] Watchdog: no audio from the mic for 2 s. Reopening stream...")
                            break

                        if self.is_busy:
                            continue  # keep draining so audio stays fresh; don't listen

                        # 1. Quick Volume Check (Skip OWW if it's too quiet)
                        # All-zero arrays are valid (quiet room) — don't treat as a mic failure.
                        current_max = np.max(np.abs(data))
                        # Only skip digital near-silence.  At 250 the quieter parts
                        # of a distant "Hey BMO" were dropped (peaks ~600-800 with
                        # the mic's AGC off), so the model heard fragments and
                        # scored 0.1-0.2.  Running predict costs ~9% of one core.
                        if current_max < 50:
                            continue

                        # 2. Down-sample 48 kHz → 16 kHz with an IIR low-pass
                        # before decimating.  Nearest-neighbor slicing aliases
                        # high-frequency speech content into the OWW band and
                        # hurts wake-word reliability in noisy rooms.
                        flat = data.flatten()
                        if downsample_factor >= 2:
                            audio_16k = scipy.signal.decimate(
                                flat, downsample_factor, ftype='iir', zero_phase=False,
                            ).astype(np.int16)
                        else:
                            audio_16k = flat

                        # 3. Predict
                        oww.predict(audio_16k)
                        
                        for key in oww.prediction_buffer.keys():
                            score = oww.prediction_buffer[key][-1]
                            # Near misses explain "it didn't hear me" reports.
                            if 0.1 <= score <= WAKE_WORD_THRESHOLD and time.time() - near_miss_at > 2.0:
                                near_miss_at = time.time()
                                print(f"[EARS] Near miss: {key} {score:.2f} (need > {WAKE_WORD_THRESHOLD}) "
                                      f"state={self.current_state} peak={current_max}")
                            if score > WAKE_WORD_THRESHOLD:
                                print(f"[EARS] Wake Word Detected: {key} (Score: {score:.2f}) "
                                      f"state={self.current_state} peak={current_max}")
                                oww.reset()
                                return True
            except Exception as e:
                retry_count += 1
                print(f"[EARS] Audio Input Error (Attempt {retry_count}): {e}")
                self.set_state(BotStates.ERROR, "Mic Error")
                if retry_count > 5:
                    print("[EARS] Too many mic errors, restarting audio system...")
                    if self.stop_event.wait(timeout=5):
                        return False
                    retry_count = 0
                if self.stop_event.wait(timeout=2):
                    return False
                # Try to go back to IDLE if we were in ERROR
                if self.current_state == BotStates.ERROR:
                    self.set_state(BotStates.IDLE, "Retrying mic...")
        return False

    def record_audio(self):
        """Record until silence with volume-driven lip sync, with retry logic for mic errors."""
        print("Recording...")
        filename = "input.wav"
        frames = []
        total_samples = 0
        MAX_SAMPLES = MIC_SAMPLE_RATE * 15  # 15-second hard cap
        endpoint = EndpointDetector(MIC_SAMPLE_RATE)

        def callback(indata, frames_count, time, status):
            nonlocal total_samples
            rms = endpoint.feed(indata[:, 0])
            # Update mouth_open for real-time lip sync during recording (listening mode)
            if self.current_state == BotStates.LISTENING:
                self.mouth_open = min(60, max(0.0, rms - (endpoint.floor or rms)) / 15)

            frames.append(indata.copy())
            total_samples += indata.shape[0]

        retry_count = 0
        while retry_count < 3:
            try:
                with sd.InputStream(samplerate=MIC_SAMPLE_RATE, device=MIC_DEVICE_INDEX, channels=1, dtype='int16',
                                    latency=MIC_LATENCY_S, callback=callback):
                    last_callback_samples = 0
                    last_callback_at = time.time()
                    while not self.stop_event.is_set():
                        sd.sleep(50)
                        if endpoint.done: break  # user stopped talking (or never started)
                        if total_samples >= MAX_SAMPLES: break  # 15-second hard cap (sample-accurate)
                        # Watchdog: if the callback stops firing mid-recording
                        # (USB unplug, driver crash) the polling loop would hang.
                        if total_samples > last_callback_samples:
                            last_callback_samples = total_samples
                            last_callback_at = time.time()
                        elif time.time() - last_callback_at > 3.0:
                            print("[REC] Watchdog: callback stopped firing — aborting record.")
                            break
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
        if not endpoint.has_spoken:
            # Nothing but room noise: transcribing it only invents a question
            # ("[Music]", "Subscribe to our channel...") for BMO to answer.
            print("[REC] No speech detected — not transcribing.")
            return None
        data = np.concatenate(frames, axis=0)

        # Down-sample 48 kHz → 16 kHz with a polyphase filter (better than the
        # old ffmpeg subprocess + extra disk write). 48000 / 3 = 16000 exactly.
        import scipy.io.wavfile
        ratio = MIC_SAMPLE_RATE // 16000
        if MIC_SAMPLE_RATE == 16000 or ratio < 2:
            data_16k = data.flatten()
        else:
            data_16k = scipy.signal.resample_poly(data.flatten().astype(np.float32), 1, ratio)
            data_16k = np.clip(data_16k, -32768, 32767).astype(np.int16)
        scipy.io.wavfile.write(filename, 16000, data_16k)
        return filename
    # --- TIMERS & REMINDERS ---
    def start_timer_thread(self, minutes, message, reminder_id=None, kind="timer", name=None):
        """Fire `message` in `minutes`.  The timer is saved in self.reminders
        (so the morning briefing can list it and a reboot re-arms it) and
        removed when it fires.  Pass `reminder_id` to re-arm a saved one."""
        if reminder_id is None:
            reminder_id = self.reminders.add(time.time() + minutes * 60, message, kind=kind, name=name)

        def timer_worker():
            print(f"[TIMER SET] for {minutes} minutes. Message: {message}")
            # Wait on stop_event so app shutdown drains the timer immediately.
            # The saved entry stays, so the next start re-arms it.
            if self.stop_event.wait(timeout=minutes * 60):
                print(f"[TIMER CANCELLED] (app shutting down): {message}")
                return
            if not self.reminders.remove(reminder_id):
                print(f"[TIMER CANCELLED] (by voice): {message}")   # "cancel the pasta timer"
                return
            print(f"[TIMER DONE] {message}")

            # Wait for BMO to finish speaking/listening (and any morning
            # briefing) so the reminder doesn't fight it for the speaker.
            self._wait_until_idle({BotStates.SPEAKING, BotStates.LISTENING, BotStates.BRIEFING},
                                  poll_s=1.0, timeout_s=300)
                
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

    # --- MORNING BRIEFING ---
    def _briefing_settings(self):
        s = load_briefing_settings()
        if BRIEFING_NOW_WINDOW:
            # --briefing-now: a window open from start-up, every day, no lead time.
            s.update(enabled=True, window=list(BRIEFING_NOW_WINDOW), prepare_minutes_before=0,
                     days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
        return s

    def _briefing_can_show(self):
        """Icon and chime wait for BMO to be idle (they share the speaker)."""
        return self.current_state in (BotStates.IDLE, BotStates.SCREENSAVER) and not self.is_busy

    def _on_briefing_icon(self, visible):
        if visible:
            self.icon_overlay.show()
        else:
            self.icon_overlay.hide(fade=True)

    def _draw_overlays(self, img, now):
        """FaceView hook: the sun icon over BMO's face (and over the screensaver)."""
        return self.icon_overlay.apply(img, now)

    def _sync_icon_label(self):
        """PNG faces can't be drawn on, so the icon is a plain label there."""
        want = self.icon_overlay.visible and self.current_state != BotStates.DISPLAY_IMAGE
        if want and self._icon_label is None:
            from core.briefing import cards
            self._icon_photo = ImageTk.PhotoImage(cards.icon_sprite("ready"))
            self._icon_label = tk.Label(self.master, image=self._icon_photo, bg='#C9E4C3',
                                        borderwidth=0, highlightthickness=0)
            # The label swallows its own taps (its event.x is label-relative).
            self._icon_label.bind('<Button-1>', lambda e: (self.start_briefing_from_tap(), "break")[1])
        if self._icon_label is not None:
            if want and not self._icon_label.winfo_ismapped():
                self._icon_label.place(relx=740 / 800, rely=60 / 480, anchor=tk.CENTER)
            elif not want and self._icon_label.winfo_ismapped():
                self._icon_label.place_forget()

    def _briefing_loop(self):
        """Tick the briefing's day every 30 s (prepare, icon + chime, fade)."""
        while not self.stop_event.is_set():
            try:
                self.briefing_scheduler.tick()
            except Exception as e:
                print(f"[BRIEFING] Scheduler error: {e}")
                traceback.print_exc()
            if self.stop_event.wait(timeout=30):
                break

    def start_briefing_from_tap(self):
        """Tap on the sun icon: play, or wiggle if BMO is busy."""
        if self.current_state in (BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING) \
                or not self._try_claim_busy():
            self.icon_overlay.wiggle()
            return
        briefing = self.briefing_scheduler.briefing_for_today()
        if briefing is None:
            self._release_busy()
            self.icon_overlay.wiggle()
            return
        self.icon_overlay.press()
        threading.Thread(target=self._play_briefing, args=(briefing,), daemon=True).start()

    def _briefing_fun_fact(self):
        """extras.fun_fact: one fact for the sign-off, made the way pondering
        makes its thoughts (web search + the LLM, which only phrases it)."""
        from core.search import search_web
        found = search_web("interesting fun fact of the day")
        if not found or found in ("SEARCH_EMPTY", "SEARCH_ERROR"):
            return None
        return self.generate_thought_internal(found)

    def _wait_for_speaker(self, timeout_s=3.0):
        """Wait for BMO's own sounds (reply TTS, thinking sound, effects) to let
        go of the speaker: only one aplay can hold the ALSA device.  A voice
        request ends its turn with the thinking sound still stopping."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            procs = [self._tts_aplay, self.thinking_audio_process] + list(self.active_sounds)
            if all(p is None or p.poll() is not None for p in procs):
                return True
            time.sleep(0.05)
        print("[BRIEFING] Speaker still busy after 3 s; trying anyway")
        return False

    def _start_part_audio(self, play_path, on_start=None, attempts=5):
        """aplay one part, retrying while the device is busy ("audio open
        error: Device or resource busy" exits within a moment).  Returns
        (proc, started_at) or (None, None) on skip/stop or repeated failure."""
        for attempt in range(attempts):
            if self._briefing_skip.is_set() or self._briefing_stop.is_set():
                return None, None
            proc = subprocess.Popen(['aplay', '-D', ALSA_DEVICE, '-q', '--buffer-time=500000', play_path])
            started = time.time()
            if on_start:
                on_start()                        # lip-sync from the moment aplay starts
            try:
                proc.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                return proc, started              # still running: it's playing
            if proc.returncode == 0:
                return proc, started              # a very short clip, already done
            print(f"[BRIEFING] aplay failed ({proc.returncode}), retrying ({attempt + 1}/{attempts})")
            self._wait_for_speaker(1.0)
            time.sleep(0.2)
        return None, None

    BRIEFING_STALE_S = 3 * 3600   # asked for later in the day: re-fetch past this age

    def _briefing_on_request(self):
        """Voice: "morning briefing", "show me my briefing", "good morning"...
        Like play_music: wait for this turn to finish, then take the busy lock
        (giving up quietly if something else has it).  Outside the morning, or
        if today's briefing is stale, a fresh one is fetched and rendered first."""
        if not self._wait_until_idle({BotStates.SPEAKING, BotStates.THINKING}):
            return
        if not self._busy_lock.acquire(timeout=5.0):
            print("[BRIEFING] Busy; not starting the briefing")
            return
        self.is_busy = True
        self.last_user_interaction = time.time()
        briefing = self.briefing_scheduler.briefing_for_today()
        if briefing is None or time.time() - briefing.get("created", 0) > self.BRIEFING_STALE_S:
            print("[BRIEFING] Preparing a fresh briefing on request")
            # Fetching + rendering takes ~20-30 s: say so, so it doesn't look stuck.
            result = {}
            worker = threading.Thread(
                target=lambda: result.update(b=self.briefing_scheduler.prepare_now()), daemon=True)
            worker.start()
            self.speak("One moment, friend! BMO is getting the latest weather and news.", msg="Getting your briefing...")
            self.set_state(BotStates.THINKING, "Getting your briefing...")
            self._thinking_sound_start()
            try:
                while worker.is_alive():
                    self.last_user_interaction = time.time()   # keep the busy watchdog away
                    worker.join(timeout=1.0)
            finally:
                self._thinking_sound_stop()
            briefing = result.get("b")
            if briefing is not None:
                briefing = self.briefing_scheduler.briefing_for_today()   # with WAV paths
        if briefing is None:
            try:
                self.speak("Sorry friend, BMO couldn't get your briefing right now.", msg="Oops!")
            finally:
                self.set_state(BotStates.IDLE, "Tap to speak")
                self._release_busy()
            return
        self._play_briefing(briefing)

    def _play_briefing(self, briefing):
        """Play a cached briefing part by part.  The caller has claimed busy;
        it's released here, whatever happens."""
        from core.briefing.ui import ENTER_S, EXIT_S
        valid_moods = set(TALK_MOODS.values()) | {"idle"}
        aplay = None
        try:
            self.briefing_scheduler.mark_played()
            mood = self._briefing_settings().get("talk_mood", "happy")
            self._briefing_mood = mood if mood in valid_moods else "happy"
            self._briefing_skip.clear()
            self._briefing_stop.clear()
            if self.briefing_view is None:
                self.briefing_view = briefing_ui.BriefingView(self.face_view, (self.BG_WIDTH, self.BG_HEIGHT))
            view = self.briefing_view
            view.start(briefing)
            self._briefing_frame_ms = []
            self.set_state(BotStates.BRIEFING, "Good morning!")
            print(f"[BRIEFING] Playing {len(briefing['parts'])} parts")
            self._briefing_stop.wait(ENTER_S)    # BMO moves aside before the first card
            self._wait_for_speaker()
            for i, part in enumerate(briefing["parts"]):
                if self._briefing_stop.is_set() or self.stop_event.is_set():
                    break
                self._briefing_skip.clear()
                # Keep the 120 s busy watchdog from clearing the lock mid-briefing.
                self.last_user_interaction = time.time()
                if part["key"] == "signoff":
                    self._briefing_mood = "happy"
                if self.is_muted:
                    # No voice: show the words and move on every 6 s.
                    view.show_part(i, caption=part["text"])
                    end = time.time() + 6.0
                    while time.time() < end and not (self._briefing_skip.is_set() or self._briefing_stop.is_set()):
                        time.sleep(0.05)
                    continue
                play_path = scaled_wav(part["path"], self._software_gain())
                view.show_part(i)
                lipsync = (lambda p=part["path"]: self._schedule_wav_lipsync(p)) \
                    if self.face_view is not None else None
                aplay, started = self._start_part_audio(play_path, lipsync)
                if aplay is None:
                    if play_path != part["path"]:
                        try: os.remove(play_path)
                        except OSError: pass
                    if not (self._briefing_skip.is_set() or self._briefing_stop.is_set()):
                        print(f"[BRIEFING] Couldn't play part {i}; showing it for 6 s instead")
                        view.show_part(i, caption=part["text"])
                        self._briefing_skip.wait(6.0)
                    continue
                marks = part.get("marks") or []
                while aplay.poll() is None:
                    if self._briefing_skip.is_set() or self._briefing_stop.is_set() or self.stop_event.is_set():
                        aplay.terminate()
                        with self._lip_lock:                  # close the mouth now
                            self._lip_sched, self._lip_start = [], None
                        break
                    elapsed = time.time() - started
                    passed = [m["mark"] for m in marks if m["at"] <= elapsed]
                    if passed:
                        view.set_highlight(passed[-1])
                    time.sleep(0.04)
                try:
                    aplay.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    aplay.kill()
                if aplay.returncode not in (0, None, -15) and not self._briefing_skip.is_set():
                    print(f"[BRIEFING] aplay exited with {aplay.returncode} on part {i}")
                aplay = None
                if play_path != part["path"]:
                    try: os.remove(play_path)
                    except OSError: pass
            view.finish()
            time.sleep(EXIT_S)
        except Exception as e:
            print(f"[BRIEFING] Playback failed: {e}")
            traceback.print_exc()
        finally:
            if aplay is not None and aplay.poll() is None:
                aplay.kill()
            # Leave BRIEFING before resetting the view, so no frame draws a reset view.
            self.set_state(BotStates.HAPPY, "Have a great day!")
            if self.briefing_view is not None:
                self.briefing_view.reset()
            ms = sorted(self._briefing_frame_ms)
            if ms:
                print(f"[BRIEFING] {len(ms)} frames: median {ms[len(ms) // 2]:.1f} ms, "
                      f"p95 {ms[int(len(ms) * 0.95)]:.1f} ms, max {ms[-1]:.1f} ms")
            self._release_busy()

            def _back_to_idle():
                if self.current_state == BotStates.HAPPY:
                    self.set_state(BotStates.IDLE, "Tap to speak")
            self.master.after(2000, _back_to_idle)

    def _rearm_reminders(self):
        """Restart saved timers still in the future; drop ones missed while off."""
        for r in self.reminders.prune_past():
            print(f"[TIMER DROPPED] missed while BMO was off: {r['message']!r}")
        now = time.time()
        for r in self.reminders.pending():
            self.start_timer_thread((r["due"] - now) / 60, r["message"], reminder_id=r["id"],
                                    kind=r.get("kind", "timer"))

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

        # Start aplay with a much larger buffer to prevent stuttering during CPU/NPU spikes.
        # --buffer-time=500000 is 500ms, which provides a very stable buffer for the Pi 5.
        aplay_cmd = ["aplay", "-D", ALSA_DEVICE, "-r", str(sample_rate), "-f", "S16_LE", "-t", "raw", "-q", "--buffer-time=500000"]
        
        # Stop the thinking sound ONCE before retrying — not on every attempt.
        self.is_thinking_sound_playing = False
        if self.thinking_audio_process is not None:
            try:
                self.thinking_audio_process.terminate()
                self.thinking_audio_process.wait(timeout=0.5)
            except Exception:
                pass
            self.thinking_audio_process = None

        # Hardware Retry Loop: If the thinking sound hasn't fully released the
        # hardware yet, we retry a few times before giving up.
        proc = None
        for attempt in range(10):
            try:
                proc = subprocess.Popen(aplay_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                # Quick check if it failed immediately (e.g. Device Busy)
                time.sleep(0.1)
                if proc.poll() is not None:
                    _, err = proc.communicate()
                    if b"Device or resource busy" in err:
                        print(f"[DEBUG] Audio device busy (attempt {attempt+1}/10), retrying...")
                        time.sleep(0.3)
                        continue
                break # Success
            except Exception as e:
                print(f"[DEBUG] Audio startup error: {e}")
                time.sleep(0.3)

        if not proc or proc.poll() is not None:
            print("[DEBUG] Failed to open audio device after retries.")
            return

        interrupted = False
        try:
            start_time = time.time()
            chunk_idx = 0

            while not self.stop_event.is_set():
                if self.is_muted:
                    interrupted = True
                    break

                # 1024 samples * 2 bytes per sample (S16_LE)
                raw_chunk = stream.read(chunk_size * 2)
                if not raw_chunk:
                    break

                # Lip-sync from unscaled signal, then apply software volume
                audio_chunk = np.frombuffer(raw_chunk, dtype=np.int16)
                vol = np.sqrt(np.mean(audio_chunk.astype(np.float32)**2))
                if self.current_state == BotStates.SPEAKING:
                    self.mouth_open = min(60, vol / 25)

                vol_scale = self._software_gain()
                if vol_scale != 1.0:
                    scaled = np.clip(audio_chunk.astype(np.float32) * vol_scale, -32768, 32767).astype(np.int16)
                    write_chunk = scaled.tobytes()
                else:
                    write_chunk = raw_chunk

                try:
                    proc.stdin.write(write_chunk)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError) as e:
                    print(f"[DEBUG] aplay write error: {e}")
                    break

                # No manual pacing — aplay's hardware buffer back-pressures stdin.write naturally.

            # stop_event firing mid-stream is also an interruption
            if self.stop_event.is_set():
                interrupted = True
        finally:
            if proc.stdin:
                try: proc.stdin.close()
                except Exception: pass
            if not interrupted:
                # Natural end of stream — let aplay drain its 500ms ALSA buffer fully
                # before we exit, otherwise the last words are cut off.
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    try: proc.terminate()
                    except Exception: pass
            else:
                # Muted or stopped — kill immediately for instant silence
                try: proc.terminate()
                except Exception: pass
            self.mouth_open = 0
            self.mouth_ema = 0 # Final reset to closed
            self.speaking_frame = 0

    def _warmup_piper(self):
        """Pre-spawn Piper (without aplay) to hide model-load latency behind STT.
        Safe to call repeatedly — no-op if Piper is already running."""
        if self._piper_proc is not None and self._piper_proc.poll() is None:
            return
        from core.config import PIPER_CMD, PIPER_MODEL
        try:
            self._piper_proc = subprocess.Popen(
                [PIPER_CMD, "--model", PIPER_MODEL, "--output_raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            print("[TTS] Piper warmed up.")
        except Exception as e:
            print(f"[TTS] Piper warmup failed: {e}")
            self._piper_proc = None

    def _start_tts_turn(self):
        """Start a persistent Piper + aplay pipeline for a single speaking turn.

        Piper is kept alive for the entire turn so the TTS model is loaded only
        once.  Every sentence is written to Piper's stdin; a reader thread pumps
        the raw PCM output into aplay continuously — no per-sentence startup gap.
        Reuses a pre-warmed Piper from _warmup_piper() if available.
        """
        from core.config import PIPER_CMD, PIPER_MODEL, ALSA_DEVICE

        # Detect a pre-warmed Piper (loaded but not yet wired to aplay/reader)
        piper_warm = (
            self._piper_proc is not None and self._piper_proc.poll() is None
            and self._piper_reader_thread is None and self._tts_aplay is None
        )
        if not piper_warm:
            self._kill_tts_pipeline()

        # Release ALSA: stop the thinking sound AND any other active sound
        # (ack sounds are tracked in active_sounds, not thinking_audio_process).
        self.is_thinking_sound_playing = False
        if self.thinking_audio_process is not None:
            try:
                self.thinking_audio_process.terminate()
                self.thinking_audio_process.wait(timeout=0.5)
            except Exception:
                pass
            self.thinking_audio_process = None
        for proc in list(self.active_sounds):
            try:
                proc.terminate()
            except Exception:
                pass

        # Start aplay (retry on busy ALSA device)
        aplay_cmd = ["aplay", "-D", ALSA_DEVICE, "-r", "22050", "-f", "S16_LE",
                     "-t", "raw", "-q", "--buffer-time=500000"]
        for attempt in range(10):
            try:
                self._tts_aplay = subprocess.Popen(aplay_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(0.05)
                if self._tts_aplay.poll() is not None:
                    _, err = self._tts_aplay.communicate()
                    if b"Device or resource busy" in err:
                        print(f"[TTS] Audio device busy (attempt {attempt+1}/10), retrying...")
                        time.sleep(0.3)
                        continue
                break
            except Exception as e:
                print(f"[TTS] aplay startup error: {e}")
                time.sleep(0.3)

        if self._tts_aplay is None or self._tts_aplay.poll() is not None:
            print("[TTS] Failed to open audio device after retries.")
            self._tts_aplay = None
            # Also kill any pre-warmed piper so speak() sees _piper_proc is None
            # and bails cleanly rather than writing audio nobody can play.
            if self._piper_proc is not None:
                try:
                    self._piper_proc.stdin.close()
                except Exception:
                    pass
                try:
                    self._piper_proc.terminate()
                    self._piper_proc.wait(timeout=1.0)
                except Exception:
                    pass
                self._piper_proc = None
            return

        # Spawn Piper if not already warmed up
        if not piper_warm:
            self._piper_proc = subprocess.Popen(
                [PIPER_CMD, "--model", PIPER_MODEL, "--output_raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

        # Fresh lip-sync schedule for this turn: playback offsets restart at 0
        # and _lip_start is stamped when the reader queues its first chunk.
        with self._lip_lock:
            self._lip_sched = []
            self._lip_start = None
            self._lip_end = None
        if self._lip_sync is not None:
            self._lip_sync.reset()

        # Reader thread: Piper stdout → aplay stdin (with lip-sync)
        self._piper_reader_thread = threading.Thread(
            target=self._piper_to_aplay_loop, daemon=True
        )
        self._piper_reader_thread.start()

    def _piper_to_aplay_loop(self):
        """Read Piper's raw PCM output and stream it into aplay with lip-sync."""
        chunk_size = 512  # samples (~23 ms at 22050 Hz)
        sample_rate = 22050
        samples_written = 0  # drives each chunk's playback offset for lip-sync
        exit_reason = "unknown"

        while True:
            try:
                raw_chunk = self._piper_proc.stdout.read(chunk_size * 2)
            except Exception as e:
                exit_reason = f"piper read error: {e}"
                break
            if not raw_chunk:
                exit_reason = "piper EOF (normal)"
                break  # Piper stdout closed — all audio transferred

            if self.is_muted:
                exit_reason = "muted"
                break  # mute_bmo will kill the pipeline

            # Lip-sync: record this chunk's loudness against WHEN it will play,
            # not when we queue it. We pump audio into aplay's buffer far faster
            # than real time, so driving mouth_open here directly would race
            # seconds ahead of what the user hears; update_animation replays the
            # schedule in sync with playback instead.
            audio_chunk = np.frombuffer(raw_chunk, dtype=np.int16)
            vol = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
            if self.current_state == BotStates.SPEAKING:
                play_offset = samples_written / sample_rate
                speech = self._lip_sync.push(audio_chunk) if self._lip_sync is not None else None
                with self._lip_lock:
                    if self._lip_start is None:
                        self._lip_start = time.time()
                    self._lip_sched.append((play_offset, float(min(60, vol / 25)), speech))
                    self._lip_end = play_offset
            samples_written += len(audio_chunk)

            vol_scale = self._software_gain()
            if vol_scale != 1.0:
                scaled = np.clip(audio_chunk.astype(np.float32) * vol_scale, -32768, 32767).astype(np.int16)
                write_chunk = scaled.tobytes()
            else:
                write_chunk = raw_chunk

            try:
                self._tts_aplay.stdin.write(write_chunk)
                self._tts_aplay.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                exit_reason = f"aplay write error: {e}"
                print(f"[TTS] aplay write error: {e}")
                break

            # No manual pacing: aplay's 500 ms hardware buffer applies natural
            # back-pressure on stdin.write once it's full. The old time.sleep()
            # could stack on top of that and starve the buffer briefly.

        print(f"[TTS] Reader thread exiting: {exit_reason}")

        # Close aplay's stdin immediately when we're done pumping — this signals
        # aplay to drain and exit as soon as the last bytes play out, without
        # waiting for _end_tts_turn to call us back.
        if exit_reason == "piper EOF (normal)" and self._tts_aplay is not None:
            try:
                self._tts_aplay.stdin.close()
            except Exception:
                pass

        # On a normal EOF the reader finishes long before playback does — up to
        # ~500 ms of audio is still draining from aplay's buffer. Leave the
        # schedule in place so update_animation keeps the mouth moving through
        # the tail and closes it (via _lip_end) when playback actually ends.
        # Only force the mouth shut immediately on an abnormal exit (mute/error).
        if exit_reason != "piper EOF (normal)":
            with self._lip_lock:
                self._lip_sched = []
                self._lip_start = None
                self._lip_end = None
            self.mouth_open = 0
            self.mouth_ema = 0
            self.speaking_frame = 0

    def _write_to_piper(self, text):
        """Write one line of cleaned text to the persistent Piper process."""
        if self._piper_proc is None or self._piper_proc.poll() is not None:
            return
        try:
            self._piper_proc.stdin.write((text + "\n").encode("utf-8"))
            self._piper_proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            print(f"[TTS] Piper stdin write error: {e}")

    def _end_tts_turn(self, drain=True):
        """Close the Piper + aplay pipeline at the end of a speaking turn.

        Closing Piper's stdin signals it to finish processing.  The reader thread
        pumps remaining audio into aplay and then closes aplay's stdin itself.
        We join the reader thread (which blocks until all audio is queued), then
        wait for aplay to drain with no hard timeout so long responses always
        finish playing.
        """
        # Signal Piper to finish — it will write remaining audio then close stdout
        if self._piper_proc is not None:
            try:
                self._piper_proc.stdin.close()
            except Exception:
                pass

        # Wait for reader thread to pump all remaining audio into aplay.
        # The thread paces itself at real-time audio speed, so a 60-second
        # response takes ~60 seconds.  No timeout — we must never cut BMO off
        # mid-sentence; a hard limit here is the wrong tool.  The thread will
        # always exit once piper's stdout closes.
        if self._piper_reader_thread is not None:
            self._piper_reader_thread.join()
            self._piper_reader_thread = None

        # Reap Piper process
        if self._piper_proc is not None:
            try:
                self._piper_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    self._piper_proc.terminate()
                except Exception:
                    pass
            self._piper_proc = None

        # The reader thread already closed aplay's stdin on a clean exit.
        # Close it here too (idempotent) to handle early-exit cases, then wait.
        if self._tts_aplay is not None:
            try:
                self._tts_aplay.stdin.close()
            except Exception:
                pass
            if drain:
                # Wait indefinitely — after stdin closes, aplay drains its
                # hardware buffer (~500 ms) and exits on its own.  There is
                # no hard cutoff; the response length drives the wait time.
                print("[TTS] Waiting for aplay to finish draining...")
                self._tts_aplay.wait()
                print("[TTS] aplay finished.")
            else:
                try:
                    self._tts_aplay.terminate()
                except Exception:
                    pass
            self._tts_aplay = None

        with self._lip_lock:
            self._lip_sched = []
            self._lip_start = None
            self._lip_end = None
        self.mouth_open = 0
        self.mouth_ema = 0
        self.speaking_frame = 0

    def _kill_tts_pipeline(self):
        """Hard-kill the Piper + aplay pipeline without draining (used by mute / turn start).

        Tries a non-blocking acquire of `speak_lock` first so we don't race a
        concurrent _start_tts_turn(); if we can't get it, we still proceed
        (mute must always win) but the brief lock-attempt window narrows the
        overlap with another thread that's mid-startup."""
        got_lock = self.speak_lock.acquire(blocking=False)
        try:
            self._kill_tts_pipeline_unlocked()
        finally:
            if got_lock:
                self.speak_lock.release()

    def _kill_tts_pipeline_unlocked(self):
        if self._piper_proc is not None:
            try:
                self._piper_proc.stdin.close()
            except Exception:
                pass
            try:
                self._piper_proc.terminate()
            except Exception:
                pass

        if self._piper_reader_thread is not None:
            self._piper_reader_thread.join(timeout=1.0)
            self._piper_reader_thread = None

        if self._piper_proc is not None:
            try:
                self._piper_proc.wait(timeout=1.0)
            except Exception:
                pass
            self._piper_proc = None

        if self._tts_aplay is not None:
            try:
                self._tts_aplay.terminate()
            except Exception:
                pass
            self._tts_aplay = None

        with self._lip_lock:
            self._lip_sched = []
            self._lip_start = None
            self._lip_end = None
        self.mouth_open = 0
        self.mouth_ema = 0
        self.speaking_frame = 0

    def speak(self, text, msg="Speaking...", end_of_turn=True):
        """Synthesize text via Piper and play it through aplay.

        Uses a persistent Piper process for the entire turn so the TTS model is
        loaded only once — eliminating the per-sentence startup gap that caused
        unnatural pauses in multi-sentence responses.
        """
        from core.tts import clean_text_for_speech

        clean_text = clean_text_for_speech(text)
        if not clean_text or not any(c.isalnum() for c in clean_text):
            if end_of_turn:
                self._end_tts_turn()
            return

        print(f"[TTS] {'Final' if end_of_turn else 'Mid'}: '{clean_text[:70]}'")

        # Transition to SPEAKING state immediately for responsive lip-sync
        if self.current_state != BotStates.DISPLAY_IMAGE:
            if msg is not None:
                self.set_state(BotStates.SPEAKING, msg)
            elif self.current_state != BotStates.SPEAKING:
                self.current_state = BotStates.SPEAKING
                self.current_frame = 0
                self.last_state_change = time.time()

        with self.speak_lock:
            try:
                if not self.is_muted:
                    # Lazily start the pipeline on the first sentence of a turn.
                    # Check the whole chain, not just Piper: the wake-word flow
                    # pre-warms Piper with no reader/aplay attached, and writing
                    # to that sends every sentence nowhere (logged, never heard).
                    # _start_tts_turn() adopts a warm Piper and wires it up.
                    pipeline_ready = (
                        self._piper_proc is not None and self._piper_proc.poll() is None
                        and self._piper_reader_thread is not None
                        and self._tts_aplay is not None and self._tts_aplay.poll() is None
                    )
                    if not pipeline_ready:
                        self._start_tts_turn()
                        if self._piper_proc is None:
                            # Failed to start — skip audio, still transition state
                            if end_of_turn and self.current_state == BotStates.SPEAKING:
                                self.set_state(BotStates.IDLE, "Tap to speak")
                            return

                    # Write text to the running Piper (returns immediately)
                    self._write_to_piper(clean_text)

                    if end_of_turn:
                        # Block until all audio has finished playing
                        self._end_tts_turn(drain=True)
                    # else: pipeline stays open, next sentence streams in gaplessly
                else:
                    time.sleep(0.2)
                    if end_of_turn:
                        self._end_tts_turn(drain=False)
            except Exception as e:
                print(f"[TTS] speak() error: {e}")
                self.mouth_open = 0
                self._end_tts_turn(drain=False)

        # Return face to IDLE after the final sentence of the turn
        if end_of_turn and self.current_state == BotStates.SPEAKING:
            if msg is not None:
                self.set_state(BotStates.IDLE, "Tap to speak")
            else:
                self.current_state = BotStates.IDLE
                self.current_frame = 0
                self.last_state_change = time.time()




    def _handle_response_chunk(self, chunk, is_last=True):
        """Processes a single chunk from the LLM, handling actions and speech."""
        if not chunk.strip():
            return
            
        # These will be updated in the main loop via side effects on self
        # or we can just use self.current_image_url etc.
        # But to match existing logic, we'll use regex here
        
        # 1. Handle JSON actions (brace-balanced — handles nested objects + lax spacing).
        #    The model may emit several on one chunk (e.g. set_expression + set_timer),
        #    so drain them all rather than acting on the first and speaking the rest.
        while True:
            action_data, span = extract_json_object(chunk)
            if action_data is None:
                break
            if "action" not in action_data:
                # Some other JSON-ish blob — drop it so it isn't spoken aloud.
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
                continue
            if action_data.get("action") == "take_photo":
                self.taking_photo = True
                return
            if action_data.get("action") == "display_image":
                self.current_image_url = action_data.get("image_url")
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
            elif action_data.get("action") == "set_expression":
                expr = (action_data.get("value") or "").lower()
                allowed = {
                    BotStates.HAPPY, BotStates.SAD, BotStates.ANGRY, BotStates.SURPRISED,
                    BotStates.SLEEPY, BotStates.DIZZY, BotStates.CHEEKY, BotStates.HEART,
                    BotStates.STARRY_EYED, BotStates.CONFUSED, BotStates.BORED,
                    BotStates.CURIOUS, BotStates.DAYDREAM, BotStates.JAMMING,
                    BotStates.SHHH, BotStates.LOW_BATTERY,
                }
                # Piper runs ahead of playback, so a tag late in the reply lands
                # while BMO is still talking.  Switching state then froze the face
                # on the expression (an open "O" for curious) for the rest of the
                # sentence; instead talk on in that mood.
                talking = self.current_state == BotStates.SPEAKING or (
                    self._tts_aplay is not None and self._tts_aplay.poll() is None)
                if expr in allowed and talking:
                    if expr in TALK_MOODS:
                        self._talk_mood = TALK_MOODS[expr]
                elif expr in allowed:
                    self.set_state(expr, f"Feeling {expr}...")
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
            elif action_data.get("action") == "play_music":
                def music_worker():
                    if not self._wait_until_idle({BotStates.SPEAKING, BotStates.THINKING}):
                        return  # shutdown
                    music_proc = self.play_sound("music")
                    if music_proc:
                        self.set_state(BotStates.JAMMING, "Jamming!")
                        try:
                            music_proc.wait(timeout=600)
                        except subprocess.TimeoutExpired:
                            try: music_proc.terminate()
                            except Exception: pass
                        if self.current_state == BotStates.JAMMING:
                            self.set_state(BotStates.IDLE, "Tap to speak")
                threading.Thread(target=music_worker, daemon=True).start()
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
            elif action_data.get("action") == "play_briefing":
                threading.Thread(target=self._briefing_on_request, daemon=True).start()
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
            elif action_data.get("action") == "set_reminder":
                # From core/timers.parse_reminder_request: an absolute time,
                # so no 12-hour clamp (it can be days away).
                try:
                    minutes = (float(action_data["due"]) - time.time()) / 60
                    msg_text = str(action_data.get("message") or "Reminder!")
                    if minutes > 0:
                        self.start_timer_thread(minutes, msg_text, kind="reminder")
                        print(f"[TIMER] Reminder in {minutes:.0f} min — {msg_text!r}")
                except (KeyError, TypeError, ValueError) as e:
                    print(f"[TIMER] Bad set_reminder payload {action_data!r}: {e}")
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
            elif action_data.get("action") == "set_timer":
                # Real handler — was advertised in the system prompt but
                # silently ignored.  Coerce minutes safely; clamp to [0.05, 720].
                try:
                    raw_min = action_data.get("minutes", 0)
                    minutes = float(raw_min)
                    minutes = max(0.05, min(720.0, minutes))  # 3 s … 12 h
                    msg_text = (action_data.get("message") or "").strip()
                    # Models like to echo the prompt's placeholder verbatim.
                    if msg_text in ("", "...", "…"):
                        msg_text = "Timer is up!"
                    self.start_timer_thread(minutes, str(msg_text), name=action_data.get("name"))
                    print(f"[TIMER] Scheduled: {minutes} min — {msg_text!r}")
                except (TypeError, ValueError) as e:
                    print(f"[TIMER] Bad set_timer payload {action_data!r}: {e}")
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
            else:
                # Unknown/legacy action (search_web, get_time, capture_image…).
                # Must still consume it, or this loop never terminates.
                print(f"[ACTION] Ignoring unknown action: {action_data.get('action')!r}")
                chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()

        # 2. Speak the remaining text
        if chunk.strip():
            self.speak(chunk, msg=None, end_of_turn=is_last)
        elif is_last:
            # Last chunk was a pure JSON action with no spoken text.  Close any
            # open TTS pipeline so piper+aplay don't stay open holding ALSA.
            self._end_tts_turn(drain=True)

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
            def _await_greeting():
                greeting_proc.wait()
                if self.current_state == BotStates.SPEAKING:
                    self.set_state(BotStates.IDLE, "Tap to speak")
            threading.Thread(target=_await_greeting, daemon=True).start()
        else:
            self.set_state(BotStates.IDLE, "Tap to speak")

        while not self.stop_event.is_set():
            # 1. Wait for Wake Word
            self._release_busy()
            if self.wait_for_wakeword(oww):
                # Block briefly if a trigger flow is mid-run; gives up after 2 s
                if not self._busy_lock.acquire(timeout=2.0):
                    print("[MAIN] Couldn't claim busy lock; another flow is running.")
                    continue
                self.is_busy = True
                self.last_user_interaction = time.time()
                # 2. Record
                self.set_state(BotStates.LISTENING, "Listening...")
                # Pre-warm Piper in parallel with STT so the first TTS chunk has zero start-up gap
                threading.Thread(target=self._warmup_piper, daemon=True).start()
                wav_file = self.record_audio()
                if wav_file is None:  # no speech (or mic error): back to waiting
                    if self.current_state != BotStates.ERROR:  # keep "Mic Error" visible
                        self.set_state(BotStates.IDLE, "Tap to speak")
                    self._release_busy()
                    continue

                # 3. Transcribe
                self.set_state(BotStates.THINKING, "Transcribing...")
                self._thinking_sound_start()

                user_text = self.transcribe(wav_file)
                print(f"User Transcribed: {user_text}")
                
                if len(user_text) < 2:
                    self.set_state(BotStates.IDLE, "Tap to speak")
                    self._release_busy()
                    self._thinking_sound_stop()
                    continue

                # 4. LLM
                self.set_state(BotStates.THINKING, "Thinking...")

                # We DO NOT stop the thinking sound loop here.
                # Let it continue playing its current sound seamlessly while the LLM thinks.


                try:
                    full_response = ""
                    self.current_image_url = None
                    self.taking_photo = False
                    
                    # Lock LLM access to prevent screensaver interference
                    with self.llm_lock:
                        # Use a peekable-style approach to detect the last chunk
                        gen = self.brain.stream_think(user_text)
                        try:
                            chunk = next(gen)
                            while True:
                                try:
                                    next_chunk = next(gen)
                                    # If we got here, 'chunk' is not the last one
                                    self._handle_response_chunk(chunk, is_last=False)
                                    full_response += chunk
                                    chunk = next_chunk
                                except StopIteration:
                                    # 'chunk' was the last one
                                    self._handle_response_chunk(chunk, is_last=True)
                                    full_response += chunk
                                    break
                        except StopIteration:
                            pass

                    image_url = self.current_image_url
                    taking_photo = self.taking_photo
                    
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
                            # Cap at 15 s — camera firmware can hang on USB glitches
                            subprocess.run(
                                [cam_cmd, '-o', 'temp.jpg', '--width', '640', '--height', '480',
                                 '--nopreview', '-t', '2000', '--autofocus-mode', 'continuous'],
                                check=True, timeout=15,
                            )
                            import base64
                            with open('temp.jpg', 'rb') as img_file:
                                b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                            self.set_state(BotStates.THINKING, "Analyzing...")
                            self._thinking_sound_start()  # Idempotent — reuses existing loop if alive
                            response = self.brain.analyze_image(b64_string, user_text)
                            self._thinking_sound_stop()
                            # Clean up the captured image — we don't need it anymore
                            try:
                                if os.path.exists('temp.jpg'):
                                    os.remove('temp.jpg')
                            except Exception:
                                pass
                            self.speak(response)
                        except FileNotFoundError as e:
                            print(f"Camera Error: {e}")
                            self.speak("Hmm, BMO doesn't seem to have a camera connected right now. I can't take a photo!")

                        except subprocess.TimeoutExpired:
                            print("Camera Error: capture timed out after 15 s")
                            self.speak("My camera took too long to respond. Let's try that again later!")

                        except Exception as e:
                            print(f"Camera Error: {e}")
                            self.speak("I tried to take a photo, but my camera isn't working.")
                    
                    # 5. Display Image (if any). The pre-LLM lead-in (from
                    # _quick_lead_in in core/llm.py) was already streamed and
                    # spoken via _handle_response_chunk, so we don't need to
                    # speak again here.
                    if image_url:
                        self.set_state(BotStates.DISPLAY_IMAGE, "Showing Image...")
                        print(f"[IMAGE] Starting image display for: {image_url}")
                        try:
                            # Note: migrated to loremflickr
                            print(f"[IMAGE] Downloading: {image_url}")
                            req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=8) as u:
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

                self.set_state(BotStates.IDLE, "Tap to speak")

                self._release_busy()
                # 1-second ALSA cooldown before re-opening the mic stream.
                # Use manual_wake_event.wait() instead of sleep() so a tap during
                # this window is not lost — it will be caught by wait_for_wakeword()
                # on the very next loop iteration.
                self.manual_wake_event.wait(timeout=1.0)

    def trigger_random_thought(self, event=None):
        """Manually trigger a random pondering thought (BMO's red button)."""
        # Quiet Hours: 8 PM to 8 AM
        _hour = datetime.datetime.now().hour
        if _hour >= 20 or _hour < 8:
            return
        if self.current_state in [BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING]:
            return
        if not self._try_claim_busy():
            return  # another flow holds the busy lock

        def run_thought():
            from core.search import search_web, search_images
            from core.config import LLM_URL, FAST_LLM_MODEL
            import requests as http_requests

            display_owns_busy = False
            try:
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
                        # Check for image URL or subject (brace-balanced JSON)
                        image_url = None
                        action_data, span = extract_json_object(phrase)
                        if action_data is not None and action_data.get("action") == "display_image":
                            subject = action_data.get("subject") or action_data.get("image_url")
                            if subject:
                                if "://" in subject:
                                    image_url = subject
                                else:
                                    image_url = search_images(subject)
                            phrase = (phrase[:span[0]] + phrase[span[1]:]).strip()

                        self.speak(phrase, msg="Pondering...")
                        if image_url:
                            # display_remote_image owns busy from here — don't double-release
                            time.sleep(1.5)
                            display_owns_busy = True
                            self.display_remote_image(image_url, commentary_prompt=topic)
                        else:
                            self.set_state(BotStates.IDLE, "Tap to speak")
                    else:
                        self.set_state(BotStates.IDLE, "Tap to speak")
                else:
                    self.set_state(BotStates.IDLE, "Tap to speak")
            except Exception as e:
                print(f"[BUTTON] Thought error: {e}")
                self.set_state(BotStates.IDLE, "Tap to speak")
            finally:
                if not display_owns_busy:
                    self._release_busy()

        threading.Thread(target=run_thought, daemon=True).start()

    def trigger_music(self, event=None):
        """Manually trigger BMO to play music and jam."""
        if self.current_state in [BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING, BotStates.JAMMING]:
            return
        if not self._try_claim_busy():
            return

        def run_music():
            try:
                if not self._wait_until_idle({BotStates.SPEAKING, BotStates.THINKING}):
                    return
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
                    try:
                        music_proc.wait(timeout=600)
                    except subprocess.TimeoutExpired:
                        try: music_proc.terminate()
                        except Exception: pass
                    time.sleep(1) # Extra buffer
                    if self.current_state == BotStates.JAMMING:
                        self.set_state(BotStates.IDLE, "Tap to speak")
                else:
                    self.speak("BMO wants to play music, but there are no songs loaded!")
            finally:
                self._release_busy()

        threading.Thread(target=run_music, daemon=True).start()

    def trigger_generate_image(self, event=None):
        """Manually trigger an image generation."""
        if self.current_state in [BotStates.LISTENING, BotStates.THINKING, BotStates.SPEAKING]:
            return
        if not self._try_claim_busy():
            return

        def run_image_thought():
            from core.config import LLM_URL, FAST_LLM_MODEL
            from core.search import search_images
            import requests as http_requests

            try:
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
                    "keep_alive": LLM_KEEP_ALIVE,
                    "options": {"temperature": 0.9, "num_predict": 20}
                }
                
                search_term = "cute robot"
                try:
                    resp = http_requests.post(LLM_URL, json=payload, timeout=30)
                    if resp.status_code == 200:
                        search_term = resp.json().get("message", {}).get("content", "").strip()
                        search_term = search_term.replace('"', '').replace("'", '').replace('\n', '').strip()
                except Exception as e:
                    print(f"[IMAGE] LLM call failed: {e}")

                # Find a real image
                url = search_images(search_term)
                
                if not url:
                    lock_id = random.randint(1, 100000)
                    url = f"https://loremflickr.com/640/480/{search_term.replace(' ', ',')}?lock={lock_id}"
                
                # Wait for BMO to finish speaking the intro
                if not self._wait_until_idle({BotStates.SPEAKING, BotStates.THINKING}):
                    return
                self.display_remote_image(url, commentary_prompt=search_term)
            except Exception as e:
                print(f"[IMAGE] Generator failed: {e}")
                self.set_state(BotStates.IDLE, "Tap to speak")
            finally:
                self._release_busy()

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
                        "keep_alive": LLM_KEEP_ALIVE,
                        "options": {"temperature": 0.8, "num_predict": 40}
                    }
                    try:
                        resp = http_requests.post(LLM_URL, json=payload, timeout=20)
                        if resp.status_code == 200:
                            commentary = resp.json().get("message", {}).get("content", "").strip()
                            self.speak(commentary, msg="Admiring art...")
                    except Exception as e:
                        pass
                
                # 12 s display window — broken by app shutdown OR user tap
                # (handle_click on DISPLAY_IMAGE state already returns to IDLE).
                end_at = time.time() + 12
                while time.time() < end_at:
                    if self.stop_event.is_set() or self.current_state != BotStates.DISPLAY_IMAGE:
                        break
                    time.sleep(0.2)
                if self.current_state == BotStates.DISPLAY_IMAGE:
                    self.set_state(BotStates.IDLE, "Tap to speak")
            except Exception as e:
                print(f"[IMAGE] Failed to display: {e}")
                self.set_state(BotStates.IDLE, "Tap to speak")
            finally:
                self._release_busy()

        threading.Thread(target=run_display, daemon=True).start()

    def generate_thought_internal(self, search_result):
        """Shared logic for generating a BMO thought from search results."""
        from core.config import LLM_URL, FAST_LLM_MODEL
        import requests as http_requests

        if not self.llm_lock.acquire(blocking=False):
            return None
        try:
            # Sanitise the search snippet: strip HTML tags and unescape entities
            # so the LLM never echoes raw markup into BMO's speech.
            import html as _html
            clean_result = re.sub(r'<[^>]+>', ' ', search_result)
            clean_result = _html.unescape(clean_result)
            clean_result = re.sub(r'\s+', ' ', clean_result).strip()

            # Wrap the actual reply in [BMO]...[/BMO]. The stripper isolates
            # whatever's between the markers, so any rule-echo or numbered
            # preamble outside the tags is automatically discarded.
            thought_prompt = (
                "Read this real-world info, then share a short charming observation "
                "as BMO (under 40 words). Make a STATEMENT — do NOT ask questions. "
                "Wrap your reply between [BMO] and [/BMO] markers. "
                "If the topic is visual, include ONE JSON action AFTER [/BMO]: "
                '{"action": "display_image", "subject": "<3-5 word visual phrase>"} '
                f"Info: {clean_result[:1500]}"
            )
            payload = {
                "model": FAST_LLM_MODEL,
                # Weather/search snippets carry ANSI escapes that crash hailo-ollama's
                # JSON prompt renderer; the \s+ collapse above does not remove them.
                "messages": sanitize_messages([
                    {"role": "system", "content":
                     "You are BMO, a cute robot musing to yourself. Always wrap your "
                     "spoken reply in [BMO]...[/BMO] tags. Make statements, not questions. "
                     "Be specific and under 40 words."},
                    {"role": "user", "content": thought_prompt},
                ]),
                "stream": False,
                "keep_alive": LLM_KEEP_ALIVE,
                "options": {"temperature": 0.8, "num_predict": 256}
            }
            resp = http_requests.post(LLM_URL, json=payload, timeout=60)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "").strip()
                result = strip_prompt_leakage(content)
                # If the LLM returned something but stripping left nothing, return
                # the raw content (minus obvious junk) so the caller always gets text.
                if not result and content:
                    result = re.sub(r'[\[\]<>]', '', content).strip()
                return result or None
        except Exception as e:
            print(f"[LLM] Thought generation error: {e}")
        finally:
            self.llm_lock.release()
        return None

    def screensaver_audio_loop(self):
        import datetime
        import requests as http_requests
        from core.search import search_web, search_images
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
            # Honour stop_event so app shutdown doesn't have to wait up to 30 s.
            if self.stop_event.wait(timeout=30):
                break
            
            # Watchdog: if busy for >2 min with no new interaction, clear it.
            # Uses last_user_interaction (not last_state_change) so a long
            # DISPLAY_IMAGE view doesn't get force-cleared.
            if self.is_busy and (time.time() - self.last_user_interaction > 120):
                print("[WATCHDOG] BMO was busy for > 120s. Force-clearing is_busy.")
                self._release_busy()
                self.set_state(BotStates.IDLE, "Tap to speak")

            if self.current_state != BotStates.SCREENSAVER or self.is_busy:
                continue
                
            now = datetime.datetime.now()
            hour = now.hour
            
            # Quiet Hours: 8 PM to 8 AM
            if hour >= 20 or hour < 8:
                continue
            
            # Skip if user was recently interacting
            if time.time() - self.last_state_change < 60:
                continue
                
            # Random visual-only boredom animations (~10% chance every 30s)
            if random.random() < 0.10:
                expr = random.choice([BotStates.HEART, BotStates.SLEEPY, BotStates.STARRY_EYED, BotStates.DIZZY])
                self.set_state(expr, "Zzz..." if expr == BotStates.SLEEPY else "...")
                # Hold the expression for 4 seconds, then revert to Screensaver.
                # Bind expr now: the callback fires later, after the loop may have rebound it.
                def revert(expr=expr):
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
                        subprocess.Popen(['aplay', '-D', ALSA_DEVICE, '-q', '--buffer-time=500000', sound_file])
                    except Exception as e:
                        pass
                
                # Hold the persona animation for 8 seconds
                def revert_persona(persona=persona):
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
                            avoid_list = ", ".join(f"'{t}'" for t in list(self.recent_thoughts)[-6:]) if self.recent_thoughts else "none"
                            topic_messages = [
                                {"role": "system", "content": (
                                    "You are BMO's imagination. Pick ONE surprising, specific topic for BMO to ponder today. "
                                    "Draw from any domain: science, history, nature, food, art, mythology, space, technology, "
                                    "geography, animals, inventions, culture, or weird trivia. "
                                    f"Do NOT repeat these recent topics: {avoid_list}. "
                                    "Output ONLY the topic in under 10 words — no quotes, no explanation."
                                )},
                                {"role": "user", "content": "Give me a fresh, unexpected topic."}
                            ]
                            topic_payload = {
                                "model": FAST_LLM_MODEL,
                                "messages": topic_messages,
                                "stream": False,
                                "keep_alive": LLM_KEEP_ALIVE,
                                "options": {"temperature": 1.2, "num_predict": 30}
                            }
                            topic_resp = http_requests.post(LLM_URL, json=topic_payload, timeout=10)
                            if topic_resp.status_code == 200:
                                topic = topic_resp.json().get("message", {}).get("content", "").strip().strip('"').strip("'")
                                topic = re.sub(r'^Topic:|^BMO topic:|^I want to learn about: ', '', topic, flags=re.IGNORECASE)
                                if topic in self.recent_thoughts:
                                    topic = None  # force fallback to hardcoded list
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
                                # Check for image URL or subject (brace-balanced JSON)
                                image_url = None
                                action_data, span = extract_json_object(phrase)
                                if action_data is not None and action_data.get("action") == "display_image":
                                    subject = action_data.get("subject") or action_data.get("image_url")
                                    if subject:
                                        if "://" in subject:
                                            image_url = subject
                                        else:
                                            image_url = search_images(subject)
                                    phrase = (phrase[:span[0]] + phrase[span[1]:]).strip()
                                
                                # Speak the thought (atomic claim — no TOCTOU)
                                if phrase and self.current_state == BotStates.SCREENSAVER and self._try_claim_busy():
                                    self.speak(phrase, msg="Pondering...")
                                    self.last_screensaver_audio_time = time.time()

                                    # Handle image display
                                    if image_url:
                                        # Wait for BMO to start speaking
                                        time.sleep(1.5)
                                        self.display_remote_image(image_url, commentary_prompt=topic)
                                        # display_remote_image releases busy in its finally
                                    else:
                                        self._release_busy()
                    except Exception as e:
                        print(f"[SCREENSAVER] Thought failed: {e}")
                        self._release_busy()
                        self.set_state(BotStates.SCREENSAVER, "Sleeping...")
                
                # Revert to screensaver state if needed
                if self.current_state != BotStates.SCREENSAVER and not self.is_busy and self.current_state != BotStates.DISPLAY_IMAGE:
                    self.set_state(BotStates.SCREENSAVER, "Sleeping...")

def _claim_single_instance():
    """Exit if another BMO agent is already running.

    A second copy (e.g. the desktop icon tapped while BMO is up) can't open the
    USB mic — the first holds it exclusively — so it silently falls back to
    another input and the two talk over each other.  flock is released by the
    kernel when the process exits or crashes, so a stale lock never blocks a
    restart.  Returns the open lock file, which must stay referenced."""
    import fcntl
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "bmo-agent.lock")
    lock = open(path, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.seek(0)
        other = lock.read().strip() or "unknown"
        print(f"[BMO] Another BMO is already running (PID {other}) — exiting.")
        sys.exit(0)
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def _enable_briefing_now():
    """--briefing-now: open a morning-briefing window from now for an hour,
    with a fresh render, icon and chime, so the screen can be tried any time."""
    global BRIEFING_NOW_WINDOW
    import shutil
    from core.briefing import audio as _audio
    now = datetime.datetime.now()
    end = min(now + datetime.timedelta(hours=1), now.replace(hour=23, minute=59))
    BRIEFING_NOW_WINDOW = (now.strftime("%H:%M"), end.strftime("%H:%M"))
    shutil.rmtree(_audio.day_dir(now.date()), ignore_errors=True)  # re-render, re-chime
    print(f"[BRIEFING] --briefing-now: window {BRIEFING_NOW_WINDOW[0]}-{BRIEFING_NOW_WINDOW[1]}; "
          "the icon appears once it's rendered (~20 s)")


if __name__ == "__main__":
    _instance_lock = _claim_single_instance()
    if "--briefing-now" in sys.argv[1:]:
        _enable_briefing_now()
    root = tk.Tk()
    app = BotGUI(root)
    # Window-manager close (X button, system kill) routes through the same
    # cleanup path as the Escape key — flushes memory.json, kills aplay, etc.
    root.protocol("WM_DELETE_WINDOW", app.exit_fullscreen)
    root.mainloop()

