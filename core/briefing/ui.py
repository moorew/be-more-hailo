"""The briefing on screen: the sun icon over BMO's face, and the playing layout
(small live face on the left, one card per part on the right).

Pure Pillow, no Tk: the agent pastes what these return into its PhotoImage.
Expensive drawing happens once (icon sprites at start-up, each card when its
part arrives); per frame it's pastes plus a 266 x 160 face render.
"""
import math
import threading
import time

from PIL import Image

from core.briefing import cards

# --- the sun icon --------------------------------------------------------------

POP_S, FADE_S, WIGGLE_S, PRESS_S = 0.45, 0.6, 0.6, 0.18
BOB_PERIOD_S, BOB_PX = 2.0, 4.0
GLOW_PERIOD_S, GLOW_S = 6.0, 1.2
_WIGGLE_ANGLES = (-10, -6, -3, 0, 3, 6, 10)
_GLOW_STEPS = 6


def icon_hit(x, y, win_w, win_h):
    """Is (x, y) in the icon's 96 x 96 tap box (x >= 688, y <= 112 at 800 x 480)?"""
    sx, sy = (win_w or 800) / 800, (win_h or 480) / 480
    return x >= 688 * sx and y <= 112 * sy


def _ease_out_back(t):
    c = 1.70158
    t -= 1
    return 1 + (c + 1) * t ** 3 + c * t ** 2


class IconOverlay:
    """Composites the sun icon onto each rig frame while a briefing is ready.

    show()/hide()/wiggle()/press() may be called from any thread; apply() runs
    on the Tk thread between renderer.render and photo.paste."""

    def __init__(self, center=cards.ICON_CENTER):
        self.cx, self.cy = center
        ready = cards.icon_sprite("ready")
        glow = cards.icon_sprite("glow")
        self._ready = ready
        self._glow = [Image.blend(ready, glow, k / _GLOW_STEPS) for k in range(_GLOW_STEPS + 1)]
        self._pressed = cards.icon_sprite("pressed")
        self._wiggle = {a: ready.rotate(a, resample=Image.Resampling.BICUBIC) for a in _WIGGLE_ANGLES}
        self._shown_at = None     # wall time the icon popped in
        self._hidden_at = None    # wall time the fade began
        self._wiggle_at = None
        self._press_at = None
        self._pop = True

    @property
    def visible(self) -> bool:
        return self._shown_at is not None and self._hidden_at is None

    def show(self, pop=True, now=None):
        if self.visible:
            return
        self._shown_at, self._hidden_at, self._pop = time.time() if now is None else now, None, pop

    def hide(self, fade=True, now=None):
        if self._shown_at is None or self._hidden_at is not None:
            return
        if fade:
            self._hidden_at = time.time() if now is None else now
        else:
            self._shown_at = self._hidden_at = None

    def wiggle(self, now=None):
        if self.visible:
            self._wiggle_at = time.time() if now is None else now

    def press(self, now=None):
        if self.visible:
            self._press_at = time.time() if now is None else now

    def sprite(self, now):
        """(RGBA sprite, dx, dy) for this moment, or None when nothing shows."""
        if self._shown_at is None:
            return None
        alpha = 1.0
        if self._hidden_at is not None:
            alpha = 1 - (now - self._hidden_at) / FADE_S
            if alpha <= 0:
                self._shown_at = self._hidden_at = None
                return None
        t = now - self._shown_at
        if self._press_at is not None and now - self._press_at < PRESS_S:
            img = self._pressed
        elif self._wiggle_at is not None and now - self._wiggle_at < WIGGLE_S:
            w = (now - self._wiggle_at) / WIGGLE_S
            angle = 10 * math.sin(w * 3 * 2 * math.pi) * (1 - w)
            img = self._wiggle[min(_WIGGLE_ANGLES, key=lambda a: abs(a - angle))]
        else:
            g = (t % GLOW_PERIOD_S) / GLOW_S
            k = round(math.sin(math.pi * g) * _GLOW_STEPS) if 0 < g < 1 and t > POP_S else 0
            img = self._glow[k]
        dy = BOB_PX / 2 * math.sin(2 * math.pi * t / BOB_PERIOD_S) if t > POP_S else 0.0
        if self._pop and t < POP_S:
            p = t / POP_S
            base = max(0.05, _ease_out_back(p))
            squash = 0.18 * math.sin(math.pi * p)
            w = max(1, int(img.width * base * (1 + squash)))
            h = max(1, int(img.height * base * (1 - squash)))
            img = img.resize((w, h), Image.Resampling.BILINEAR)
        if alpha < 1:
            img = img.copy()
            img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
        return img, 0, dy

    def apply(self, frame, now=None):
        """Paste the icon onto `frame` (RGB, 800 x 480) in place; returns frame."""
        s = self.sprite(time.time() if now is None else now)
        if s is not None:
            img, dx, dy = s
            frame.paste(img, (int(self.cx - img.width / 2 + dx), int(self.cy - img.height / 2 + dy)), img)
        return frame


# --- the playing layout ----------------------------------------------------------

ENTER_S, SLIDE_S, FADE_CARD_S = 0.4, 0.35, 0.3
EXIT_S = SLIDE_S + ENTER_S          # card slides out, then the face springs back


def _ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


class BriefingView:
    """Draws the playing layout.  With a face (face_view's rig), BMO shrinks
    into the left third and keeps lip-syncing through a second renderer sized
    to the slot, sharing the rig so springs, blinks and speech carry over.
    Without one (PNG faces) the cards fill the width."""

    def __init__(self, face_view=None, size=(800, 480)):
        self.W, self.H = size
        self.fv = face_view
        self.small = None
        if face_view is not None:
            from bmo_face import PillowRenderer
            x0, y0, x1, y1 = cards.FACE_BOX
            self.small = PillowRenderer(face_view.rig.shapes, (x1 - x0, y1 - y0), "stretch", 4)
        self.card_box = cards.CARD_BOX if face_view is not None else cards.CARD_BOX_FULL
        self.bg = Image.new("RGB", size, cards.C["screen"])
        self._lock = threading.Lock()
        self.reset()

    # --- state, set from the playback thread ---
    def reset(self):
        with self._lock:
            # New objects (not .clear()): background draws keep the old ones.
            self.parts, self.keys = [], []
            self.index, self.highlight = None, None
            self.caption = None
            self._cache, self._pending, self._shown = {}, set(), None
            self._started = self._exit_at = None
            self._card_at = None
            self._prev = None          # (card image) fading out
            self._base_key = None
            self._last = None

    def start(self, briefing, now=None):
        with self._lock:
            self.parts = briefing["parts"]
            self.keys = [p["key"] for p in self.parts if p.get("card")]
            self.index = self.highlight = self._exit_at = self._prev = None
            self._cache, self._base_key = {}, None
            self._pending, self._shown = set(), None
            self._started = time.time() if now is None else now
        # Cards are drawn ahead in the background; tick() draws any missing one.
        threading.Thread(target=self._prerender, args=(self._job(),), daemon=True).start()

    def _card_size(self):
        x0, y0, x1, y1 = self.card_box
        return x1 - x0, y1 - y0

    def _card(self, index, highlight, job=None):
        """Draw (or fetch) a card.  `job` is (parts, keys, cache) captured when a
        background draw started, so a draw that outlives its briefing can only
        fill that briefing's (discarded) cache, never the next one's."""
        parts, keys, cache = job or (self.parts, self.keys, self._cache)
        key = (index, highlight)
        img = cache.get(key)
        if img is None:
            part = parts[index]
            card_index = keys.index(part["key"]) if part["key"] in keys else 0
            img = cards.draw_card(part, keys, card_index, self._card_size(), highlight)
            cache[key] = img
        return img

    def _job(self):
        return self.parts, self.keys, self._cache

    def _prerender(self, job):
        parts = job[0]
        try:
            for i, p in enumerate(parts):
                if not p.get("card"):
                    continue
                self._card(i, None, job)
                for m in p.get("marks") or []:
                    self._card(i, m["mark"], job)
        except Exception as e:  # drawing errors surface again in tick()
            print(f"[BRIEFING] Card pre-render failed: {e}")

    def show_part(self, index, caption=None, now=None):
        """Called as part `index` starts playing.  A part with no card keeps the last one."""
        now = time.time() if now is None else now
        with self._lock:
            if self.parts[index].get("card"):
                if self.index is not None and self.index != index:
                    self._prev = self._current_card()
                    self._card_at = now
                elif self.index is None:
                    self._card_at = now
                self.index, self.highlight = index, None
            self.caption = cards.caption_image(caption, (cards.FACE_BOX[2] - cards.FACE_BOX[0], 138)) \
                if caption else None
            self._base_key = None

    def set_highlight(self, mark):
        with self._lock:
            if mark != self.highlight:
                self.highlight = mark
                self._base_key = None

    def finish(self, now=None):
        with self._lock:
            self._exit_at = time.time() if now is None else now

    def finished(self, now=None) -> bool:
        return self._exit_at is not None and (time.time() if now is None else now) - self._exit_at >= EXIT_S

    def _current_card(self):
        """The card to show now.  A highlight variant that isn't drawn yet is
        drawn in the background while the previous one stays up, so a change
        never stalls a frame."""
        if self.index is None:
            return None
        img = self._cache.get((self.index, self.highlight))
        if img is not None:
            self._shown = img
            return img
        if (self.index, None) not in self._cache or getattr(self, "_shown", None) is None:
            self._shown = self._card(self.index, self.highlight)   # first sight: must draw now
            return self._shown
        key = (self.index, self.highlight)
        if key not in self._pending:
            self._pending.add(key)
            threading.Thread(target=self._card, args=(*key, self._job()), daemon=True).start()
        return self._shown

    # --- per frame, on the Tk thread ---
    def _face_image(self, frame_dict, rect):
        """The face drawn into `rect` (x0, y0, x1, y1): small renderer when it's
        the slot, else the full renderer scaled (only during the 0.4 s moves)."""
        x0, y0, x1, y1 = rect
        if (x0, y0, x1, y1) == cards.FACE_BOX:
            return self.small.render(frame_dict)
        full = self.fv.renderer.render(frame_dict)
        size = (max(1, int(x1 - x0)), max(1, int(y1 - y0)))
        return full if size == full.size else full.resize(size, Image.Resampling.BILINEAR)

    def _face_rect(self, now):
        """Face rectangle: springs from full screen into the slot and back."""
        full = (0, 0, self.W, self.H)
        slot = cards.FACE_BOX
        if self._exit_at is not None:
            t = (now - self._exit_at - SLIDE_S) / ENTER_S        # after the card has gone
            k = 1 - _ease_out(t) if t > 0 else 1.0
        else:
            k = _ease_out((now - self._started) / ENTER_S) if self._started else 1.0
        return tuple(round(f + (s - f) * k) for f, s in zip(full, slot))

    def _card_x_offset(self, now):
        if self._started is None:                 # not started (or just reset)
            return self.W - self.card_box[0]
        if self._exit_at is not None:
            return int((self.W - self.card_box[0]) * _ease_out((now - self._exit_at) / SLIDE_S))
        appear = self._started + (ENTER_S if self.fv is not None else 0)
        k = _ease_out((now - appear) / SLIDE_S)
        return int((self.W - self.card_box[0]) * (1 - k))

    def compose(self, frame_dict=None, now=None):
        """The whole 800 x 480 frame for this moment."""
        now = time.time() if now is None else now
        with self._lock:
            card = self._current_card()
            fading = self._prev is not None and self._card_at is not None \
                and now - self._card_at < FADE_CARD_S
            if card is not None and fading:
                card = Image.blend(self._prev, card, (now - self._card_at) / FADE_CARD_S)
            elif self._prev is not None:
                self._prev = None
            dx = self._card_x_offset(now)
            steady = not fading and dx == 0 and self._exit_at is None
            key = (id(card), id(self.caption))
            if steady and self._base_key == key:
                frame = self._base.copy()
            else:
                frame = self.bg.copy()
                if card is not None:
                    x0, y0 = self.card_box[:2]
                    frame.paste(card, (x0 + dx, y0), card)
                if self.caption is not None and self._exit_at is None:
                    frame.paste(self.caption, (cards.FACE_BOX[0], cards.FACE_BOX[3] + 12), self.caption)
                if steady:
                    self._base, self._base_key = frame.copy(), key
            if self.fv is not None and frame_dict is not None:
                rect = self._face_rect(now)
                face = self._face_image(frame_dict, rect)
                frame.paste(face, rect[:2])
        return frame

    def tick(self, speech=None, now=None):
        """Advance the shared rig and return the composed frame (rig layout)."""
        now = time.time() if now is None else now
        frame_dict = None
        if self.fv is not None:
            rig = self.fv.rig
            dt = 1 / 30 if self.fv._last is None else min(0.1, now - self.fv._last)
            self.fv._last = now     # FaceView carries on from here without a jump
            if speech is not None:
                rig.set_speech(speech)
            rig.update(dt)
            frame_dict = rig.frame()
        return self.compose(frame_dict, now)
