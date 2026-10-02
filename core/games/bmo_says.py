"""BMO Says: BMO plays a growing tune on his four buttons; you play it back."""
from core.games import art
from core.games.art import C
from core.games.base import Game

PAD_NAMES = ("red", "blue", "green", "yellow")      # tone:<i> follows this order
PAD_COLORS = (C["red"], C["blue"], C["green"], C["dpad"])
PAD_ICONS = ("big_circle", "triangle", "small_circle", "cross")   # BMO's own buttons

FACE_BOX = (20, 96, 250, 280)
SCORE_BOX = (20, 294, 250, 468)
PAD_AREA = (270, 96, 780, 468)
PAD_GAP = 14
PAD_MARGIN = 10          # lit sprite's glow margin

LEAD = 0.8               # pause before BMO starts a round
ON, GAP = 0.45, 0.15     # round 1 timing; later rounds speed up
MIN_SPEED = 0.6
SPEED_STEP = 0.05
WIN_PAUSE = 1.1
TAP_FLASH = 0.3


def pad_boxes():
    x0, y0, x1, y1 = PAD_AREA
    w = (x1 - x0 - PAD_GAP) / 2
    h = (y1 - y0 - PAD_GAP) / 2
    out = []
    for i in range(4):
        c, r = i % 2, i // 2
        bx, by = x0 + c * (w + PAD_GAP), y0 + r * (h + PAD_GAP)
        out.append((round(bx), round(by), round(bx + w), round(by + h)))
    return out


PADS = pad_boxes()
OVERLAY_SIZE = (500, 270)
OVERLAY_POS = (PAD_AREA[0] + (PAD_AREA[2] - PAD_AREA[0] - OVERLAY_SIZE[0]) // 2,
               PAD_AREA[1] + (PAD_AREA[3] - PAD_AREA[1] - OVERLAY_SIZE[1]) // 2)


# --- drawing -------------------------------------------------------------------

def _pad(pen, i, x0, y0, x1, y1, lit):
    base = PAD_COLORS[i]
    fill = art.mix(base, "#FFFFFF", 0.22) if lit else art.mix(base, C["ink"], 0.22)
    icon = "#FFFFFF" if lit else art.mix(base, "#FFFFFF", 0.18)
    pen.rect(x0, y0 + 6, x1, y1, r=30, fill=C["ink"])                              # depth
    dy = 4 if lit else 0                                                           # pressed in
    pen.rect(x0, y0 + dy, x1, y1 - 6 + dy, r=30, fill=fill, outline=C["ink"], width=4)
    # a soft shine along the top edge
    pen.rect(x0 + 16, y0 + 12 + dy, x1 - 16, y0 + 24 + dy, r=6,
             fill=art.mix(fill, "#FFFFFF", 0.45 if lit else 0.2))
    cx, cy = (x0 + x1) / 2, (y0 + y1 - 6) / 2 + dy + 4
    s = min(x1 - x0, y1 - y0) * 0.5
    kind = PAD_ICONS[i]
    if kind == "big_circle":
        r = s * 0.5
        pen.ellipse(cx - r, cy - r, cx + r, cy + r, fill=icon, outline=C["ink"], width=4)
    elif kind == "small_circle":
        r = s * 0.34
        pen.ellipse(cx - r, cy - r, cx + r, cy + r, fill=icon, outline=C["ink"], width=4)
    elif kind == "triangle":
        r = s * 0.56
        pen.polygon([(cx, cy - r * .9), (cx + r, cy + r * .72), (cx - r, cy + r * .72)],
                    fill=icon, outline=C["ink"], width=4)
    else:                                                   # D-pad cross
        a, b = s * 0.52, s * 0.18
        pen.polygon([(cx - b, cy - a), (cx + b, cy - a), (cx + b, cy - b), (cx + a, cy - b), (cx + a, cy + b),
                     (cx + b, cy + b), (cx + b, cy + a), (cx - b, cy + a), (cx - b, cy + b), (cx - a, cy + b),
                     (cx - a, cy - b), (cx - b, cy - b)], fill=icon, outline=C["ink"], width=4)
    if lit:                                                 # sparkles
        for sx, sy, sr in ((x1 - 34, y0 + 40, 11), (x0 + 30, y1 - 34, 8)):
            art.sparkle(pen, sx, sy + dy, sr, "#FFFFFF")


_cache = {}


def _base():
    if "base" not in _cache:
        def extra(pen):
            for i, (x0, y0, x1, y1) in enumerate(PADS):
                _pad(pen, i, x0, y0, x1, y1, lit=False)
        _cache["base"] = art.background("BMO Says", extra)
    return _cache["base"]


def _lit(i):
    key = ("lit", i)
    if key not in _cache:
        x0, y0, x1, y1 = PADS[i]
        w, h = x1 - x0 + 2 * PAD_MARGIN, y1 - y0 + 2 * PAD_MARGIN
        m = PAD_MARGIN

        def draw(pen, w, h):
            pen.rect(0, 0, w, h, r=38, fill=(242, 196, 61, 170))           # warm glow
            pen.rect(4, 4, w - 4, h - 4, r=35, fill=(255, 250, 220, 235))
            _pad(pen, i, m, m, w - m, h - m, lit=True)
        _cache[key] = art.sprite(w, h, draw)
    return _cache[key]


def _face(mood):
    key = ("face", mood)
    if key not in _cache:
        x0, y0, x1, y1 = FACE_BOX
        _cache[key] = art.sprite(x1 - x0, y1 - y0, lambda pen, w, h: art.bmo_face(pen, 2, 2, w - 4, h - 4, mood))
    return _cache[key]


def _score(rnd, best):
    key = ("score", rnd, best)
    if key not in _cache:
        x0, y0, x1, y1 = SCORE_BOX

        def draw(pen, w, h):
            pen.rect(2, 2, w - 2, h - 2, r=20, fill=C["card"], outline=C["ink"], width=4)
            pen.text(w / 2, 22, "ROUND", "bold", 17, C["muted"], anchor="mt")
            pen.text(w / 2, 82, str(rnd), "title", 60, C["ink"], anchor="mm")
            pen.rect(24, 120, w - 24, 122, fill=C["rule"])
            pen.text(w / 2, 145, f"Best: round {best}" if best else "Best: —", "bold", 18, C["text"], anchor="mm")
        if len(_cache) > 200:
            for k in [k for k in _cache if k[0] == "score"]:
                del _cache[k]
        _cache[key] = art.sprite(x1 - x0, y1 - y0, draw)
    return _cache[key]


def _overlay(rnd, best, new_best):
    key = ("over", rnd, best, new_best)
    if key not in _cache:
        sub = "That's a new best!" if new_best else f"Best: round {best}"
        _cache[key] = art.result_card(*OVERLAY_SIZE, "sad", "Oops!", f"You got to round {rnd}", sub)
    return _cache[key]


# --- the game ------------------------------------------------------------------

class BMOSays(Game):
    """Simon, BMO style.  Sound events: tone:0..3 (red, blue, green, yellow),
    win (round complete), lose (wrong pad)."""

    name = "BMO Says"
    key = "bmo_says"

    def __init__(self, rng=None, now=0.0):
        super().__init__(rng, now)
        self.best = 0
        self.new_best = False
        self._new_game(now)

    # --- state ------------------------------------------------------------------

    @property
    def round(self):
        return len(self.seq)

    def timing(self):
        """(on, gap) seconds for the current round: a little quicker each round."""
        f = max(MIN_SPEED, 1 - SPEED_STEP * (self.round - 1))
        return ON * f, GAP * f

    def _new_game(self, now):
        self.seq = [self.rng.randrange(4)]
        self.new_best = False
        self._flash = (None, 0.0)
        self._start_show(now + LEAD)

    def _start_show(self, t0):
        self.state = "show"
        self.t0 = t0
        self.pos = 0
        self._toned = -1
        self.status = "Watch BMO!"

    def update(self, now):
        if self.state == "won" and now >= self._next_at:
            self.seq.append(self.rng.randrange(4))
            self._start_show(self._next_at + 0.25)
        if self.state == "show" and now >= self.t0:
            on, gap = self.timing()
            idx = int((now - self.t0) // (on + gap))
            if idx >= len(self.seq):
                self.state = "input"
                self.status = "Your turn!"
            elif idx > self._toned:                     # only the current note, never a backlog
                self._toned = idx
                self._emit(f"tone:{self.seq[idx]}")

    def lit_pad(self, now):
        """The pad lit at `now`, or None."""
        if self.state == "show":
            if now < self.t0:
                return None
            on, gap = self.timing()
            idx, into = divmod(now - self.t0, on + gap)
            return self.seq[int(idx)] if idx < len(self.seq) and into < on else None
        pad, until = self._flash
        return pad if now < until else None

    def _mood(self, now):
        if self.state == "lost":
            return "sad"
        if self.state == "won":
            return "happy"
        if self.state == "show":
            return "sing" if self.lit_pad(now) is not None else "watch"
        return "smile"

    # --- input --------------------------------------------------------------------

    def _tap(self, x, y, now):
        if self.state == "lost":
            ox, oy = OVERLAY_POS
            _, boxes = _overlay(self.round, self.best, self.new_best)
            if art.inside(boxes["again"], x - ox, y - oy):
                self._new_game(now)
            elif art.inside(boxes["done"], x - ox, y - oy):
                self.finished = True
            return
        if self.state != "input":
            return                                       # BMO is playing (or celebrating)
        pad = next((i for i, b in enumerate(PADS) if art.inside(b, x, y)), None)
        if pad is None:
            return
        self._flash = (pad, now + TAP_FLASH)
        self._emit(f"tone:{pad}")
        if pad != self.seq[self.pos]:
            self._emit("lose")
            self.state = "lost"
            self.new_best = self.round > self.best
            self.best = max(self.best, self.round)
            self.status = f"Oops! You got to round {self.round}"
            return
        self.pos += 1
        if self.pos == len(self.seq):
            self._emit("win")
            self.state = "won"
            self._next_at = now + WIN_PAUSE
            self.status = f"Yay! Round {self.round} done!"

    # --- drawing ------------------------------------------------------------------

    def _state_key(self, now):
        return (self.state, self.lit_pad(now), self._mood(now), self.status, self.round, self.best)

    def _render(self, now):
        img = _base().copy()
        lit = self.lit_pad(now)
        if lit is not None and self.state != "lost":
            x0, y0, _, _ = PADS[lit]
            art.paste(img, _lit(lit), x0 - PAD_MARGIN, y0 - PAD_MARGIN)
        art.paste(img, _face(self._mood(now)), FACE_BOX[0], FACE_BOX[1])
        art.paste(img, _score(self.round, self.best), SCORE_BOX[0], SCORE_BOX[1])
        label = "Oops!" if self.state == "lost" else self.status
        pill = art.pill_sprite(label, 22, fill=C["yellow"] if self.state == "input" else C["card"])
        art.paste(img, pill, art.EXIT_BOX[0] - 16 - pill.width, 43 - pill.height // 2)
        if self.state == "lost":
            x0, y0, x1, y1 = PAD_AREA
            art.paste(img, art.wash(x1 - x0 + 8, y1 - y0 + 8), x0 - 4, y0 - 4)
            spr, _ = _overlay(self.round, self.best, self.new_best)
            art.paste(img, spr, *OVERLAY_POS)
        return img


__all__ = ["BMOSays", "PADS", "PAD_NAMES"]
