# core/meter.py — Smooth segmented mic-level meter for the Tkinter GUI
import tkinter as tk
import time

from core.config import MIC_METER_ENABLED


def _lerp_color(c1, c2, t):
    """Linearly interpolate between two '#RRGGBB' hex colors."""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f'#{r:02x}{g:02x}{b:02x}'


def _dim(color, factor=0.12):
    """Return a darkened version of a hex color for unlit segments."""
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return f'#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}'


class MicMeter:
    """Compact segmented LED-style mic meter with smooth interpolation."""

    # Layout — centered wide VU-style meter (mouth width = 97px)
    METER_X      = 348
    METER_Y      = 73
    SEG_W        = 97
    SEG_H        = 12
    SEG_GAP      = 3
    NUM_SEGS     = 22
    PAD          = 3

    # Volume mapping
    VOL_MAX      = 150_000.0

    # Smoothing — separate attack/release for fluid motion
    ATTACK       = 0.38    # fast rise to follow speech onsets
    RELEASE      = 0.08    # slow fall for a fluid, organic decay
    PEAK_HOLD_S  = 1.2     # seconds before peak indicator decays
    PEAK_DECAY   = 0.93
    INTERVAL_MS  = 33      # ~30 FPS

    # Gradient stops: green (bottom) → yellow (mid) → red (top)
    _CLR_LO  = '#22cc55'
    _CLR_MID = '#ddcc22'
    _CLR_HI  = '#ee3333'

    def __init__(self, master):
        self._master = master
        self._vol_raw = 0.0
        self._vol_smooth = 0.0
        self._peak = 0.0
        self._peak_time = 0.0
        self._visible = False
        self._canvas = None
        self._seg_ids = []       # canvas item IDs (index 0 = bottom segment)
        self._peak_id = None
        self._colors_on = []     # bright color per segment
        self._colors_dim = []    # dim color per segment
        self._build_palette()

    # -- palette ---------------------------------------------------------------

    def _build_palette(self):
        """Pre-compute per-segment on/dim colors as a smooth gradient."""
        for i in range(self.NUM_SEGS):
            t = i / max(self.NUM_SEGS - 1, 1)
            if t < 0.55:
                c = _lerp_color(self._CLR_LO, self._CLR_MID, t / 0.55)
            else:
                c = _lerp_color(self._CLR_MID, self._CLR_HI, (t - 0.55) / 0.45)
            self._colors_on.append(c)
            self._colors_dim.append(_dim(c))

    # -- public API ------------------------------------------------------------

    def show(self):
        """Reset state, show the meter, start the render loop."""
        if not MIC_METER_ENABLED:
            return
        self._vol_raw = 0.0
        self._vol_smooth = 0.0
        self._peak = 0.0
        self._visible = True
        self._ensure_canvas()
        # Reset all segments to dim
        for i, sid in enumerate(self._seg_ids):
            self._canvas.itemconfig(sid, fill=self._colors_dim[i])
        self._canvas.itemconfig(self._peak_id, state='hidden')
        self._canvas.place(x=self.METER_X, y=self.METER_Y)
        self._tick()

    def hide(self):
        """Hide the meter overlay and zero the volume."""
        self._visible = False
        self._vol_raw = 0.0
        self._vol_smooth = 0.0
        if self._canvas is not None:
            self._canvas.place_forget()

    def feed(self, vol):
        """Set current raw volume (called from recording callbacks)."""
        self._vol_raw = vol

    # -- internals -------------------------------------------------------------

    def _ensure_canvas(self):
        """Lazily build the canvas and all segment items once."""
        if self._canvas is not None:
            return
        cw = self.SEG_W + self.PAD * 2
        ch = self.NUM_SEGS * (self.SEG_H + self.SEG_GAP) - self.SEG_GAP + self.PAD * 2
        self._canvas = tk.Canvas(
            self._master, width=cw, height=ch,
            bg='black', highlightthickness=0, bd=0)

        # Create segments bottom-up (index 0 = bottom = lowest volume)
        self._seg_ids = []
        for i in range(self.NUM_SEGS):
            row_from_top = self.NUM_SEGS - 1 - i
            y0 = self.PAD + row_from_top * (self.SEG_H + self.SEG_GAP)
            y1 = y0 + self.SEG_H
            x0 = self.PAD
            x1 = x0 + self.SEG_W
            sid = self._canvas.create_rectangle(
                x0, y0, x1, y1, fill=self._colors_dim[i], outline='')
            self._seg_ids.append(sid)

        # Peak hold marker — thin white line across the full segment width
        self._peak_id = self._canvas.create_line(
            self.PAD - 1, 0, self.PAD + self.SEG_W + 1, 0,
            fill='#ffffff', width=1, state='hidden')

    def _tick(self):
        if not self._visible or self._canvas is None:
            return

        now = time.time()
        # Normalize raw volume to 0..1
        target = max(0.0, min(self._vol_raw / self.VOL_MAX, 1.0))

        # Exponential smoothing with separate attack / release
        if target > self._vol_smooth:
            self._vol_smooth += self.ATTACK * (target - self._vol_smooth)
        else:
            self._vol_smooth += self.RELEASE * (target - self._vol_smooth)

        level = self._vol_smooth

        # Peak hold
        if level > self._peak:
            self._peak = level
            self._peak_time = now
        elif now - self._peak_time > self.PEAK_HOLD_S:
            self._peak *= self.PEAK_DECAY

        # Light up segments
        lit = int(level * self.NUM_SEGS + 0.5)
        lit = max(0, min(lit, self.NUM_SEGS))

        for i, sid in enumerate(self._seg_ids):
            if i < lit:
                self._canvas.itemconfig(sid, fill=self._colors_on[i])
            else:
                self._canvas.itemconfig(sid, fill=self._colors_dim[i])

        # Position peak marker
        if self._peak > 0.02:
            peak_seg = min(int(self._peak * self.NUM_SEGS), self.NUM_SEGS - 1)
            row_from_top = self.NUM_SEGS - 1 - peak_seg
            py = self.PAD + row_from_top * (self.SEG_H + self.SEG_GAP) + self.SEG_H // 2
            self._canvas.coords(
                self._peak_id,
                self.PAD - 1, py, self.PAD + self.SEG_W + 1, py)
            self._canvas.itemconfig(self._peak_id, state='normal')
        else:
            self._canvas.itemconfig(self._peak_id, state='hidden')

        self._master.after(self.INTERVAL_MS, self._tick)
