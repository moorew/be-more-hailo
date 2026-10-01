"""Draw the briefing's cards and the sun icon with Pillow (no Tk).

Matches bmo-morning-briefing/mockups: BMO's palette, 4 px card outlines,
Baloo 2 (800) for titles, Atkinson Hyperlegible for text.  Everything is
drawn at 2x and downsampled, since Pillow's shapes aren't anti-aliased.
Cards are drawn once per part (and again only when the highlighted headline
changes), so the per-frame cost is a paste.
"""
import math
import os
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT_DIR = os.path.join(REPO, "fonts")
SS = 2

C = {
    "screen": "#C9E4C3", "card": "#F4FAF1", "panel": "#E3F0DE", "ink": "#111111",
    "text": "#13302a", "muted": "#3d5a52", "rule": "#B7D3B1", "yellow": "#F2C43D",
    "highlight": "#FFF3C9", "blue": "#2A67B8", "red": "#D8434B", "white": "#FFFFFF",
}
PART_LABELS = {"weather": "Weather", "headlines": "Headlines", "your_day": "Your day"}
HINT = ("Tap card to skip", "tap BMO to stop")

# Layout on the 800 x 480 screen (mockups/2-weather.html).
CARD_BOX = (282, 20, 780, 460)          # beside the small face
CARD_BOX_FULL = (20, 20, 780, 460)      # PNG-face fallback: no face, full width
FACE_BOX = (8, 160, 274, 320)           # 266 x 160 small face
ICON_CENTER = (740, 60)                 # 96 x 96 tap box at x >= 688, y <= 112
ICON_SPRITE = 132                       # sprite incl. glow margin


# --- fonts -------------------------------------------------------------------

_FONT_FILES = {
    "title": ("baloo2/Baloo2[wght].ttf", 800),
    "title_semi": ("baloo2/Baloo2[wght].ttf", 600),
    "body": ("atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf", None),
    "bold": ("atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf", None),
}
_FALLBACK = {"title": "DejaVuSans-Bold.ttf", "title_semi": "DejaVuSans-Bold.ttf",
             "body": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf"}
_font_cache = {}


def font(kind: str, size: float):
    """Card font at `size` px (1x); falls back to DejaVu Sans, then Pillow's default."""
    key = (kind, size)
    if key not in _font_cache:
        path, weight = _FONT_FILES[kind]
        px = int(round(size * SS))
        try:
            f = ImageFont.truetype(os.path.join(FONT_DIR, path), px)
            if weight:
                f.set_variation_by_axes([weight])
        except Exception:
            try:
                f = ImageFont.truetype(_FALLBACK[kind], px)
            except Exception:
                f = ImageFont.load_default(px)
        _font_cache[key] = f
    return _font_cache[key]


# --- drawing helpers (1x coordinates, drawn at SS) -----------------------------

class Pen:
    def __init__(self, img):
        self.img = img
        self.d = ImageDraw.Draw(img)

    @staticmethod
    def _s(*v):
        return [round(x * SS) for x in v]

    def rect(self, x0, y0, x1, y1, r=0, fill=None, outline=None, width=0):
        self.d.rounded_rectangle(self._s(x0, y0, x1, y1), radius=round(r * SS), fill=fill,
                                 outline=outline, width=round(width * SS))

    def ellipse(self, x0, y0, x1, y1, fill=None, outline=None, width=0):
        self.d.ellipse(self._s(x0, y0, x1, y1), fill=fill, outline=outline, width=round(width * SS))

    def line(self, pts, fill, width):
        self.d.line(self._s(*[c for p in pts for c in p]), fill=fill, width=round(width * SS), joint="curve")
        r = width / 2                                   # round caps
        for x, y in (pts[0], pts[-1]):
            self.ellipse(x - r, y - r, x + r, y + r, fill=fill)

    def polygon(self, pts, fill=None, outline=None, width=0):
        self.d.polygon(self._s(*[c for p in pts for c in p]), fill=fill, outline=outline,
                       width=round(width * SS))

    def pieslice(self, x0, y0, x1, y1, start, end, fill=None, outline=None, width=0):
        self.d.pieslice(self._s(x0, y0, x1, y1), start, end, fill=fill, outline=outline,
                        width=round(width * SS))

    def text(self, x, y, s, kind, size, fill, anchor="la"):
        self.d.text(self._s(x, y), s, font=font(kind, size), fill=fill, anchor=anchor)

    @staticmethod
    def width(s, kind, size):
        return font(kind, size).getlength(s) / SS


def _new(w, h, bg=(0, 0, 0, 0)):
    return Image.new("RGBA", (w * SS, h * SS), bg)


def _down(img):
    return img.resize((img.width // SS, img.height // SS), Image.Resampling.LANCZOS)


def _runs(text):
    """'**9:30 a.m.** Stir the soup' -> words, each a list of (text, bold) runs,
    so punctuation right after bold text ("**19°C**,") stays attached."""
    words, cur, bold = [], [], False
    for i, chunk in enumerate(text.split("**")):
        bold = i % 2 == 1
        pieces = chunk.split(" ")
        for j, piece in enumerate(pieces):
            if j > 0 and cur:
                words.append(cur)
                cur = []
            if piece:
                cur.append((piece, bold))
    if cur:
        words.append(cur)
    return words


def _word_w(word, size, kind, bold_kind):
    return sum(Pen.width(t, bold_kind if b else kind, size) for t, b in word)


def wrap(text, size, max_w, max_lines=None, kind="body", bold_kind="bold"):
    """Lay rich text into lines of words; the last kept line gets '…' if cut."""
    lines, cur, cur_w = [], [], 0.0
    space = Pen.width(" ", kind, size)
    for word in _runs(text):
        w = _word_w(word, size, kind, bold_kind)
        if cur and cur_w + space + w > max_w:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append(word)
        cur_w += (space if len(cur) > 1 else 0) + w
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        ell = Pen.width("…", kind, size)
        while last and sum(_word_w(wd, size, kind, bold_kind) for wd in last) + space * len(last) + ell > max_w:
            last.pop()
        if last:
            t, b = last[-1][-1]
            last[-1] = last[-1][:-1] + [(t.rstrip(",;:.") + "…", b)]
    return lines


def draw_lines(pen, x, y, lines, size, fill, line_h, kind="body", bold_kind="bold"):
    space = Pen.width(" ", kind, size)
    for line in lines:
        cx = x
        for word in line:
            for t, bold in word:
                k = bold_kind if bold else kind
                pen.text(cx, y, t, k, size, fill)
                cx += Pen.width(t, k, size)
            cx += space
        y += line_h
    return y


def pill(pen, x, y, label, filled=False, done=False, size=14, right=False):
    """A footer/location pill; returns its width.  `right` anchors at x's right edge."""
    pad = 12 if filled else 10
    w = Pen.width(label, "bold", size) + 2 * pad
    h = size + 14
    x0 = x - w if right else x
    if filled:
        pen.rect(x0, y, x0 + w, y + h, r=h / 2, fill=C["ink"])
        pen.text(x0 + w / 2, y + h / 2, label, "bold", size, C["card"], anchor="mm")
    else:
        pen.rect(x0, y, x0 + w, y + h, r=h / 2, fill=C["rule"] if done else None, outline=C["ink"], width=2)
        pen.text(x0 + w / 2, y + h / 2, label, "bold", size, C["ink"], anchor="mm")
    return w


# --- icons (drawn into a box at x, y of side s) --------------------------------

def _cloud(pen, x, y, s, dy=0.0, fill=C["white"]):
    """A cloud filling roughly the box (x, y, s); outlined by drawing it twice."""
    def shape(grow, col):
        g = grow
        pen.ellipse(x + s * .14 - g, y + s * (.38 + dy) - g, x + s * .50 + g, y + s * (.74 + dy) + g, fill=col)
        pen.ellipse(x + s * .30 - g, y + s * (.18 + dy) - g, x + s * .74 + g, y + s * (.62 + dy) + g, fill=col)
        pen.ellipse(x + s * .55 - g, y + s * (.36 + dy) - g, x + s * .90 + g, y + s * (.74 + dy) + g, fill=col)
        pen.rect(x + s * .30 - g, y + s * (.50 + dy) - g, x + s * .74 + g, y + s * (.74 + dy) + g, fill=col)
    lw = max(2.0, s * 0.075)
    shape(lw, C["ink"])
    shape(0, fill)


def _sun(pen, cx, cy, r, rays=True):
    lw = max(2.0, r * 0.28)
    if rays:
        for k in range(8):
            a = k * math.pi / 4
            pen.line([(cx + math.cos(a) * r * 1.45, cy + math.sin(a) * r * 1.45),
                      (cx + math.cos(a) * r * 1.9, cy + math.sin(a) * r * 1.9)], C["ink"], lw)
    pen.ellipse(cx - r, cy - r, cx + r, cy + r, fill=C["yellow"], outline=C["ink"], width=lw)


def condition_icon(pen, kind, x, y, s=44):
    if kind == "sun":
        _sun(pen, x + s / 2, y + s / 2, s * 0.22)
    elif kind == "partly":
        _sun(pen, x + s * 0.36, y + s * 0.32, s * 0.16)
        _cloud(pen, x + s * 0.12, y + s * 0.12, s * 0.88)
    elif kind == "fog":
        _cloud(pen, x, y, s, dy=-0.12)
        for i, (a, b) in enumerate(((.18, .82), (.28, .72))):
            yy = y + s * (.74 + .12 * i)
            pen.line([(x + s * a, yy), (x + s * b, yy)], C["ink"], max(2.0, s * .07))
    else:
        wet = kind in ("rain", "snow", "storm")
        _cloud(pen, x, y, s, dy=-0.1 if wet else 0)
        if kind == "rain":
            for k in range(3):
                xx = x + s * (.36 + .18 * k)
                pen.line([(xx, y + s * .74), (xx - s * .05, y + s * .88)], C["blue"], max(2.0, s * .07))
        elif kind == "snow":
            for k in range(3):
                xx, yy, r = x + s * (.34 + .18 * k), y + s * .82, s * .045
                pen.ellipse(xx - r, yy - r, xx + r, yy + r, fill=C["ink"])
        elif kind == "storm":
            pen.polygon([(x + s * .52, y + s * .6), (x + s * .40, y + s * .82), (x + s * .52, y + s * .80),
                         (x + s * .46, y + s * .98), (x + s * .64, y + s * .72), (x + s * .52, y + s * .74)],
                        fill=C["yellow"], outline=C["ink"], width=1.5)


def row_icon(pen, kind, x, y, s=30):
    lw = 2.6
    if kind == "reminder":                                  # bell
        pen.polygon([(x + s * .25, y + s * .66), (x + s * .25, y + s * .44), (x + s * .5, y + s * .18),
                     (x + s * .75, y + s * .44), (x + s * .75, y + s * .66), (x + s * .84, y + s * .76),
                     (x + s * .16, y + s * .76)], fill=C["yellow"], outline=C["ink"], width=lw)
        pen.ellipse(x + s * .25, y + s * .18, x + s * .75, y + s * .66, fill=C["yellow"], outline=C["ink"], width=lw)
        pen.rect(x + s * .27, y + s * .42, x + s * .73, y + s * .70, fill=C["yellow"])
        pen.line([(x + s * .25, y + s * .44), (x + s * .25, y + s * .68)], C["ink"], lw)
        pen.line([(x + s * .75, y + s * .44), (x + s * .75, y + s * .68)], C["ink"], lw)
        pen.pieslice(x + s * .40, y + s * .74, x + s * .60, y + s * .94, 0, 180, fill=C["ink"])
    elif kind == "timer":                                   # stopwatch
        pen.ellipse(x + s * .17, y + s * .22, x + s * .83, y + s * .88, fill=C["white"], outline=C["ink"], width=lw)
        pen.line([(x + s * .5, y + s * .38), (x + s * .5, y + s * .55), (x + s * .62, y + s * .63)], C["ink"], lw)
        pen.line([(x + s * .38, y + s * .1), (x + s * .62, y + s * .1)], C["ink"], lw)
    elif kind == "countdown":                               # gift
        pen.rect(x + s * .17, y + s * .42, x + s * .83, y + s * .84, r=1, fill=C["red"], outline=C["ink"], width=lw)
        pen.rect(x + s * .12, y + s * .29, x + s * .88, y + s * .42, fill=C["white"], outline=C["ink"], width=lw)
        pen.line([(x + s * .5, y + s * .29), (x + s * .5, y + s * .84)], C["ink"], lw)
        pen.ellipse(x + s * .30, y + s * .12, x + s * .50, y + s * .30, outline=C["ink"], width=lw)
        pen.ellipse(x + s * .50, y + s * .12, x + s * .70, y + s * .30, outline=C["ink"], width=lw)
    else:                                                   # sun on the horizon
        pen.pieslice(x + s * .2, y + s * .42, x + s * .8, y + s * 1.0, 180, 360, fill=C["yellow"],
                     outline=C["ink"], width=lw)
        pen.line([(x + s * .08, y + s * .71), (x + s * .92, y + s * .71)], C["ink"], lw)
        pen.line([(x + s * .5, y + s * .12), (x + s * .5, y + s * .28)], C["ink"], lw)


def umbrella_badge(pen, x_right, y, size=14):
    label = "Umbrella!"
    w = Pen.width(label, "bold", size) + 20
    h = size + 10
    pen.rect(x_right - w, y, x_right, y + h, r=h / 2, fill=C["blue"])
    pen.text(x_right - w / 2, y + h / 2, label, "bold", size, C["white"], anchor="mm")
    return w


# --- cards ---------------------------------------------------------------------

def _frame(w, h):
    img = _new(w, h)
    pen = Pen(img)
    pen.rect(2, 2, w - 2, h - 2, r=20, fill=C["card"], outline=C["ink"], width=4)
    return img, pen


def _footer(pen, w, h, keys, index):
    """Progress pills (done / current / to come) and the touch hint."""
    y = h - 18 - 30
    x = 24
    for i, key in enumerate(keys):
        x += pill(pen, x, y + (0 if i == index else 2), PART_LABELS.get(key, key),
                  filled=i == index, done=i < index) + 8
    hx = w - 24
    if hx - x > 90:
        pen.text(hx, y + 2, HINT[0], "body", 13, C["muted"], anchor="ra")
        pen.text(hx, y + 18, HINT[1], "body", 13, C["muted"], anchor="ra")


def _title(pen, w, title, tag=None):
    pen.text(24, 18, title, "title", 32, C["ink"])
    if tag:
        size, pad = 15, 12
        tw = Pen.width(tag, "bold", size) + 2 * pad
        x1 = w - 24
        pen.rect(x1 - tw, 22, x1, 22 + size + 12, r=(size + 12) / 2, outline=C["ink"], width=2)
        pen.text(x1 - tw / 2, 22 + (size + 12) / 2, tag, "bold", size, C["ink"], anchor="mm")


def _day_column(pen, x, y, w, label, day, umbrella):
    h = 178
    pen.rect(x, y, x + w, y + h, r=14, fill=C["panel"], outline=C["ink"], width=3)
    condition_icon(pen, day["icon"], x + 14, y + 12, 44)
    pen.text(x + 68, y + 12, label, "title_semi", 18, C["text"])
    desc = wrap(day["desc"], 16, w - 82, max_lines=1)
    draw_lines(pen, x + 68, y + 36, desc, 16, C["text"], 20)
    hi = f"{day['high']}°"
    pen.text(x + 14, y + 66, hi, "title", 34, C["ink"])
    pen.text(x + 14 + Pen.width(hi + " ", "title", 34), y + 76, f"/ {day['low']}°", "title_semi", 22, C["muted"])
    by = y + 118
    pen.rect(x + 14, by, x + w - 14, by + 12, r=6, fill=C["screen"], outline=C["ink"], width=2)
    frac = max(0, min(100, day["rain"])) / 100
    if frac > 0:
        pen.rect(x + 16, by + 2, x + 16 + max(4, (w - 32) * frac), by + 10, r=4, fill=C["blue"])
    pen.text(x + 14, by + 22, f"{day['rain']}% chance of rain", "body", 15, C["text"])
    if umbrella:
        umbrella_badge(pen, x + w - 12, by + 20, 13)


def weather_card(card, keys, index, size):
    w, h = size
    img, pen = _frame(w, h)
    _title(pen, w, "Weather", card.get("location"))
    now = card["now"]
    feels = f", feels like {now['feels']}°C" if now.get("feels") is not None and now["feels"] != now["temp"] else ""
    line = wrap(f"Now: {now['desc'].lower()}, **{now['temp']}°C**{feels}", 20, w - 48, max_lines=1)
    draw_lines(pen, 24, 66, line, 20, C["text"], 24)
    gap = 14
    col_w = (w - 48 - gap) / 2
    wet = card.get("umbrella") or ""
    cols = [("Today", card["today"], "today" in wet)]
    if card.get("tomorrow"):
        cols.append(("Tomorrow", card["tomorrow"], "tomorrow" in wet))
    for i, (label, day, umb) in enumerate(cols):
        _day_column(pen, 24 + i * (col_w + gap), 100, col_w, label, day, umb)
    if card.get("sunrise") and card.get("sunset"):
        pen.text(24, 292, f"Sunrise {card['sunrise']} · Sunset {card['sunset']}", "body", 16, C["muted"])
    _footer(pen, w, h, keys, index)
    return _down(img)


def age_label(published, now_ts):
    if not published:
        return None
    mins = max(0, int((now_ts - published) / 60))
    if mins < 60:
        return "just now" if mins < 5 else f"{mins} min ago"
    hours = mins // 60
    return f"{hours} h ago" if hours < 24 else "yesterday"


def headlines_card(card, keys, index, size, highlight=None, now_ts=None):
    w, h = size
    img, pen = _frame(w, h)
    _title(pen, w, "Headlines")
    now_ts = now_ts or time.time()
    items = card["items"]
    top, bottom = 62, h - 18 - 30 - 10
    # Shrink the type until every headline fits (2 lines each at most).
    for size_t, size_s, lines_max in ((18, 14, 2), (17, 13, 2), (16, 13, 2), (15, 12, 2), (15, 12, 1)):
        text_w = w - 48 - 24 - 30 - 12
        laid = [wrap(it["title"], size_t, text_w, max_lines=lines_max, kind="bold") for it in items]
        lh = size_t * 1.25
        heights = [16 + len(lines) * lh + 2 + size_s + 2 for lines in laid]
        gap = 4
        if sum(heights) + gap * (len(items) - 1) <= bottom - top:
            break
    y = top
    for i, (it, lines, rh) in enumerate(zip(items, laid, heights)):
        on = i == highlight
        if on:
            pen.rect(24, y, w - 24, y + rh, r=12, fill=C["highlight"], outline=C["ink"], width=3)
        cx, cy = 24 + 12 + 15, y + 8 + 15
        if on:
            pen.ellipse(cx - 15, cy - 15, cx + 15, cy + 15, fill=C["ink"])
            pen.text(cx, cy + 1, str(i + 1), "title", 16, C["highlight"], anchor="mm")
        else:
            pen.ellipse(cx - 15, cy - 15, cx + 15, cy + 15, outline=C["ink"], width=3)
            pen.text(cx, cy + 1, str(i + 1), "title", 16, C["ink"], anchor="mm")
        tx = 24 + 12 + 30 + 12
        ty = draw_lines(pen, tx, y + 8, lines, size_t, C["text"], size_t * 1.25, kind="bold")
        meta = it["source"]
        age = age_label(it.get("published"), now_ts)
        if age:
            meta += f" · {age}"
        pen.text(tx, ty + 2, meta, "body", size_s, C["muted"])
        y += rh + gap
    _footer(pen, w, h, keys, index)
    return _down(img)


def _day_row_text(row):
    if row["kind"] == "sun":
        rise, sets = row["text"].replace("Sunrise ", "").split(" · Sunset ")
        return "sun", f"Sunrise **{rise}** · sunset **{sets}**"
    if row["kind"] == "countdown":
        d = row["days"]
        when = "today!" if d == 0 else "tomorrow" if d == 1 else f"in {d} days"
        return "countdown", f"{row['text']} **{when}**"
    if row["text"].lower().startswith("timer is up"):
        return "timer", f"Timer finishes at **{row['time']}**"
    return "reminder", f"**{row['time']}** {row['text']}"


def your_day_card(card, keys, index, size):
    w, h = size
    img, pen = _frame(w, h)
    _title(pen, w, "Your day", card.get("date"))
    # Reminders first, then countdowns, then the sun (the mockup's order).
    order = {"reminder": 0, "timer": 0, "countdown": 1, "sun": 2}
    rows = sorted((_day_row_text(r) for r in card["rows"]), key=lambda kr: order[kr[0]])
    y, bottom = 64, h - 18 - 30 - 8
    row_h = 50
    max_rows = int((bottom - y) // row_h)
    if len(rows) > max_rows:
        rows = rows[:max_rows - 1] + [("reminder", f"…and {len(rows) - max_rows + 1} more")]
    for i, (kind, text) in enumerate(rows):
        row_icon(pen, kind, 24, y + 10, 30)
        lines = wrap(text, 20, w - 48 - 44, max_lines=1)
        draw_lines(pen, 24 + 44, y + 12, lines, 20, C["text"], 24)
        if i < len(rows) - 1:
            pen.line([(24, y + row_h - 1), (w - 24, y + row_h - 1)], C["rule"], 2)
        y += row_h
    _footer(pen, w, h, keys, index)
    return _down(img)


def draw_card(part, keys, index, size, highlight=None, now_ts=None):
    """The card for `part` as an RGBA image of `size`, or None if it has none."""
    card = part.get("card")
    if not card:
        return None
    kind = card["type"]
    if kind == "weather":
        return weather_card(card, keys, index, size)
    if kind == "headlines":
        return headlines_card(card, keys, index, size, highlight, now_ts)
    if kind == "your_day":
        return your_day_card(card, keys, index, size)
    raise ValueError(f"unknown card type {kind!r}")


def caption_image(text, size, font_size=15):
    """Muted path: the part's text, wrapped to fit `size` (RGBA, transparent)."""
    w, h = size
    img = _new(w, h)
    pen = Pen(img)
    for fs in (font_size, 14, 13, 12, 11):
        lines = wrap(text, fs, w - 8)
        if len(lines) * fs * 1.25 <= h:
            break
    else:
        lines = wrap(text, fs, w - 8, max_lines=int(h // (fs * 1.25)))
    draw_lines(pen, 4, 0, lines, fs, C["text"], fs * 1.25)
    return _down(img)


# --- the sun icon ----------------------------------------------------------------

def _icon_glyph(pen, cx, cy, s, sun_fill):
    """The mockup's 48-unit sun-on-the-horizon glyph, centred, `s` px wide."""
    k = s / 48
    x0, y0 = cx - 24 * k, cy - 24 * k
    lw = 4 * k

    def P(x, y):
        return (x0 + x * k, y0 + y * k)
    pen.pieslice(x0 + 10 * k, y0 + 20 * k, x0 + 38 * k, y0 + 48 * k, 180, 360, fill=sun_fill,
                 outline=C["ink"], width=lw)
    pen.line([P(4, 34), P(44, 34)], C["ink"], lw)
    pen.line([P(24, 14), P(24, 8)], C["ink"], lw)
    pen.line([P(12.7, 22.7), P(8.7, 18.7)], C["ink"], lw)
    pen.line([P(35.3, 22.7), P(39.3, 18.7)], C["ink"], lw)
    pen.line([P(14, 41), P(34, 41)], C["ink"], lw)


def icon_sprite(state="ready"):
    """RGBA sprite, ICON_SPRITE square, centred on the icon: ready, glow or pressed."""
    S = ICON_SPRITE
    img = _new(S, S)
    c = S / 2
    if state == "glow":
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        r = (36 + 14) * SS
        g.rounded_rectangle([c * SS - r, c * SS - r, c * SS + r, c * SS + r], radius=30 * SS,
                            fill=(242, 196, 61, 120))
        glow = glow.filter(ImageFilter.GaussianBlur(9 * SS))
        img.alpha_composite(glow)
        pen = Pen(img)
        pen.rect(c - 42, c - 42, c + 42, c + 42, r=26, outline=(242, 196, 61, 115), width=6)
    pen = Pen(img)
    if state == "pressed":
        half, fill, sun, glyph = 33, C["yellow"], C["card"], 44
        pen.rect(c - half, c - half, c + half, c + half, r=18, fill=fill, outline=C["ink"], width=4)
    else:
        half, fill, sun, glyph = 36, C["card"], C["yellow"], 48
        pen.rect(c - half, c - half, c + half, c + half, r=20, fill=fill, outline=C["ink"], width=4)
    _icon_glyph(pen, c, c, glyph, sun)
    return _down(img)
