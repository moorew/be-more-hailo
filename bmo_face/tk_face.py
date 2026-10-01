"""Tkinter glue: draw a FaceRig into a tk.Label and replay lip-sync in time."""

from __future__ import annotations

import threading
import time

from .lipsync import analyse_wav
from .render import PillowRenderer
from .rig import SILENT, FaceRig


class SpeechSchedule:
    """(play_offset, mouth_open, speech) entries replayed against the wall clock.

    Audio is often produced faster than it plays (agent_hailo pumps Piper into
    aplay's buffer ahead of time), so each chunk is stamped with *when* it will
    be heard and the face reads whatever is playing right now.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._items: list = []
        self._start = None
        self._end = None
        self._speech = dict(SILENT)
        self.mouth_open = 0.0

    def clear(self) -> None:
        with self._lock:
            self._items, self._start, self._end = [], None, None
        self._speech = dict(SILENT)
        self.mouth_open = 0.0

    def add(self, offset: float, mouth_open: float, speech: dict) -> None:
        with self._lock:
            if self._start is None:
                self._start = time.time()
            self._items.append((offset, mouth_open, speech))
            self._end = offset

    def load_wav(self, path: str, start: float | None = None) -> float:
        """Pre-analyse a WAV and schedule it from `start` (default: now). Returns duration."""
        items, duration = analyse_wav(path)
        with self._lock:
            self._items = items
            self._start = start if start is not None else time.time()
            self._end = duration
        return duration

    def poll(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            if self._start is None:
                return self._speech
            elapsed = now - self._start
            latest, onset, consumed = None, False, 0
            while consumed < len(self._items) and self._items[consumed][0] <= elapsed:
                _, self.mouth_open, latest = self._items[consumed]
                onset = onset or latest["onset"]
                consumed += 1
            if consumed:
                del self._items[:consumed]
            end = self._end
        if latest is not None:
            self._speech = {**latest, "onset": onset}
        elif end is not None and elapsed > end + 0.15:
            self._speech = dict(SILENT)
            self.mouth_open = 0.0
        else:
            self._speech = {**self._speech, "onset": False}
        return self._speech


class FaceView:
    """Owns a rig + renderer and paints into a tk.Label via one reusable PhotoImage."""

    def __init__(self, label, size=(800, 480), fit="stretch", supersample=4, shapes=None, presets=None,
                 tile_budget=300_000):
        from PIL import ImageTk  # imported here so the rest of the package works headless

        self.rig = FaceRig(shapes, presets)
        self.renderer = PillowRenderer(self.rig.shapes, size, fit, supersample, tile_budget)
        self.photo = ImageTk.PhotoImage(self.renderer.base)
        self.label = label
        self._last = None
        self.render_ms = 0.0  # smoothed cost of update+render+paste
        # Optional (image, now) -> image hook between render and paste, e.g.
        # the morning-briefing sun icon drawn over the face.
        self.overlay = None

    def attach(self) -> None:
        """Point the label at the rig's image (call when switching back from PNG frames)."""
        self.label.config(image=self.photo)

    def tick(self, speech: dict | None = None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        dt = 1 / 30 if self._last is None else now - self._last
        self._last = now
        t0 = time.perf_counter()
        if speech is not None:
            self.rig.set_speech(speech)
        self.rig.update(dt)
        img = self.renderer.render(self.rig.frame())
        if self.overlay is not None:
            img = self.overlay(img, now)
        self.photo.paste(img)
        ms = (time.perf_counter() - t0) * 1000
        self.render_ms = ms if self.render_ms == 0 else self.render_ms * 0.9 + ms * 0.1
