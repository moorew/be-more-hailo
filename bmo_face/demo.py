"""Try the face rig on BMO's screen without running the agent.

    python -m bmo_face.demo                 # 800x480 window
    python -m bmo_face.demo --fullscreen

Keys: 1-9, 0, - pick an expression · space (or tap) says a random line with
lip-sync · w wakes BMO up · Esc quits. Run from the repo root so ./sounds is found.
"""

from __future__ import annotations

import argparse
import glob
import os
import random
import shutil
import subprocess
import time
import tkinter as tk
import wave

from .rig import load_presets
from .tk_face import FaceView, SpeechSchedule

KEYS = "1234567890-="


def play(path: str, device: str | None) -> None:
    if shutil.which("aplay"):
        subprocess.Popen(["aplay", "-q"] + (["-D", device] if device else []) + [path])
        return
    try:
        import numpy as np
        import sounddevice as sd

        with wave.open(path, "rb") as w:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            sd.play(data, w.getframerate())
    except Exception as e:  # no audio device is fine; the mouth still moves
        print(f"(no audio: {e})")


def main() -> None:
    ap = argparse.ArgumentParser(description="BMO face rig demo")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--sounds", default="sounds", help="folder with greeting_sounds/ etc.")
    ap.add_argument("--device", default=None, help="ALSA device for aplay, e.g. plughw:2,0")
    ap.add_argument("--supersample", type=int, default=4, help="1 = fastest, 4 = crisp edges (matches the PNG faces)")
    args = ap.parse_args()

    root = tk.Tk()
    root.title("BMO face rig")
    root.configure(bg="black")
    if args.fullscreen:
        root.attributes("-fullscreen", True)
        root.configure(cursor="none")
    label = tk.Label(root, bd=0, highlightthickness=0, bg="black")
    label.pack()
    view = FaceView(label, supersample=args.supersample)
    view.attach()
    view.rig.play_intro()
    schedule = SpeechSchedule()

    names = list(load_presets()["expressions"])
    clips = []
    for sub in ("greeting_sounds", "thinking_sounds", "ack_sounds"):
        clips += sorted(glob.glob(os.path.join(args.sounds, sub, "*.wav")))
    caption = tk.Label(root, font=("Courier New", 12, "bold"), fg="#1a5c2a", bg="#C9E4C3")
    caption.place(relx=0.5, rely=0.98, anchor="s")
    status = {"text": "1-9 faces · space talk · w wake · Esc quit", "until": time.time() + 6}

    def say(_event=None):
        if not clips:
            status.update(text=f"no WAVs under {args.sounds}/", until=time.time() + 3)
            return
        path = random.choice(clips)
        schedule.load_wav(path, start=time.time() + 0.05)
        play(path, args.device)
        status.update(text=os.path.basename(path), until=time.time() + 2)

    def on_key(event):
        if event.keysym == "Escape":
            root.destroy()
        elif event.char and event.char in KEYS and KEYS.index(event.char) < len(names):
            name = names[KEYS.index(event.char)]
            view.rig.set_expression(name)
            status.update(text=name, until=time.time() + 2)
        elif event.char == " ":
            say()
        elif event.char == "w":
            view.rig.play_intro()

    root.bind("<Key>", on_key)
    root.bind("<Button-1>", say)

    def tick():
        view.tick(schedule.poll())
        text = status["text"] if time.time() < status["until"] else f"{view.render_ms:.1f} ms/frame"
        if caption.cget("text") != text:
            caption.config(text=text)
        root.after(33, tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
