"""Running timers as countdown chips over BMO's face ("Pasta 4:32").

Drawn onto each rig frame like the briefing's sun icon, top-left so they
clear the icon (top-right) and the caption.  Each chip is rendered once per
second of change (its text) and pasted every frame, so the cost per frame
is a couple of small pastes.  Only timers show; reminders hours away don't.
"""
import time

from PIL import Image

from core.briefing import cards

MAX_CHIPS = 3
SHOW_WITHIN_S = 12 * 3600      # a "timer" further away than this is really a reminder
ORIGIN = (16, 12)
GAP = 6


def countdown(seconds: float) -> str:
    s = max(0, int(seconds + 0.999))      # 0.2 s left still reads 0:01
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chip_image(label: str, text: str, urgent: bool = False) -> Image.Image:
    """A rounded chip: stopwatch, label, time.  RGBA, drawn at 2x."""
    # 36 px tall: three chips (plus gaps) stay above BMO's eyes (~150 px down).
    size, pad, icon = 17, 10, 22
    lw = cards.Pen.width(label + "  ", "bold", size) if label else 0
    tw = cards.Pen.width(text, "title", size + 2)
    w, h = int(pad + icon + 7 + lw + tw + pad), 36
    img = cards._new(w, h)
    pen = cards.Pen(img)
    fill = cards.C["yellow"] if urgent else cards.C["card"]
    pen.rect(2, 2, w - 2, h - 2, r=(h - 4) / 2, fill=fill, outline=cards.C["ink"], width=3)
    cards.row_icon(pen, "timer", pad - 2, (h - icon) / 2, icon)
    x = pad + icon + 7
    if label:
        pen.text(x, h / 2 + 1, label, "bold", size, cards.C["text"], anchor="lm")
        x += lw
    pen.text(x, h / 2 + 1, text, "title", size + 2, cards.C["ink"], anchor="lm")
    return cards._down(img)


class TimerChips:
    def __init__(self, registry, clock=time.time):
        self.registry = registry
        self.clock = clock
        self._cache = {}
        self._items, self._items_at = [], -1.0

    def _timers(self, now):
        if now - self._items_at >= 0.5:           # the registry is cheap, but not per frame
            self._items_at = now
            self._items = [r for r in self.registry.pending()
                           if r.get("kind", "timer") == "timer" and 0 < r["due"] - now <= SHOW_WITHIN_S]
        return self._items[:MAX_CHIPS]

    def apply(self, frame, now=None):
        """Paste chips onto `frame` (800 x 480 RGB) in place; returns it."""
        now = self.clock() if now is None else now
        x, y = ORIGIN
        for r in self._timers(now):
            left = r["due"] - now
            if left <= 0:
                continue
            label = (r.get("name") or "").capitalize()
            key = (label, countdown(left), left <= 10)
            img = self._cache.get(key)
            if img is None:
                if len(self._cache) > 64:
                    self._cache.clear()
                img = self._cache[key] = chip_image(*key)
            frame.paste(img, (x, y), img)
            y += img.height + GAP
        return frame
