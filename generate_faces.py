"""
generate_faces.py — BMO face animation generator (2026 edition)

All frames are rendered at 8× super-sampling and downscaled via LANCZOS
for crisp, perfectly anti-aliased curves at 800 × 480 final resolution.
"""

import os
import math
import glob
from PIL import Image, ImageDraw

# ── Colour palette ────────────────────────────────────────────────────────────
BG         = (189, 255, 203)   # BMO screen green
BLACK      = (0,   0,   0  )
WHITE      = (255, 255, 255)
DARK_GREEN = (41,  131,  57)   # mouth cavity dark
TONGUE_COL = (140, 210, 130)   # light-green tongue
RED        = (210,  42,  42)   # heart / ladybug body
PINK       = (255, 145, 195)   # blush / bow
YELLOW     = (255, 215,  48)   # bee abdomen
PALE_BLUE  = (190, 215, 255)   # bee / dragonfly wing
HAT        = ( 55,  55,  65)   # fedora dark grey
HATBAND    = ( 22,  22,  33)   # hat band near-black
GOLD       = (205, 165,  42)   # hat-band accent stripe
WOOD       = (128,  62,  26)   # pipe bowl / stem
SMOKE_COL  = (195, 195, 195)   # pipe smoke rings
ORANGE_RED = (215,  60,  20)   # ladybug body

# ── Canvas / supersampling ────────────────────────────────────────────────────
W, H   = 800, 480
SCALE  = 8          # render at 8×, LANCZOS down-sample to final size
LW     = 12         # base line-width  (screen-space pixels)

# ── Face layout ───────────────────────────────────────────────────────────────
LEX  = 220          # left  eye centre X
REX  = 580          # right eye centre X
EY   = 198          # eye arc-centre Y  (arc opens upward)
ER   = 38           # eye arc radius    (was 18 — much bigger now)
EVY  = 203          # visual centre of U-arc (arc mass sits ~5 px below centre)
MY   = 310          # mouth centre Y
MW   = 114          # mouth span width

# ── Scaling helpers ───────────────────────────────────────────────────────────
def S(v):                  return int(round(v * SCALE))
def SB(x1, y1, x2, y2):   return [S(x1), S(y1), S(x2), S(y2)]
def mkd(p):                os.makedirs(p, exist_ok=True)

def make_face(path, fn):
    img  = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    draw = ImageDraw.Draw(img)
    fn(draw)
    img.resize((W, H), Image.Resampling.LANCZOS).save(path)
    print(f"  {path}")

# ── Low-level primitives ──────────────────────────────────────────────────────

def _arc(draw, cx, cy, r, a0, a1, color=BLACK, w=LW):
    """Arc in screen-space coords, scaled up, with rounded end-caps."""
    cxs, cys, rs, ws = S(cx), S(cy), S(r), S(w)
    draw.arc([cxs-rs, cys-rs, cxs+rs, cys+rs], a0, a1, fill=color, width=ws)
    r_eff = rs - ws / 2
    for a in (a0, a1):
        rad = math.radians(a)
        ex = cxs + r_eff * math.cos(rad)
        ey = cys + r_eff * math.sin(rad)
        c  = ws / 2
        draw.ellipse([ex-c, ey-c, ex+c, ey+c], fill=color)

def _line(draw, x1, y1, x2, y2, color=BLACK, w=LW):
    """Line with rounded caps (screen-space coords, auto-scaled)."""
    ws = S(w)
    p1, p2 = (S(x1), S(y1)), (S(x2), S(y2))
    draw.line([p1, p2], fill=color, width=ws)
    r = ws / 2
    for px, py in (p1, p2):
        draw.ellipse([px-r, py-r, px+r, py+r], fill=color)

def _dot(draw, cx, cy, r, color=BLACK):
    rs = S(r); cxs, cys = S(cx), S(cy)
    draw.ellipse([cxs-rs, cys-rs, cxs+rs, cys+rs], fill=color)

def _oval(draw, x1, y1, x2, y2, fill=None, outline=None, ow=LW):
    draw.ellipse(SB(x1, y1, x2, y2), fill=fill, outline=outline,
                 width=S(ow) if outline else 0)

def _rrect(draw, x1, y1, x2, y2, rad=0, fill=None, outline=None, ow=LW):
    if rad:
        draw.rounded_rectangle(SB(x1, y1, x2, y2), radius=S(rad),
                               fill=fill, outline=outline,
                               width=S(ow) if outline else 0)
    else:
        draw.rectangle(SB(x1, y1, x2, y2), fill=fill, outline=outline,
                       width=S(ow) if outline else 0)

# ── Eye building blocks ───────────────────────────────────────────────────────

def _eye_u(draw, cx, cy=EY, r=ER, blink=0.0, shift=0, shine=True):
    """Standard BMO U-arc eye.  blink: 0=open → 1=closed.  shift=pupil horiz shift."""
    vy = EVY + (cy - EY)
    if blink >= 0.9:
        _line(draw, cx - r, vy, cx + r, vy)
        return
    cxs = cx + shift
    if blink > 0.0:
        cya = cy - int((r / 2) * blink)
        _arc(draw, cxs, cya, r, 325, 215)
    else:
        _arc(draw, cxs, cy, r, 325, 215)
    if shine:
        _dot(draw, cx + int(r * 0.42), cy - int(r * 0.55), max(4, r // 8), WHITE)

def _eye_round(draw, cx, cy=EVY, r=ER, shine=True):
    """Wide-open round eye: white iris + black outline + dark pupil + shine."""
    _oval(draw, cx-r, cy-r, cx+r, cy+r, fill=WHITE, outline=BLACK, ow=LW//2+1)
    pr = max(5, r // 3)
    _dot(draw, cx, cy + pr // 3, pr)
    if shine:
        _dot(draw, cx + pr // 2, cy - pr // 4, max(3, pr // 3), WHITE)

def _eye_happy(draw, cx, cy=EY, shine=True):
    """Inverted-U hat-arch eye for happy expressions."""
    _arc(draw, cx, cy + 14, ER, 180, 360)
    if shine:
        _dot(draw, cx + int(ER * 0.38), cy + 14 - int(ER * 0.3),
             max(4, ER // 8), WHITE)

def _eye_slash_angry(draw, cx):
    """Downward-slanting slash eye (angry). Left: \\  Right: /"""
    tilt = 11
    vy = EVY
    if cx < 400:
        _line(draw, cx - ER, vy + tilt, cx + ER, vy - tilt)
    else:
        _line(draw, cx - ER, vy - tilt, cx + ER, vy + tilt)

def _eye_slash_sad(draw, cx, droop=0):
    """Upward-slanting sad eye (outer corner drags down)."""
    tilt = 10
    vy = EVY + droop
    if cx < 400:
        _line(draw, cx - ER, vy + tilt, cx + ER, vy - tilt)
    else:
        _line(draw, cx - ER, vy - tilt, cx + ER, vy + tilt)

def _eyebrow(draw, cx, cy=EY, angry=True):
    """Thick angled brow above the eye. angry=furrow (\\  /), else sad (/ \\)."""
    by   = cy - ER - 9
    tilt = 9
    bw   = LW + 2
    if angry:
        if cx < 400:
            _line(draw, cx - ER + 5, by + tilt, cx + ER - 5, by - tilt, w=bw)
        else:
            _line(draw, cx - ER + 5, by - tilt, cx + ER - 5, by + tilt, w=bw)
    else:
        if cx < 400:
            _line(draw, cx - ER + 5, by - tilt, cx + ER - 5, by + tilt, w=bw)
        else:
            _line(draw, cx - ER + 5, by + tilt, cx + ER - 5, by - tilt, w=bw)

def _eye_heart(draw, cx, cy=EVY, scale=1.0, color=RED):
    size = 22 * scale
    pts  = []
    for t in range(0, 360, 4):
        r = math.radians(t)
        x = 16 * (math.sin(r) ** 3)
        y = 13 * math.cos(r) - 5 * math.cos(2*r) - 2 * math.cos(3*r) - math.cos(4*r)
        pts.append((S(cx + x * (size / 16)), S(cy - y * (size / 16))))
    draw.polygon(pts, fill=color, outline=BLACK, width=S(3))

def _eye_star(draw, cx, cy=EVY, rot=0):
    outer, inner = 28, 8
    pts = []
    for i in range(8):
        a = math.radians(rot + i * 45)
        r = outer if i % 2 == 0 else inner
        pts.append((S(cx + math.sin(a) * r), S(cy - math.cos(a) * r)))
    draw.polygon(pts, fill=BLACK)

def _eye_x(draw, cx, cy=EVY, sz=17):
    _line(draw, cx - sz, cy - sz, cx + sz, cy + sz)
    _line(draw, cx - sz, cy + sz, cx + sz, cy - sz)

def _eye_closed(draw, cx):
    _line(draw, cx - ER, EVY, cx + ER, EVY)

# ── Mouth building blocks ─────────────────────────────────────────────────────

def _mouth_straight(draw, y=MY, w=MW):
    _line(draw, 399 - w // 2, y, 399 + w // 2, y)

def _mouth_smile(draw, y=MY, w=MW, depth=26):
    _arc(draw, 399, y - depth, w // 2, 45, 135)

def _mouth_frown(draw, y=MY, w=MW, depth=26):
    _arc(draw, 399, y + depth, w // 2, 225, 315)

def _mouth_o(draw, r=24):
    _oval(draw, 399-r, MY-r, 399+r, MY+r, fill=DARK_GREEN, outline=BLACK, ow=LW)

def _mouth_speak(draw, h, w=MW):
    h    = max(14, min(68, h))
    ml   = 399 - w // 2
    mr   = 399 + w // 2
    box  = SB(ml, MY - h // 2, mr, MY + h // 2)
    rad  = S(h // 2)
    draw.rounded_rectangle(box, radius=rad, fill=DARK_GREEN,
                            outline=BLACK, width=S(LW))
    if h > 20:
        th = min(14, h // 3)
        tb = [box[0]+S(LW), box[1]+S(LW), box[2]-S(LW), box[1]+S(th+LW)]
        draw.rounded_rectangle(tb, radius=rad, fill=WHITE)
    if h > 34:
        ty_h = min(24, h // 2)
        tw   = w - 34
        tl   = S(399 - tw // 2)
        tr2  = S(399 + tw // 2)
        tb2  = box[3] - S(LW)
        draw.ellipse([tl, tb2 - S(ty_h), tr2, tb2 + S(ty_h // 2)], fill=TONGUE_COL)
        draw.rounded_rectangle(box, radius=rad, fill=None,
                               outline=BLACK, width=S(LW))

def _mouth_wavy(draw):
    sh = LW // 2
    _arc(draw, 399 - 16 + sh, MY, 16, 180, 360)
    _arc(draw, 399 + 16 - sh, MY, 16,   0, 180)

def _mouth_x(draw, sz=13):
    _line(draw, 399 - sz, MY - sz, 399 + sz, MY + sz)
    _line(draw, 399 - sz, MY + sz, 399 + sz, MY - sz)

def _mouth_tongue(draw):
    _mouth_straight(draw)
    tc, tr = 399 + 20, 16
    _oval(draw, tc-tr, MY, tc+tr, MY+tr*2, fill=TONGUE_COL, outline=BLACK, ow=LW)
    _mouth_straight(draw)

# ── Accessory helpers ─────────────────────────────────────────────────────────

def _blush(draw):
    """Soft pink blush circles on cheeks (happy, football)."""
    _oval(draw, 110, 245, 178, 278, fill=PINK)
    _oval(draw, 622, 245, 690, 278, fill=PINK)

def _z_bubble(draw, cx, cy, sz=15):
    """Speech-bubble style floating Z with white background."""
    pad  = 5
    b1x, b1y = cx - sz - pad, cy - sz - pad
    b2x, b2y = cx + sz + pad, cy + sz + pad
    _rrect(draw, b1x, b1y, b2x, b2y, rad=6, fill=WHITE, outline=BLACK, ow=3)
    m = 4
    _line(draw, cx - sz + m, cy - sz + m, cx + sz - m, cy - sz + m, w=3)
    _line(draw, cx + sz - m, cy - sz + m, cx - sz + m, cy + sz - m, w=3)
    _line(draw, cx - sz + m, cy + sz - m, cx + sz - m, cy + sz - m, w=3)

def _musical_note(draw, nx, ny, bounce=0):
    """Single musical note: filled oval head + stem + flag."""
    _oval(draw, nx, ny + bounce, nx + 11, ny + 9 + bounce, fill=BLACK)
    _line(draw, nx + 11, ny + bounce, nx + 11, ny - 22 + bounce, w=3)
    _line(draw, nx + 11, ny - 22 + bounce, nx + 18, ny - 19 + bounce, w=3)

def _draw_hat(draw):
    """Solid fedora hat with dome crown, band, brim, and outlines."""
    # ── Crown body (tapered trapezoid) ─────────────────────────────────────
    crown_pts = [
        (S(298), S(118)),
        (S(316), S(32)),
        (S(484), S(32)),
        (S(502), S(118)),
    ]
    draw.polygon(crown_pts, fill=HAT)

    # ── Dome top (filled semi-ellipse) ────────────────────────────────────
    draw.pieslice(SB(312, -24, 488, 68), 180, 360, fill=HAT)

    # ── Hat band ──────────────────────────────────────────────────────────
    band_pts = [
        (S(300), S(118)),
        (S(312), S(86)),
        (S(488), S(86)),
        (S(500), S(118)),
    ]
    draw.polygon(band_pts, fill=HATBAND)
    draw.line([S(312), S(86), S(488), S(86)], fill=GOLD, width=S(4))

    # ── Brim: full ellipse, then re-paint the top to merge with crown ─────
    draw.ellipse(SB(195, 108, 605, 155), fill=HAT)
    # Repaint upper half of brim area to merge with crown seamlessly
    draw.rectangle(SB(200, 108, 600, 131), fill=HAT)

    # ── Outlines ──────────────────────────────────────────────────────────
    # Brim visible lower arc — use PIL arc directly on the ellipse bbox so it
    # stays flat (a circular _arc with r=205 would sweep through the face)
    draw.arc(SB(195, 108, 605, 155), start=5, end=175, fill=BLACK, width=S(4))
    # Crown sides
    draw.line([S(298), S(118), S(316), S(32)], fill=BLACK, width=S(4))
    draw.line([S(484), S(32), S(502), S(118)], fill=BLACK, width=S(4))
    # Crown dome
    _arc(draw, 400, 22, 85, 195, 345, color=BLACK, w=4)

def _draw_pipe(draw, smoke=0):
    """Wooden pipe with animated smoke rings."""
    px, py = 452, 318
    # Stem (two-segment slightly curved line)
    _line(draw, px,    py,    px+28, py+18, color=WOOD, w=7)
    _line(draw, px+28, py+18, px+55, py+32, color=WOOD, w=7)
    # Rim outline of stem
    _line(draw, px,    py,    px+28, py+18, color=BLACK, w=2)
    _line(draw, px+28, py+18, px+55, py+32, color=BLACK, w=2)
    # Bowl
    _oval(draw, px+50, py+18, px+84, py+60, fill=WOOD, outline=BLACK, ow=4)
    # Bowl opening (dark circle at top of bowl)
    _dot(draw, px + 67, py + 22, 6, BLACK)
    # Smoke rings that expand and drift upward
    for k in range(min(smoke, 4)):
        r_s = 10 + k * 7
        sy  = py + 12 - k * 16 - smoke * 5
        if sy > 10:
            alpha_col = (210 - k*20, 210 - k*20, 210 - k*20)
            _arc(draw, px + 67, sy, r_s, 190, 530, color=alpha_col, w=4)

def _draw_moustache(draw, twitch=0):
    """Grand handlebar moustache with proper teardrop body and curled tips."""
    mx, my = 399, MY - 26

    # ── Left half ─────────────────────────────────────────────────────────
    # Teardrop body: filled chord (bottom half of a wide ellipse)
    draw.chord(SB(305, my - 22, 400, my + 18), 0, 180, fill=BLACK)
    # Curled tip — thick arc that loops outward (use bigger ellipse, thinner stroke)
    _arc(draw, 282 + twitch, my - 6, 22, 95, 275, color=BLACK, w=5)
    # Outer loop
    _arc(draw, 278 + twitch, my - 10, 30, 80, 260, color=BLACK, w=4)

    # ── Right half (mirror) ───────────────────────────────────────────────
    draw.chord(SB(398, my - 22, 493, my + 18), 0, 180, fill=BLACK)
    _arc(draw, 516 - twitch, my - 6, 22, 265, 445, color=BLACK, w=5)
    _arc(draw, 520 - twitch, my - 10, 30, 280, 460, color=BLACK, w=4)

    # Centre parting divot
    _dot(draw, mx, my - 2, 6, BG)

def _draw_bow(draw):
    """Fabric-looking pink bow for football identity."""
    bx, by = 550, 35
    # Left loop (chord = filled arc segment)
    draw.chord(SB(bx-44, by, bx+2,  by+52), 120, 300, fill=PINK, outline=BLACK, width=S(2))
    # Right loop
    draw.chord(SB(bx-2,  by, bx+44, by+52), 240,  60, fill=PINK, outline=BLACK, width=S(2))
    # Centre knot
    _rrect(draw, bx-9, by+14, bx+9, by+36, rad=4, fill=PINK, outline=BLACK, ow=2)

def _draw_bee(draw, bx, by, wing_phase=0):
    """Cartoon bee: striped abdomen, clear wings, head, antennae."""
    # Abdomen (yellow rounded oval)
    _oval(draw, bx-2, by, bx+46, by+26, fill=YELLOW, outline=BLACK, ow=3)
    # Black stripes
    for sx in (bx+10, bx+22, bx+34):
        draw.rectangle(SB(sx, by+1, sx+7, by+25), fill=BLACK)
    # Cover stripe overflows with outer oval outline
    _oval(draw, bx-2, by, bx+46, by+26, fill=None, outline=BLACK, ow=3)
    # Head (small yellow circle at front)
    _dot(draw, bx - 9, by + 13, 10, YELLOW)
    _dot(draw, bx - 9, by + 13, 10, None)  # placeholder
    _oval(draw, bx-19, by+4, bx+1, by+23, fill=YELLOW, outline=BLACK, ow=2)
    # Eye on head
    _dot(draw, bx - 13, by + 10, 3, BLACK)
    # Stinger
    _line(draw, bx+46, by+13, bx+54, by+13, color=BLACK, w=3)
    # Wings (translucent pale-blue ellipses, offset by phase for flap)
    flap = int(5 * math.sin(wing_phase))
    _oval(draw, bx+8,  by-20+flap, bx+40, by+4+flap,  fill=PALE_BLUE, outline=BLACK, ow=2)
    _oval(draw, bx+12, by-12+flap, bx+36, by+2+flap,  fill=PALE_BLUE, outline=BLACK, ow=1)
    # Antennae
    _line(draw, bx-10, by+8, bx-18, by-8,  color=BLACK, w=2)
    _line(draw, bx-8,  by+7, bx-2,  by-8,  color=BLACK, w=2)
    _dot(draw, bx-18, by-10, 3, BLACK)
    _dot(draw, bx-2,  by-10, 3, BLACK)

def _draw_ladybug(draw, lx, ly, leg_phase=0):
    """Cute cartoon ladybug: red oval, black spots, head, antennae."""
    # Body
    _oval(draw, lx, ly, lx+44, ly+30, fill=RED, outline=BLACK, ow=3)
    # Centre line dividing wing cases
    _line(draw, lx+22, ly+2, lx+22, ly+28, color=BLACK, w=2)
    # Spots (3 per side)
    for sx, sy in [(lx+6, ly+6), (lx+6, ly+17), (lx+13, ly+11),
                   (lx+30, ly+6), (lx+30, ly+17), (lx+36, ly+11)]:
        _dot(draw, sx, sy, 4, BLACK)
    # Head
    _dot(draw, lx - 8, ly + 15, 10, BLACK)
    # Eyes on head
    _dot(draw, lx - 13, ly + 11, 3, WHITE)
    _dot(draw, lx - 13, ly + 18, 3, WHITE)
    # Antennae
    leg_wag = int(3 * math.sin(leg_phase))
    _line(draw, lx-6, ly+8, lx-18, ly-4+leg_wag,  color=BLACK, w=2)
    _line(draw, lx-6, ly+12, lx-14, ly-6-leg_wag, color=BLACK, w=2)
    _dot(draw, lx-18, ly-6+leg_wag,  3, BLACK)
    _dot(draw, lx-14, ly-8-leg_wag,  3, BLACK)
    # Legs (3 on each side, wiggle with phase)
    for k, (lleg_x, lleg_y) in enumerate([(lx+8, ly+30), (lx+20, ly+30), (lx+32, ly+30)]):
        wag = int(4 * math.sin(leg_phase + k * 1.2))
        _line(draw, lleg_x, lleg_y, lleg_x-5, lleg_y+10+wag, color=BLACK, w=2)
        _line(draw, lleg_x, lleg_y, lleg_x+5, lleg_y+10-wag, color=BLACK, w=2)

def _draw_worm(draw, wx, wy, wiggle=0.0):
    """Segmented cartoon worm with cute face."""
    seg_r    = 14
    n_segs   = 6
    seg_gap  = int(seg_r * 1.6)
    # Draw body segments back-to-front (so head is on top)
    for k in range(n_segs, 0, -1):
        sy = wy + int(10 * math.sin(wiggle + k * 0.8))
        sx = wx + k * seg_gap
        # Slight gradient from tail (darker) to head (brighter)
        shade = max(0, 160 - k * 14)
        col   = (shade, 200, shade)
        _dot(draw, sx, sy, seg_r, col)
        _dot(draw, sx, sy, seg_r, None)   # placeholder so outline draws
        _oval(draw, sx-seg_r, sy-seg_r, sx+seg_r, sy+seg_r, fill=col, outline=BLACK, ow=2)
    # Head
    hx = wx + seg_gap // 2
    hy = wy + int(10 * math.sin(wiggle))
    _oval(draw, hx-seg_r-3, hy-seg_r-3, hx+seg_r+3, hy+seg_r+3,
          fill=(60, 210, 60), outline=BLACK, ow=3)
    # Eyes
    _dot(draw, hx - 5, hy - 4, 5, WHITE)
    _dot(draw, hx + 5, hy - 4, 5, WHITE)
    _dot(draw, hx - 4, hy - 5, 3, BLACK)
    _dot(draw, hx + 6, hy - 5, 3, BLACK)
    # Smile
    _arc(draw, hx, hy + 4, 6, 25, 155, color=BLACK, w=2)


# ══════════════════════════════════════════════════════════════════════════════
# ANIMATION GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

def gen_idle(d="faces/idle"):
    mkd(d)
    # Sequence: rest · blink · look-left · rest · look-right · rest · double-blink · look-up
    seq = []
    seq += [(0, 0, 0.0)] * 10          # resting
    seq += [(0, 0, 0.5), (0, 0, 1.0),
            (0, 0, 1.0), (0, 0, 0.5)]  # blink
    seq += [(0, 0, 0.0)] * 4
    seq += [(-k*2, 0, 0.0) for k in range(1, 4)]   # look left
    seq += [(-k*2, 0, 0.0) for k in range(3, 0, -1)]
    seq += [(0, 0, 0.0)] * 4
    seq += [(k*2, 0, 0.0) for k in range(1, 4)]    # look right
    seq += [(k*2, 0, 0.0) for k in range(3, 0, -1)]
    seq += [(0, 0, 0.0)] * 3
    seq += [(0, 0, 0.8), (0, 0, 0.0),
            (0, 0, 0.8), (0, 0, 0.0)]  # double blink
    seq += [(0, -k*2, 0.0) for k in range(1, 3)]   # glance up
    seq += [(0, -k*2, 0.0) for k in range(2, 0, -1)]

    for i, (ox, oy, bl) in enumerate(seq):
        def fn(draw, ox=ox, oy=oy, bl=bl):
            _eye_u(draw, LEX + ox, EY + oy, blink=bl, shift=ox // 2)
            _eye_u(draw, REX + ox, EY + oy, blink=bl, shift=ox // 2)
            _mouth_straight(draw)
        make_face(f"{d}/idle_{i+1:02d}.png", fn)

def gen_speaking(d="faces/speaking"):
    mkd(d)
    # (mouth-open-height, mouth-width) — varied for natural lip-sync feel
    shapes = [
        ( 0, MW), (16, 90), (32, 82), (52, 62), (42, 72),
        (22, 96), (46, 66), (10, 88), (36, 76), (62, 52),
        (26, 92), (42, 62), ( 0, MW), (18, 82), (48, 66),
        (28, 88), (10, 92), (56, 56), (34, 72), ( 0, MW),
    ]
    for i, (h, w) in enumerate(shapes):
        def fn(draw, h=h, w=w):
            # Wide open eyes during speech — round with shine
            _eye_round(draw, LEX, EVY, r=ER - 2)
            _eye_round(draw, REX, EVY, r=ER - 2)
            if h == 0:
                _mouth_straight(draw, w=w)
            else:
                _mouth_speak(draw, h, w=w)
        make_face(f"{d}/speaking_{i+1:02d}.png", fn)

def gen_happy(d="faces/happy"):
    mkd(d)
    offsets = [0, -2, -4, -6, -4, -2, 0, 2]
    for i, off in enumerate(offsets):
        def fn(draw, o=off):
            _eye_happy(draw, LEX)
            _eye_happy(draw, REX)
            _blush(draw)
            _mouth_smile(draw, depth=26 + o)
        make_face(f"{d}/happy_{i+1:02d}.png", fn)

def gen_sad(d="faces/sad"):
    mkd(d)
    droops = [0, 2, 4, 6, 8, 6, 4, 2]
    for i, dr in enumerate(droops):
        def fn(draw, dr=dr):
            _eyebrow(draw, LEX, angry=False)
            _eyebrow(draw, REX, angry=False)
            _eye_slash_sad(draw, LEX, droop=dr // 2)
            _eye_slash_sad(draw, REX, droop=dr // 2)
            _mouth_frown(draw)
            # Teardrop under left eye at peak droop
            if dr >= 6:
                _oval(draw, LEX - 5, EVY + ER + 4,
                      LEX + 5, EVY + ER + 18, fill=(130, 220, 255))
        make_face(f"{d}/sad_{i+1:02d}.png", fn)

def gen_angry(d="faces/angry"):
    mkd(d)
    jitters = [0, -2, 0, 2, 0, -1, 0, 1]
    for i, j in enumerate(jitters):
        def fn(draw, j=j):
            _eyebrow(draw, LEX + j, angry=True)
            _eyebrow(draw, REX - j, angry=True)
            _eye_slash_angry(draw, LEX + j)
            _eye_slash_angry(draw, REX - j)
            _mouth_straight(draw)
        make_face(f"{d}/angry_{i+1:02d}.png", fn)

def gen_surprised(d="faces/surprised"):
    mkd(d)
    # Eyes grow then settle, mouth pulses
    sizes = [ER, ER+4, ER+7, ER+9, ER+7, ER+4, ER+7, ER+9]
    mouths = [30, 33, 36, 40, 36, 33, 36, 40]
    for i, (rs, mr) in enumerate(zip(sizes, mouths)):
        def fn(draw, rs=rs, mr=mr):
            _eye_round(draw, LEX, EVY, r=rs)
            _eye_round(draw, REX, EVY, r=rs)
            _mouth_o(draw, r=mr)
        make_face(f"{d}/surprised_{i+1:02d}.png", fn)

def gen_sleepy(d="faces/sleepy"):
    mkd(d)
    for i in range(10):
        t = i / 9.0
        def fn(draw, i=i, t=t):
            _eye_u(draw, LEX, blink=0.9)
            _eye_u(draw, REX, blink=0.9)
            _mouth_straight(draw)
            # Z bubbles float upward, fading in one by one
            if i >= 2:
                _z_bubble(draw, 605, 175 - i * 10, sz=13)
            if i >= 5:
                _z_bubble(draw, 645, 130 - (i-3) * 10, sz=17)
            if i >= 8:
                _z_bubble(draw, 625, 85 - (i-6) * 10, sz=21)
        make_face(f"{d}/sleepy_{i+1:02d}.png", fn)

def gen_thinking(d="faces/thinking"):
    mkd(d)
    for i in range(12):
        phase = i / 11.0
        off   = int(60 * math.sin(phase * math.pi))   # dot scans left→right
        def fn(draw, i=i, off=off):
            # Half-closed eyes looking slightly upward
            _eye_u(draw, LEX, EY - 5, blink=0.35)
            _eye_u(draw, REX, EY - 5, blink=0.35)
            _mouth_straight(draw)
            # Scanning dot row
            for k in range(3):
                base_x = 355 + k * 30
                cx     = base_x + off // 3
                alpha  = 1.0 - abs(cx - (base_x + 30)) / 60
                r_dot  = max(5, int(9 * alpha))
                _dot(draw, cx, 260, r_dot)
        make_face(f"{d}/thinking_{i+1:02d}.png", fn)

def gen_dizzy(d="faces/dizzy"):
    mkd(d)
    for i in range(6):
        flip = (i % 2 == 0)
        def fn(draw, flip=flip):
            _eye_x(draw, LEX)
            _eye_x(draw, REX)
            _mouth_wavy(draw)
        make_face(f"{d}/dizzy_{i+1:02d}.png", fn)

def gen_cheeky(d="faces/cheeky"):
    mkd(d)
    tongue_off = [10, 16, 22, 18, 12, 6, 2, 6]
    for i, to in enumerate(tongue_off):
        def fn(draw, to=to):
            # Wink: left = round open, right = closed line
            _eye_round(draw, LEX, EVY, r=ER - 2)
            _eye_closed(draw, REX)
            # Mouth with tongue wagging to offset
            _mouth_straight(draw)
            tc, tr = 399 + to, 16
            _oval(draw, tc-tr, MY, tc+tr, MY+tr*2,
                  fill=TONGUE_COL, outline=BLACK, ow=LW)
            _mouth_straight(draw)
        make_face(f"{d}/cheeky_{i+1:02d}.png", fn)

def gen_heart(d="faces/heart"):
    mkd(d)
    scales = [1.0, 1.15, 1.35, 1.5, 1.35, 1.15, 1.0, 0.9]
    for i, sc in enumerate(scales):
        def fn(draw, sc=sc):
            _eye_heart(draw, LEX, EVY, scale=sc)
            _eye_heart(draw, REX, EVY, scale=sc)
            _mouth_smile(draw)
        make_face(f"{d}/heart_{i+1:02d}.png", fn)

def gen_starry(d="faces/starry_eyed"):
    mkd(d)
    for i in range(8):
        rot = i * 11.25
        def fn(draw, rot=rot):
            _eye_star(draw, LEX, EVY, rot=rot)
            _eye_star(draw, REX, EVY, rot=rot)
            _mouth_o(draw, r=20)
        make_face(f"{d}/starry_{i+1:02d}.png", fn)

def gen_confused(d="faces/confused"):
    mkd(d)
    for i in range(6):
        flip = (i % 2 == 0)
        wag  = [0, 1, 0, -1, 0, 1][i]
        def fn(draw, flip=flip, wag=wag):
            # One oversized round eye, one flat line
            _eye_round(draw, LEX, EVY, r=ER + 5)
            _eye_closed(draw, REX)
            # Wavy mouth wobbles
            sh = LW // 2
            if flip:
                _arc(draw, 399 - 16 + sh, MY + wag, 16, 180, 360)
                _arc(draw, 399 + 16 - sh, MY + wag, 16,   0, 180)
            else:
                _arc(draw, 399 - 16 + sh, MY + wag, 16,   0, 180)
                _arc(draw, 399 + 16 - sh, MY + wag, 16, 180, 360)
        make_face(f"{d}/confused_{i+1:02d}.png", fn)

def gen_listening(d="faces/listening"):
    mkd(d)
    for i in range(3):
        def fn(draw):
            _eye_round(draw, LEX, EVY, r=ER)
            _eye_round(draw, REX, EVY, r=ER)
            _mouth_straight(draw)
        make_face(f"{d}/listening_{i+1:02d}.png", fn)

def gen_error(d="faces/error"):
    mkd(d)
    def fn(draw):
        _eye_x(draw, LEX)
        _eye_x(draw, REX)
        _mouth_frown(draw)
    make_face(f"{d}/error_01.png", fn)

def gen_capturing(d="faces/capturing"):
    mkd(d)
    def fn(draw):
        _eye_round(draw, LEX, EVY, r=ER + 6)
        _eye_round(draw, REX, EVY, r=ER + 6)
        _mouth_o(draw, r=26)
    make_face(f"{d}/capturing_01.png", fn)

def gen_warmup(d="faces/warmup"):
    mkd(d)
    def fn(draw):
        _eye_u(draw, LEX, blink=0.5)
        _eye_u(draw, REX, blink=0.5)
        _mouth_straight(draw)
    make_face(f"{d}/warmup_01.png", fn)

# ── Screensaver animations ────────────────────────────────────────────────────

def gen_daydream(d="faces/daydream"):
    mkd(d)
    for i in range(12):
        drift = int(4 * math.sin(i * math.pi / 6))
        by    = 185 - i * 7
        def fn(draw, i=i, drift=drift, by=by):
            _eye_u(draw, LEX, EY - 6 + drift, blink=0.25)
            _eye_u(draw, REX, EY - 6 + drift, blink=0.25)
            _mouth_straight(draw)
            if i >= 2:
                _dot(draw, 618, by + 20, 5)
            if i >= 5:
                _z_bubble(draw, 638, by, sz=10)
            if i >= 8:
                _z_bubble(draw, 650, by - 28, sz=14)
        make_face(f"{d}/daydream_{i+1:02d}.png", fn)

def gen_bored(d="faces/bored"):
    mkd(d)
    offsets = [-8, -6, -3, 0, 3, 6, 8, 6, 3, 0]
    for i, ox in enumerate(offsets):
        def fn(draw, ox=ox):
            _eye_u(draw, LEX, shift=ox)
            _eye_u(draw, REX, shift=ox)
            _mouth_frown(draw, depth=14)
        make_face(f"{d}/bored_{i+1:02d}.png", fn)

def gen_jamming(d="faces/jamming"):
    mkd(d)
    for i in range(10):
        nb = int(6 * math.sin(i * math.pi / 5))
        def fn(draw, i=i, nb=nb):
            _eye_closed(draw, LEX)
            _eye_closed(draw, REX)
            _mouth_smile(draw, depth=30)
            _musical_note(draw, 608 + (i % 3) * 6, 148, bounce=nb)
            if i > 2:
                _musical_note(draw, 648 - (i % 3) * 4, 128, bounce=-nb)
        make_face(f"{d}/jamming_{i+1:02d}.png", fn)

def gen_curious(d="faces/curious"):
    mkd(d)
    for i in range(10):
        big_r = ER + 2 + int(4 * math.sin(i * math.pi / 5))
        sml_r = ER - 6
        def fn(draw, big_r=big_r, sml_r=sml_r):
            _eye_round(draw, LEX, EVY, r=big_r)
            _eye_u(draw, REX, blink=0.3)
            _mouth_straight(draw)
        make_face(f"{d}/curious_{i+1:02d}.png", fn)

def gen_shhh(d="faces/shhh"):
    mkd(d)
    for i in range(8):
        bl  = (4 - abs(i - 4)) * 0.08
        xsz = 11 + int((4 - abs(i - 4)) * 1.5)
        def fn(draw, bl=bl, xsz=xsz):
            _eye_u(draw, LEX, blink=bl)
            _eye_u(draw, REX, blink=bl)
            _mouth_x(draw, sz=xsz)
        make_face(f"{d}/shhh_{i+1:02d}.png", fn)

def gen_football(d="faces/football"):
    mkd(d)
    for i in range(8):
        def fn(draw):
            _eye_happy(draw, LEX)
            _eye_happy(draw, REX)
            _blush(draw)
            _mouth_smile(draw)
            _draw_bow(draw)
        make_face(f"{d}/football_{i+1:02d}.png", fn)

def gen_detective(d="faces/detective"):
    mkd(d)
    for i in range(10):
        ox    = int(10 * math.sin(i * math.pi / 5))   # scanning eyes
        smoke = (i % 5)                                # smoke rings cycle
        def fn(draw, ox=ox, smoke=smoke):
            _draw_hat(draw)
            _eye_u(draw, LEX + ox, EY + 6, blink=0.2)
            _eye_u(draw, REX + ox, EY + 6, blink=0.2)
            _mouth_straight(draw)
            _draw_pipe(draw, smoke=smoke)
        make_face(f"{d}/detective_{i+1:02d}.png", fn)

def gen_sir_mano(d="faces/sir_mano"):
    mkd(d)
    for i in range(8):
        twitch = int(2 * math.sin(i * math.pi / 4))
        def fn(draw, tw=twitch):
            _eye_round(draw, LEX, EVY, r=ER - 2)
            _eye_round(draw, REX, EVY, r=ER - 2)
            _mouth_smile(draw, depth=16)
            _draw_moustache(draw, twitch=tw)
        make_face(f"{d}/sir_mano_{i+1:02d}.png", fn)

def gen_low_battery(d="faces/low_battery"):
    mkd(d)
    for i in range(8):
        flash = (i % 2 == 0)
        def fn(draw, flash=flash):
            _eye_slash_sad(draw, LEX, droop=4)
            _eye_slash_sad(draw, REX, droop=4)
            _mouth_frown(draw)
            red_col = (240, 20, 20) if flash else (100, 10, 10)
            _rrect(draw, 318, 46, 452, 96, fill=WHITE, outline=BLACK, ow=5)
            _rrect(draw, 452, 62, 468, 80, fill=BLACK)
            _rrect(draw, 322, 50, 360, 92, fill=red_col)
        make_face(f"{d}/low_battery_{i+1:02d}.png", fn)

# ── Creature animations ───────────────────────────────────────────────────────

def gen_bee(d="faces/bee"):
    mkd(d)
    for i in range(20):
        bx = 50 + i * 37
        by = 145 + int(32 * math.sin(i * math.pi / 3))
        # Eye gaze tracks bee — proportional horizontal shift
        eye_shift = int((bx - 400) / 18)
        # Surprise grows as bee reaches centre
        centre_dist = abs(bx - 400) / 400
        eye_r = int(ER - 2 + (ER + 4 - (ER - 2)) * (1 - centre_dist))
        wing_phase = i * 1.2
        def fn(draw, bx=bx, by=by, es=eye_shift, er=eye_r, wp=wing_phase):
            _eye_round(draw, LEX + es, EVY, r=er)
            _eye_round(draw, REX + es, EVY, r=er)
            _mouth_o(draw, r=max(16, int(20 * (1 - abs(es) / 30))))
            _draw_bee(draw, bx, by, wing_phase=wp)
        make_face(f"{d}/bee_{i+1:02d}.png", fn)

def gen_ladybug(d="faces/ladybug"):
    mkd(d)
    for i in range(20):
        lx = 30 + i * 38
        # Slight vertical wobble as it crawls
        ly = 345 + int(5 * math.sin(i * math.pi / 2))
        eye_shift = int((lx - 400) / 20)
        leg_phase = i * 0.8
        # BMO grows more curious as ladybug passes
        centre_dist = abs(lx - 400) / 400
        eye_r = int(ER + (ER + 8 - ER) * (1 - centre_dist))
        def fn(draw, lx=lx, ly=ly, es=eye_shift, er=eye_r, lp=leg_phase):
            _eye_round(draw, LEX + es, EVY, r=er)
            _eye_u(draw, REX + es, shift=es)
            _mouth_straight(draw)
            _draw_ladybug(draw, lx, ly, leg_phase=lp)
        make_face(f"{d}/ladybug_{i+1:02d}.png", fn)

def gen_worm(d="faces/worm"):
    mkd(d)
    for i in range(20):
        # Worm enters from right, moves left across lower screen
        wx = 680 - i * 34
        wy = 355 + int(6 * math.sin(i * 0.7))
        wiggle = i * 0.5
        eye_shift = int((wx - 400) / 22)
        # BMO brow rises as worm approaches
        centre_dist = abs(wx - 400) / 400
        blink = 0.15 + 0.3 * (1 - centre_dist)
        def fn(draw, wx=wx, wy=wy, wig=wiggle, es=eye_shift, bl=blink):
            _eye_u(draw, LEX, blink=bl, shift=es)
            _eye_u(draw, REX, blink=bl, shift=es)
            _mouth_straight(draw)
            _draw_worm(draw, wx, wy, wiggle=wig)
        make_face(f"{d}/worm_{i+1:02d}.png", fn)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Generating BMO faces at 8× super-sampling…")

    gen_idle()
    gen_speaking()
    gen_happy()
    gen_sad()
    gen_angry()
    gen_surprised()
    gen_sleepy()
    gen_thinking()
    gen_dizzy()
    gen_cheeky()
    gen_heart()
    gen_starry()
    gen_confused()
    gen_listening()
    gen_error()
    gen_capturing()
    gen_warmup()
    gen_daydream()
    gen_bored()
    gen_jamming()
    gen_curious()
    gen_shhh()
    gen_football()
    gen_detective()
    gen_sir_mano()
    gen_low_battery()
    gen_bee()
    gen_ladybug()
    gen_worm()

    # Clean up any old space-named files that would cause frame jumps
    for f in glob.glob("faces/**/* *.png", recursive=True):
        os.remove(f)
        print(f"  Removed stale: {f}")

    print("Done!")
