"""Shared drawing for BMO's games: palette, header, exit button, BMO's face,
buttons and the end-of-game card.

Reuses the briefing's Pen (2x supersampled Pillow shapes) and fonts.  Every
piece is drawn once into a sprite (RGBA, 1x) and cached, so a game's frame()
is a background copy plus a few pastes.
"""
import math

from PIL import Image

from core.briefing.cards import SS, C as _BRIEFING_C, Pen, _down, _new, font

W, H = 800, 480

C = dict(_BRIEFING_C)
C.update({
    "green": "#4FAE5A",          # BMO's round green button
    "dpad": "#F2C43D",           # BMO's yellow D-pad
    "teal": "#63C5B4",           # BMO's body
    "teal_dark": "#3F9C8B",
    "mouth": "#396337",          # BMO's mouth / tongue (generate_faces.py)
    "tongue": "#A2B36A",
})

HEADER_H = 84
EXIT_BOX = (712, 10, 788, 76)        # drawn: 76 x 66
EXIT_HIT = (700, 0, W, 90)           # tap target, a little more generous

__all__ = ["SS", "Pen", "font", "W", "H", "C", "HEADER_H", "EXIT_BOX", "EXIT_HIT", "mix", "inside",
           "sprite", "background", "bmo_face", "button", "pill_sprite", "result_card", "arc", "paste", "wash", "sparkle"]


def mix(a, b, t):
    """Blend hex colours a -> b by t (0..1); returns '#rrggbb'."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(pa, pb))


def inside(box, x, y):
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def sprite(w, h, draw):
    """Run draw(pen, w, h) on a 2x transparent canvas; return the 1x RGBA sprite."""
    img = _new(w, h)
    draw(Pen(img), w, h)
    return _down(img)


def arc(pen, x0, y0, x1, y1, start, end, fill, width):
    pen.d.arc(Pen._s(x0, y0, x1, y1), start, end, fill=fill, width=round(width * SS))


# --- BMO ---------------------------------------------------------------------

def bmo_face(pen, x, y, w, h, mood="smile", body=True):
    """BMO's head: teal body, green screen, and a face for `mood`:
    smile, sing, watch, happy, sad, wink."""
    if body:
        pen.rect(x, y, x + w, y + h, r=min(w, h) * 0.16, fill=C["teal"], outline=C["ink"], width=max(2, w * .025))
        m = min(w, h) * 0.12
        sx0, sy0, sx1, sy1 = x + m, y + m, x + w - m, y + h - m
        pen.rect(sx0, sy0, sx1, sy1, r=min(w, h) * 0.1, fill=C["screen"], outline=C["ink"], width=max(1.5, w * .018))
    else:
        sx0, sy0, sx1, sy1 = x, y, x + w, y + h
    sw, sh = sx1 - sx0, sy1 - sy0
    cx = (sx0 + sx1) / 2
    ink = C["ink"]
    lw = max(2.0, sw * 0.045)
    er = max(2.0, sw * 0.055)
    ey = sy0 + sh * 0.40
    ex = sw * 0.22
    look = sw * 0.06 if mood == "watch" else 0
    if mood == "happy":                                      # ^ ^ eyes
        for s in (-1, 1):
            ecx = cx + s * ex
            pen.line([(ecx - er * 1.3, ey + er * .6), (ecx, ey - er * .8), (ecx + er * 1.3, ey + er * .6)], ink, lw)
    elif mood == "sad":                                      # droopy dots
        for s in (-1, 1):
            ecx = cx + s * ex
            pen.ellipse(ecx - er, ey - er * .7, ecx + er, ey + er * 1.1, fill=ink)
            pen.line([(ecx - s * er * 1.1, ey - er * 2.5), (ecx + s * er * 1.5, ey - er * 1.7)], ink, lw * .8)
    elif mood == "wink":
        pen.ellipse(cx - ex - er, ey - er, cx - ex + er, ey + er, fill=ink)
        pen.line([(cx + ex - er * 1.3, ey), (cx + ex + er * 1.3, ey)], ink, lw)
    else:
        for s in (-1, 1):
            ecx = cx + s * ex + look
            pen.ellipse(ecx - er, ey - er * 1.15, ecx + er, ey + er * 1.15, fill=ink)
    my = sy0 + sh * 0.66
    mw = sw * 0.17
    if mood in ("smile", "wink"):
        arc(pen, cx - mw, my - sh * .16, cx + mw, my + sh * .08, 20, 160, ink, lw)
    elif mood == "watch":
        pen.line([(cx - mw * .45 + look, my), (cx + mw * .45 + look, my)], ink, lw)
    elif mood == "sing":
        r = sw * 0.075
        pen.ellipse(cx - r, my - r * 1.15, cx + r, my + r * 1.15, fill=C["mouth"], outline=ink, width=lw * .8)
        pen.ellipse(cx - r * .55, my + r * .1, cx + r * .55, my + r * .9, fill=C["tongue"])
    elif mood == "happy":
        pen.pieslice(cx - mw * 1.25, my - sh * .17, cx + mw * 1.25, my + sh * .17, 0, 180,
                     fill=C["mouth"], outline=ink, width=lw * .8)
        pen.pieslice(cx - mw * .7, my + sh * .03, cx + mw * .7, my + sh * .15, 180, 360, fill=C["tongue"])
    elif mood == "sad":
        arc(pen, cx - mw * .9, my - sh * .02, cx + mw * .9, my + sh * .2, 200, 340, ink, lw)


# --- header ------------------------------------------------------------------

def exit_button(pen):
    x0, y0, x1, y1 = EXIT_BOX
    pen.rect(x0, y0, x1, y1, r=18, fill=C["card"], outline=C["ink"], width=4)
    cx, cy, k = (x0 + x1) / 2, (y0 + y1) / 2, 14
    pen.line([(cx - k, cy - k), (cx + k, cy + k)], C["red"], 8)
    pen.line([(cx - k, cy + k), (cx + k, cy - k)], C["red"], 8)


def background(title, extra=None):
    """The full 800 x 480 static layer: screen green, BMO's head, title, exit X.
    `extra(pen)` draws more static parts (in 1x coordinates) before downsampling."""
    img = _new(W, H, C["screen"])
    pen = Pen(img)
    bmo_face(pen, 20, 16, 64, 52, "smile")
    pen.text(98, 44, title, "title", 36, C["ink"], anchor="lm")
    exit_button(pen)
    if extra:
        extra(pen)
    return _down(img).convert("RGB")


_pill_cache = {}


def pill_sprite(text, size=20, fill=None, ink=None):
    """A rounded status pill with `text` (cached)."""
    key = (text, size, fill, ink)
    if key not in _pill_cache:
        if len(_pill_cache) > 64:
            _pill_cache.clear()
        fill = fill or C["card"]
        ink = ink or C["ink"]
        tw = Pen.width(text, "title_semi", size)
        w, h = int(tw + 44), int(size * 1.9)

        def draw(pen, w, h):
            pen.rect(2, 2, w - 2, h - 2, r=(h - 4) / 2, fill=fill, outline=C["ink"], width=3)
            pen.text(w / 2, h / 2 + 1, text, "title_semi", size, ink, anchor="mm")
        _pill_cache[key] = sprite(w, h, draw)
    return _pill_cache[key]


def button(pen, x0, y0, x1, y1, label, primary=True, size=24):
    """A chunky BMO button with a drop 'shadow' so it looks pressable."""
    pen.rect(x0, y0 + 5, x1, y1 + 5, r=(y1 - y0) / 2, fill=C["ink"])
    pen.rect(x0, y0, x1, y1, r=(y1 - y0) / 2, fill=C["yellow"] if primary else C["card"],
             outline=C["ink"], width=4)
    pen.text((x0 + x1) / 2, (y0 + y1) / 2 + 1, label, "title", size, C["ink"], anchor="mm")


def sparkle(pen, cx, cy, r, fill):
    pts = []
    for k in range(8):
        a = -math.pi / 2 + k * math.pi / 4
        rr = r if k % 2 == 0 else r * 0.32
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    pen.polygon(pts, fill=fill, outline=C["ink"], width=2)


def result_card(w, h, mood, title, line, sub=None):
    """End-of-game card (RGBA sprite) and its buttons' boxes, relative to the
    card: {'again': box, 'done': box}."""
    bw, bh, gap = 190, 62, 20
    by = h - bh - 30
    bx = (w - (bw * 2 + gap)) / 2
    boxes = {"again": (bx, by, bx + bw, by + bh), "done": (bx + bw + gap, by, bx + 2 * bw + gap, by + bh)}

    def draw(pen, w, h):
        pen.rect(4, 8, w - 4, h - 2, r=26, fill=C["ink"])                  # drop shadow
        pen.rect(2, 2, w - 6, h - 8, r=26, fill=C["card"], outline=C["ink"], width=4)
        bmo_face(pen, 30, 26, 108, 86, mood)
        if mood == "happy":
            sparkle(pen, 150, 32, 14, C["yellow"])
            sparkle(pen, 22, 112, 10, C["yellow"])
        tx = 160
        pen.text(tx, 36, title, "title", 44, C["ink"])
        pen.text(tx, 98, line, "bold", 22, C["text"])
        if sub:
            pen.text(tx, 128, sub, "body", 18, C["muted"])
        for key, (x0, y0, x1, y1) in boxes.items():
            button(pen, x0, y0, x1, y1, "Play again" if key == "again" else "Done", primary=key == "again")
    return sprite(w, h, draw), boxes


_wash_cache = {}


def wash(w, h):
    """A translucent screen-green veil that quiets the board under a result card."""
    if (w, h) not in _wash_cache:
        r, g, b = (int(C["screen"][i:i + 2], 16) for i in (1, 3, 5))
        _wash_cache[(w, h)] = Image.new("RGBA", (w, h), (r, g, b, 170))
    return _wash_cache[(w, h)]


def paste(base, spr, x, y):
    base.paste(spr, (int(x), int(y)), spr)

