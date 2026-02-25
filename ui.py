import tkinter as tk
from PIL import Image, ImageTk
import os
import threading
import time

class BotGUI:
    def __init__(self, master):
        self.master = master
        master.title("Pi Assistant")
        # master.attributes('-fullscreen', True)  # Fullscreen logic
        # master.bind('<Escape>', lambda e: master.quit())
        
        self.bg_label = tk.Label(master, bg='black')
        self.bg_label.pack(fill=tk.BOTH, expand=True)
        
        self.status = tk.StringVar(value="Waiting...")
        self.status_label = tk.Label(master, textvariable=self.status, font=('Arial', 24), fg='white', bg='black')
        self.status_label.place(relx=0.5, rely=0.9, anchor='s')
        
        self.state = "idle"
        self.animations = {}
        self.frame_idx = 0
        
        # Load Faces (Pre-existing logic)
        self.load_faces()
        self.start_animation()
        
    def load_faces(self):
        # Scan ./faces/ directory
        base = "./faces"
        if not os.path.exists(base): return 
        
        for state in ["idle", "listening", "thinking", "speaking", "error", "processing"]:
            path = os.path.join(base, state)
            if not os.path.exists(path): continue
            
            self.animations[state] = []
            files = sorted([f for f in os.listdir(path) if f.lower().endswith('.png')])
            for f in files:
                try:
                    img = Image.open(os.path.join(path, f))
                    # Resize logic handled by PIL if needed (800x480)
                    self.animations[state].append(ImageTk.PhotoImage(img))
                except: pass

    def set_state(self, state, msg=None):
        if msg: self.status.set(msg)
        self.state = state
        self.frame_idx = 0
        
    def start_animation(self):
        frames = self.animations.get(self.state, []) or self.animations.get("idle", [])
        if frames:
            self.frame_idx = (self.frame_idx + 1) % len(frames)
            self.bg_label.config(image=frames[self.frame_idx])
            
        speed = 50 if self.state == "speaking" else 500
        self.master.after(speed, self.start_animation)
