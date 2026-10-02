"""Memory Match: twelve cards, six pairs, flip two at a time."""
import math

from PIL import Image

from core.games import art
from core.games.art import C
from core.games.base import Game

ICONS = ("sun", "heart", "star", "moon", "controller", "bmo")
COLS, ROWS = 4, 3
CARD_W, CARD_H = 170, 114
GAP_X, GAP_Y = 16, 15
GRID_X = (art.W - (COLS * CARD_W + (COLS - 1) * GAP_X)) // 2
GRID_Y = 96
SHADOW = 5

MISMATCH_DELAY = 0.8     # a wrong pair stays up this long
FLIP_T = 0.22            # flip animation
POP_T = 0.35             # matched cards bounce
WIN_DELAY = 0.9          # last match -> "You did it" card

OVERLAY_SIZE = (520, 270)
OVERLAY_POS = ((art.W - OVERLAY_SIZE[0]) // 2, GRID_Y + (ROWS * CARD_H + (ROWS - 1) * GAP_Y - OVERLAY_SIZE[1]) // 2)


def card_box(i):
    c, r = i % COLS, i // COLS
    x, y = GRID_X + c * (CARD_W + GAP_X), GRID_Y + r * (CARD_H + GAP_Y)
    return (x, y, x + CARD_W, y + CARD_H)


CARDS = [card_box(i) for i in range(COLS * ROWS)]


# --- icons -------------------------------------------------------------------

def _kawaii(pen, cx, cy, s, sleepy=False):
    """A tiny Adventure Time face: dot eyes and a smile."""
    ink, er, ex = C["ink"], s * 0.045, s * 0.13
    if sleepy:
        for k in (-1, 1):
            art.arc(pen, cx + k * ex - er * 1.6, cy - er * 2, cx + k * ex + er * 1.6, cy + er, 20, 160, ink, 2.6)
    else:
        for k in (-1, 1):
            pen.ellipse(cx + k * ex - er, cy - er * 1.2, cx + k * ex + er, cy + er * 1.2, fill=ink)
    art.arc(pen, cx - s * .08, cy - s * .02, cx + s * .08, cy + s * .12, 20, 160, ink, 2.6)


def _outlined(pen, shapes, fill, lw):
    """Fill a union of shapes with an ink outline: draw it grown in ink, then filled."""
    for grow, col in ((lw, C["ink"]), (0, fill)):
        for kind, args in shapes:
            if kind == "ellipse":
                x0, y0, x1, y1 = args
                pen.ellipse(x0 - grow, y0 - grow, x1 + grow, y1 + grow, fill=col)
            else:                                            # polygon: grow from its centroid
                cx = sum(p[0] for p in args) / len(args)
                cy = sum(p[1] for p in args) / len(args)
                pts = []
                for x, y in args:
                    d = math.hypot(x - cx, y - cy) or 1
                    pts.append((x + (x - cx) / d * grow * 1.15, y + (y - cy) / d * grow * 1.15))
                pen.polygon(pts, fill=col)


def _circle_pts(cx, cy, r, a0, a1, n=48):
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n))
            for k in range(n + 1)]


def icon(pen, kind, cx, cy, s):
    """A card face icon centred at (cx, cy), about `s` px across."""
    ink, lw = C["ink"], 4
    if kind == "sun":
        r = s * 0.27
        for k in range(8):
            a = k * math.pi / 4 + math.pi / 8
            pen.line([(cx + math.cos(a) * r * 1.38, cy + math.sin(a) * r * 1.38),
                      (cx + math.cos(a) * r * 1.78, cy + math.sin(a) * r * 1.78)], ink, 5)
        pen.ellipse(cx - r, cy - r, cx + r, cy + r, fill=C["yellow"], outline=ink, width=lw)
        _kawaii(pen, cx, cy + s * .02, s)
    elif kind == "heart":
        r = s * 0.2
        y0 = cy - s * 0.12
        _outlined(pen, [("ellipse", (cx - 2 * r, y0 - r, cx, y0 + r)),
                        ("ellipse", (cx, y0 - r, cx + 2 * r, y0 + r)),
                        ("poly", [(cx - 1.93 * r, y0 + r * .38), (cx + 1.93 * r, y0 + r * .38),
                                  (cx, y0 + r * 2.55)])], C["red"], lw)
        _kawaii(pen, cx, cy + s * .02, s)
    elif kind == "star":
        pts = []
        for k in range(10):
            a = -math.pi / 2 + k * math.pi / 5
            r = s * (0.48 if k % 2 == 0 else 0.22)
            pts.append((cx + r * math.cos(a), cy + s * .05 + r * math.sin(a)))
        pen.polygon(pts, fill=C["blue"], outline=ink, width=lw)
        _kawaii(pen, cx, cy + s * .06, s * .85)
    elif kind == "moon":
        r = s * 0.38
        ox, oy = cx + s * .06, cy
        dx, dy, r2 = r * .55, -r * .35, r * .82                       # the bite
        bx, by = ox + dx, oy + dy
        away = math.atan2(-dy, -dx)
        outer = [p for p in _circle_pts(ox, oy, r, away - math.pi, away + math.pi, 160)
                 if math.hypot(p[0] - bx, p[1] - by) >= r2]
        inner = [p for p in _circle_pts(bx, by, r2, away + math.pi, away - math.pi, 160)
                 if math.hypot(p[0] - ox, p[1] - oy) <= r]
        pen.polygon(outer + inner, fill=art.mix(C["yellow"], "#FFFFFF", 0.4), outline=ink, width=lw)
        for sx, sy, sr in ((cx + s * .36, cy - s * .30, 7), (cx + s * .30, cy + s * .22, 5)):
            art.sparkle(pen, sx, sy, sr, C["yellow"])
        # sleepy eye + smile on the crescent's fat side
        ex, ey = ox - r * .52, oy + r * .05
        art.arc(pen, ex - 6, ey - 6, ex + 6, ey + 4, 20, 160, ink, 2.6)
        art.arc(pen, ex - 4, ey + 6, ex + 10, ey + 18, 20, 160, ink, 2.6)
    elif kind == "controller":
        w, h = s * 0.95, s * 0.52
        x0, y0 = cx - w / 2, cy - h / 2
        _outlined(pen, [("ellipse", (x0 - s * .04, y0 + h * .2, x0 + w * .4, y0 + h * 1.35)),
                        ("ellipse", (x0 + w * .6, y0 + h * .2, x0 + w + s * .04, y0 + h * 1.35)),
                        ("ellipse", (x0 + w * .1, y0, x0 + w * .9, y0 + h * 1.0))], C["green"], lw)
        pen.rect(x0 + w * .2, y0 + h * .1, x0 + w * .8, y0 + h * .8, fill=C["green"])
        a, b = s * .12, s * .04                                         # D-pad
        dx, dy = x0 + w * .27, cy + h * .08
        pen.rect(dx - a, dy - b, dx + a, dy + b, r=2, fill=C["dpad"], outline=ink, width=2.5)
        pen.rect(dx - b, dy - a, dx + b, dy + a, r=2, fill=C["dpad"], outline=ink, width=2.5)
        pen.rect(dx - b + 1.3, dy - b + 1.3, dx + b - 1.3, dy + b - 1.3, fill=C["dpad"])
        for bx, by, col in ((x0 + w * .72, cy - h * .04, C["red"]), (x0 + w * .84, cy + h * .22, C["blue"])):
            r = s * .065
            pen.ellipse(bx - r, by - r, bx + r, by + r, fill=col, outline=ink, width=2.5)
    else:                                                               # BMO himself
        w, h = s * 0.92, s * 0.74
        art.bmo_face(pen, cx - w / 2, cy - h / 2, w, h, "wink")


# --- sprites -------------------------------------------------------------------

_cache = {}


def _card_sprite(kind):
    """'back', 'face:<icon>' or 'match:<icon>' (CARD_W x CARD_H + SHADOW, RGBA)."""
    if kind in _cache:
        return _cache[kind]

    def draw(pen, w, h):
        h -= SHADOW
        pen.rect(0, SHADOW, w, h + SHADOW, r=16, fill=C["ink"])
        if kind == "back":
            pen.rect(0, 0, w, h, r=16, fill=C["blue"], outline=C["ink"], width=4)
            pen.rect(10, 10, w - 10, h - 10, r=10, outline=art.mix(C["blue"], "#FFFFFF", 0.35), width=3)
            for x, y in ((24, 24), (w - 24, 24), (24, h - 24), (w - 24, h - 24)):
                pen.ellipse(x - 4, y - 4, x + 4, y + 4, fill=C["yellow"])
            cx, cy, r = w / 2, h / 2, 27
            pen.ellipse(cx - r, cy - r, cx + r, cy + r, fill=art.mix(C["blue"], C["ink"], 0.3),
                        outline=C["ink"], width=3)
            pen.text(cx, cy + 3, "?", "title", 40, C["yellow"], anchor="mm")
        else:
            matched = kind.startswith("match:")
            pen.rect(0, 0, w, h, r=16, fill=C["highlight"] if matched else C["card"], outline=C["ink"], width=4)
            icon(pen, kind.split(":", 1)[1], w / 2, h / 2 + 2, 84)
            if matched:
                art.sparkle(pen, w - 20, 20, 11, C["yellow"])
                art.sparkle(pen, 19, h - 19, 7, C["yellow"])
    _cache[kind] = art.sprite(CARD_W, CARD_H + SHADOW, draw)
    return _cache[kind]


def _base():
    if "base" not in _cache:
        def extra(pen):
            for x0, y0, x1, y1 in CARDS:                                # empty slots behind a flip
                pen.rect(x0 + 6, y0 + 6, x1 - 6, y1 - 4, r=14, fill=C["rule"])
        _cache["base"] = art.background("Memory Match", extra)
    return _cache["base"]


def _overlay(moves, best, new_best):
    key = ("over", moves, best, new_best)
    if key not in _cache:
        sub = "That's a new best!" if new_best else f"Best: {best} moves"
        _cache[key] = art.result_card(*OVERLAY_SIZE, "happy", "Yay!", f"You did it in {moves} moves!", sub)
    return _cache[key]


# --- the game ------------------------------------------------------------------

class MemoryMatch(Game):
    """Find the six pairs.  Sound events: flip (a card turns, either way),
    match (a pair found), win (all pairs found)."""

    name = "Memory Match"
    key = "memory"

    def __init__(self, rng=None, now=0.0):
        super().__init__(rng, now)
        self.best = None
        self.new_best = False
        self._new_game(now)

    def _new_game(self, now):
        deck = list(ICONS) * 2
        self.rng.shuffle(deck)
        self.deck = deck
        self.up = []                    # face-up, not yet matched (0..2 cards)
        self.matched = set()
        self.moves = 0
        self.state = "play"
        self.new_best = False
        self._flip_back_at = None
        self._won_at = None
        self._shown_overlay = False
        self._anim = {}                 # card -> (start, kind shown before the flip)
        self._pop = {}                  # card -> start of its "matched" bounce
        self._update_status()

    def _update_status(self):
        if self.state == "won":
            self.status = f"You did it in {self.moves} moves!"
        elif self.moves == 0 and not self.up:
            self.status = "Find the pairs!"
        else:
            self.status = f"Moves {self.moves} · Pairs {len(self.matched) // 2}/{len(ICONS)}"

    def kind(self, i):
        if i in self.matched:
            return "match:" + self.deck[i]
        if i in self.up:
            return "face:" + self.deck[i]
        return "back"

    @property
    def overlay_shown(self):
        return self.state == "won" and self._shown_overlay

    def update(self, now):
        if self._flip_back_at is not None and now >= self._flip_back_at:
            t = self._flip_back_at
            for i in self.up:
                self._anim[i] = (t, "face:" + self.deck[i])
            self.up = []
            self._flip_back_at = None
            self._emit("flip")
            self._update_status()
        self._shown_overlay = self.state == "won" and now >= self._won_at + WIN_DELAY

    def _tap(self, x, y, now):
        if self.state == "won":
            if not self._shown_overlay:
                return
            ox, oy = OVERLAY_POS
            _, boxes = _overlay(self.moves, self.best, self.new_best)
            if art.inside(boxes["again"], x - ox, y - oy):
                self._new_game(now)
            elif art.inside(boxes["done"], x - ox, y - oy):
                self.finished = True
            return
        i = next((k for k, b in enumerate(CARDS) if art.inside(b, x, y)), None)
        if i is None or i in self.matched or i in self.up or len(self.up) >= 2:
            return
        self._anim[i] = (now, "back")
        self.up.append(i)
        self._emit("flip")
        if len(self.up) == 2:
            self.moves += 1
            a, b = self.up
            if self.deck[a] == self.deck[b]:
                self.matched.update(self.up)
                self.up = []
                self._emit("match")
                for k in (a, b):
                    self._pop[k] = now + FLIP_T
                if len(self.matched) == len(self.deck):
                    self.state = "won"
                    self._won_at = now
                    self.new_best = self.best is None or self.moves < self.best
                    self.best = self.moves if self.best is None else min(self.best, self.moves)
                    self._emit("win")
            else:
                self._flip_back_at = now + MISMATCH_DELAY
        self._update_status()

    # --- drawing ------------------------------------------------------------------

    def _animating(self, now):
        return (any(now < t + FLIP_T for t, _ in self._anim.values())
                or any(t <= now < t + POP_T for t in self._pop.values()))

    def _state_key(self, now):
        if self._animating(now):
            return ("anim", now)
        return (tuple(self.kind(i) for i in range(len(self.deck))), self.status, self._shown_overlay,
                any(t > now for t in self._pop.values()))

    def _render(self, now):
        img = _base().copy()
        for i, (x0, y0, _, _) in enumerate(CARDS):
            spr = _card_sprite(self.kind(i))
            sx = sy = 1.0
            anim = self._anim.get(i)
            if anim and now < anim[0] + FLIP_T:
                t = max(0.0, (now - anim[0]) / FLIP_T)
                if t < 0.5:
                    spr = _card_sprite(anim[1])
                sx = abs(1 - 2 * t)
            pop = self._pop.get(i)
            if pop is not None and pop <= now < pop + POP_T:
                sx = sy = 1 + 0.09 * math.sin(math.pi * (now - pop) / POP_T)
            if sx != 1.0 or sy != 1.0:
                w, h = max(1, round(spr.width * sx)), max(1, round(spr.height * sy))
                spr = spr.resize((w, h), Image.Resampling.BILINEAR)
                art.paste(img, spr, x0 + (CARD_W - w) / 2, y0 + (CARD_H + SHADOW - h) / 2)
            else:
                art.paste(img, spr, x0, y0)
        if self.state == "won":
            label = "All pairs found!"
        else:
            label = f"Moves {self.moves}  ·  Pairs {len(self.matched) // 2}/{len(ICONS)}"
        pill = art.pill_sprite(label, 22)
        art.paste(img, pill, art.EXIT_BOX[0] - 16 - pill.width, 43 - pill.height // 2)
        if self._shown_overlay:
            art.paste(img, art.wash(art.W, art.H - GRID_Y + 8), 0, GRID_Y - 8)
            spr, _ = _overlay(self.moves, self.best, self.new_best)
            art.paste(img, spr, *OVERLAY_POS)
        return img
