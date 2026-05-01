#!/usr/bin/env python3
"""Generate BMO face animation frames from SVG assets in svg_faces/.

Each SVG is normalised so the face content is centred in the output and
faces that are very large (ooooooh, heart eyes, shocked) are gently scaled
down to keep expressions comparable in size.  Bounce / shake animations are
specified in output pixels and converted to SVG-viewBox units automatically.
"""

import glob, io, math, os, re, shutil
import xml.etree.ElementTree as ET
import cairosvg
import numpy as np
from PIL import Image

OUT_W, OUT_H   = 800, 480
SUPERSAMPLE    = 2
SVG_DIR        = "svg_faces"
NS             = "http://www.w3.org/2000/svg"
BMO_BG         = "#C9E4C3"
BMO_BG_RGB     = (201, 228, 195)

ET.register_namespace("", NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

# Maximum content size (px in output) before we zoom out to normalise.
# Values chosen so "normal" expressions (smile, hmmm, tired…) stay at 1×
# while large ones (heart eyes, ooooooh, shocked) shrink gently.
MAX_W_PX = 620
MAX_H_PX = 360

# ── Core render / IO helpers ──────────────────────────────────────────────────

def _read(name: str) -> str:
    with open(f"{SVG_DIR}/{name}", encoding="utf-8") as f:
        return f.read()

def _render(svg_text: str, ss: int = SUPERSAMPLE) -> Image.Image:
    """Render SVG at native resolution (×ss) → resize to OUT_W × OUT_H."""
    png = cairosvg.svg2png(
        bytestring=svg_text.encode(),
        output_width=1280 * ss, output_height=720 * ss,
    )
    img = Image.open(io.BytesIO(png))
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, BMO_BG_RGB)
        bg.paste(img.convert("RGB"), mask=img.split()[3])
        img = bg
    else:
        img = img.convert("RGB")
    return img.resize((OUT_W, OUT_H), Image.LANCZOS)

def _save(img: Image.Image, directory: str, n: int) -> None:
    os.makedirs(directory, exist_ok=True)
    stem = os.path.basename(directory)
    img.save(f"{directory}/{stem}_{n:02d}.png")

# ── ViewBox normalisation ─────────────────────────────────────────────────────

_VB_CACHE: dict[str, str] = {}

def _content_bbox(svg_text: str):
    """Return (x1, y1, x2, y2) bounding box of non-bg content in output px."""
    img = _render(svg_text, ss=1)
    arr = np.array(img)
    bg  = np.array(BMO_BG_RGB, dtype=int)
    mask = ~np.all(np.abs(arr.astype(int) - bg) < 20, axis=2)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if not len(rows):
        return None
    return int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())

def _compute_vb(name: str) -> str:
    """Compute a normalised viewBox: centres the face and limits max size."""
    svg_text = _read(name)
    bbox = _content_bbox(svg_text)
    if bbox is None:
        return "0 0 1280 720"

    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1
    cx_px = (x1 + x2) / 2
    cy_px = (y1 + y2) / 2

    # Only scale DOWN (never upscale small faces)
    scale = min(MAX_W_PX / w, MAX_H_PX / h, 1.0)

    # Face centre in SVG coordinate space
    face_cx = cx_px * 1280 / OUT_W
    face_cy = cy_px * 720  / OUT_H

    # ViewBox: zoomed-out by 1/scale, centred on the face
    vb_w = 1280 / scale
    vb_h = 720  / scale
    vb_x = face_cx - vb_w / 2
    vb_y = face_cy - vb_h / 2

    return f"{vb_x:.2f} {vb_y:.2f} {vb_w:.2f} {vb_h:.2f}"

def _get_vb(name: str) -> str:
    if name not in _VB_CACHE:
        _VB_CACHE[name] = _compute_vb(name)
    return _VB_CACHE[name]

def _apply_vb(svg_text: str, vb: str, dy_px: float = 0, dx_px: float = 0) -> str:
    """Replace viewBox and optionally add bounce/shift offsets (in output px)."""
    parts = list(map(float, vb.split()))
    # dy_px > 0 → content shifts DOWN → vb_y decreases
    # dx_px > 0 → content shifts RIGHT → vb_x decreases
    parts[1] -= dy_px * parts[3] / OUT_H
    parts[0] -= dx_px * parts[2] / OUT_W
    new_vb = " ".join(f"{p:.2f}" for p in parts)
    return re.sub(r'viewBox="[^"]*"', f'viewBox="{new_vb}"', svg_text)

# ── Animated render functions ─────────────────────────────────────────────────

def _svg_render(name: str, dy_px: float = 0, dx_px: float = 0) -> Image.Image:
    """Render SVG with normalised viewBox + optional bounce/shake (px)."""
    return _render(_apply_vb(_read(name), _get_vb(name), dy_px, dx_px))

def _find_eyes(root) -> list:
    """Return up to 2 fill=black ellipses that look like eyes."""
    eyes = [
        e for e in root.iter(f"{{{NS}}}ellipse")
        if e.get("fill") == "black"
        and float(e.get("rx", 0)) > 15
        and float(e.get("ry", 0)) > 15
    ]
    return eyes[:2]

def _blink_render(name: str, factor: float,
                  dy_px: float = 0, dx_px: float = 0) -> Image.Image:
    """Render with blink (0=open, 1=closed) + optional bounce/shake."""
    tree = ET.parse(f"{SVG_DIR}/{name}")
    root = tree.getroot()

    # Apply normalised + offset viewBox
    svg_text = _apply_vb(
        ET.tostring(root, encoding="unicode"),
        _get_vb(name), dy_px, dx_px,
    )
    # Re-parse to get modified viewBox on the root element
    root2 = ET.fromstring(svg_text)

    # Shrink eye ry
    for eye in _find_eyes(root2):
        ry = float(eye.get("ry"))
        eye.set("ry", str(max(1.5, ry * (1 - factor * 0.97))))

    return _render('<?xml version="1.0"?>\n' + ET.tostring(root2, encoding="unicode"))

def _composite_critter(critter_name: str, critter_w: float, critter_h: float,
                        x: float, y: float) -> Image.Image:
    """Render critter SVG onto BMO green background at scaled position."""
    body = _read(critter_name)
    vb = re.search(r'viewBox="0 0 (\S+) (\S+)"', body)
    orig_w = float(vb.group(1)) if vb else 578
    orig_h = float(vb.group(2)) if vb else 584
    inner  = re.sub(r'^.*?<svg[^>]*>', '', body, flags=re.DOTALL)
    inner  = re.sub(r'</svg>\s*$', '', inner.strip())
    sx, sy = critter_w / orig_w, critter_h / orig_h
    svg = (
        f'<svg width="1280" height="720" viewBox="0 0 1280 720" '
        f'xmlns="http://www.w3.org/2000/svg" fill="none">\n'
        f'<rect width="1280" height="720" fill="{BMO_BG}"/>\n'
        f'<g transform="translate({x:.1f},{y:.1f}) scale({sx:.5f},{sy:.5f})">\n'
        f'{inner}\n</g>\n</svg>'
    )
    return _render(svg)

# ── Face generators ───────────────────────────────────────────────────────────

def gen_idle(d="faces/idle"):
    # 75 frames @ 120 ms = 9-second cycle.
    # ~8 s open eyes, then two quick blinks, then open again.
    open_f = _blink_render("smile.svg", 0)
    half_f = _blink_render("smile.svg", 0.55)
    shut_f = _blink_render("smile.svg", 0.97)
    frames = (
        [open_f] * 64 +
        [half_f, shut_f, half_f,   # first blink
         open_f,                   # tiny gap between blinks
         half_f, shut_f, half_f,   # second blink
         open_f, open_f, open_f, open_f]
    )
    for i, img in enumerate(frames, 1):
        _save(img, d, i)

def gen_speaking(d="faces/speaking"):
    # 12 frames ordered closed→open.  Only the mouth zone is blended so the
    # eyes (from smile.svg) stay perfectly stable — no ghosting from the two
    # different SVGs having eyes at slightly different positions.
    img_c = _svg_render("smile.svg")
    img_o = _svg_render("open mouth.svg")
    arr_c = np.array(img_c).astype(float)
    arr_o = np.array(img_o).astype(float)

    # Vertical gradient mask: 0 = use closed face, 1 = use open mouth.
    # Transition from 54 % to 68 % of image height (below eyes, into mouth).
    blend_start = int(OUT_H * 0.54)
    blend_end   = int(OUT_H * 0.68)
    ys   = np.arange(OUT_H)
    ramp = np.clip((ys - blend_start) / (blend_end - blend_start), 0.0, 1.0)
    mask = ramp[:, None, None]  # (H, 1, 1) → broadcasts over (H, W, 3)

    factors = [0.0, 0.0, 0.10, 0.22, 0.38, 0.55, 0.70, 0.82, 0.92, 1.0, 1.0, 1.0]
    os.makedirs(d, exist_ok=True)
    for i, f in enumerate(factors, 1):
        blended = (arr_c * (1 - mask * f) + arr_o * (mask * f)).astype(np.uint8)
        _save(Image.fromarray(blended), d, i)

def gen_thinking(d="faces/thinking"):
    for i in range(1, 9):
        dy = round(4 * math.sin(i * math.pi / 4))
        _save(_svg_render("hmmm.svg", dy_px=dy), d, i)

def gen_listening(d="faces/listening"):
    # 36 frames @ 120 ms = 4.3-second cycle, one slow blink at the end
    open_f = _blink_render("smile.svg", 0)
    half_f = _blink_render("smile.svg", 0.55)
    shut_f = _blink_render("smile.svg", 0.97)
    frames = [open_f] * 32 + [half_f, shut_f, half_f, open_f]
    for i, img in enumerate(frames, 1):
        _save(img, d, i)

def gen_happy(d="faces/happy"):
    for i in range(1, 9):
        dy = round(6 * math.sin(i * math.pi / 4))
        _save(_svg_render("happy.svg", dy_px=dy), d, i)

def gen_sad(d="faces/sad"):
    for i in range(1, 9):
        dy = round(2 * math.sin(i * math.pi / 8))
        b  = 0.9 if i == 6 else 0
        if b:
            _save(_blink_render("frown.svg", b, dy_px=dy), d, i)
        else:
            _save(_svg_render("frown.svg", dy_px=dy), d, i)

def gen_angry(d="faces/angry"):
    shakes = [0, 6, -6, 8, -8, 4, -4, 0]
    for i, dx in enumerate(shakes, 1):
        _save(_svg_render("confused and mad.svg", dx_px=dx), d, i)

def gen_surprised(d="faces/surprised"):
    for i in range(1, 5):
        dy = round(8 * math.sin(i * math.pi / 2))
        _save(_svg_render("shocked and wonder.svg", dy_px=dy), d, i)

def gen_sleepy(d="faces/sleepy"):
    blinks = [0.1, 0.3, 0.6, 0.9, 0.97, 0.9, 0.6, 0.3]
    for i, b in enumerate(blinks, 1):
        _save(_blink_render("tired and happy.svg", b), d, i)

def gen_dizzy(d="faces/dizzy"):
    for i in range(1, 5):
        dx = round(5 * math.sin(i * math.pi / 2))
        _save(_svg_render("dizzy.svg", dx_px=dx), d, i)

def gen_cheeky(d="faces/cheeky"):
    blinks = [0, 0, 0, 0, 0.5, 0.97, 0.5, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_render("cheeky.svg", b), d, i)

def gen_heart(d="faces/heart"):
    # Pulse: zoom viewBox in/out ±3 %
    vb = _get_vb("heart eyes.svg")
    parts_base = list(map(float, vb.split()))
    for i in range(1, 7):
        factor = 1 + 0.03 * math.sin(i * math.pi / 3)
        p = parts_base.copy()
        dw = (p[2] * factor - p[2]) / 2
        dh = (p[3] * factor - p[3]) / 2
        p[0] -= dw; p[1] -= dh; p[2] *= factor; p[3] *= factor
        svg = re.sub(r'viewBox="[^"]*"',
                     f'viewBox="{" ".join(f"{x:.2f}" for x in p)}"',
                     _read("heart eyes.svg"))
        _save(_render(svg), d, i)

def gen_starry(d="faces/starry_eyed"):
    for i in range(1, 9):
        dy = round(4 * math.sin(i * math.pi / 4))
        _save(_svg_render("star eyes 2.svg", dy_px=dy), d, i)

def gen_confused(d="faces/confused"):
    for i in range(1, 7):
        dy = round(3 * math.sin(i * math.pi / 3))
        _save(_svg_render("hmmm.svg", dy_px=dy), d, i)

def gen_shhh(d="faces/shhh"):
    blinks = [0, 0, 0, 0.9, 0.9, 0, 0, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_render("meep.svg", b), d, i)

def gen_jamming(d="faces/jamming"):
    for i in range(1, 9):
        dy = round(10 * abs(math.sin(i * math.pi / 4)))
        _save(_svg_render("happy.svg", dy_px=dy), d, i)

def gen_football(d="faces/football"):
    for i in range(1, 9):
        dy = round(7 * math.sin(i * math.pi / 4))
        _save(_svg_render("shouting.svg", dy_px=dy), d, i)

def gen_detective(d="faces/detective"):
    blinks = [0, 0, 0, 0, 0, 0, 0.9, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_render("side eye.svg", b), d, i)

def gen_sir_mano(d="faces/sir_mano"):
    for i in range(1, 9):
        dy = round(4 * math.sin(i * math.pi / 4))
        _save(_svg_render("cheeky.svg", dy_px=dy), d, i)

def gen_low_battery(d="faces/low_battery"):
    blinks = [0.7, 0.8, 0.9, 0.97, 0.9, 0.8, 0.7, 0.6]
    for i, b in enumerate(blinks, 1):
        _save(_blink_render("tired and happy.svg", b), d, i)

def gen_bee(d="faces/bee"):
    for i in range(1, 17):
        t = (i - 1) / 16
        x = 540 + 340 * math.sin(t * 2 * math.pi)
        y = 240 + 110 * math.sin(t * 4 * math.pi)
        _save(_composite_critter("bee.svg", 220, 222, x, y), d, i)

def gen_daydream(d="faces/daydream"):
    for i in range(1, 13):
        dy = round(5 * math.sin(i * math.pi / 6))
        _save(_svg_render("relax.svg", dy_px=dy), d, i)

def gen_bored(d="faces/bored"):
    blinks = [0, 0, 0, 0.4, 0.9, 0.4, 0, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_render("side eye.svg", b), d, i)

def gen_curious(d="faces/curious"):
    for i in range(1, 9):
        dy = round(5 * math.sin(i * math.pi / 4))
        _save(_svg_render("ooooooh.svg", dy_px=dy), d, i)

def gen_error(d="faces/error"):
    shakes = [0, -10, 10, 0]
    for i, dx in enumerate(shakes, 1):
        _save(_svg_render("exasperated.svg", dx_px=dx), d, i)

def gen_capturing(d="faces/capturing"):
    for i in range(1, 5):
        dy = round(5 * math.sin(i * math.pi / 2))
        _save(_svg_render("ooooooh.svg", dy_px=dy), d, i)

def gen_warmup(d="faces/warmup"):
    # Eyes open from closed over 4 frames
    for i, b in enumerate([0.97, 0.6, 0.2, 0], 1):
        _save(_blink_render("smile.svg", b), d, i)

def gen_ladybug(d="faces/ladybug"):
    # 16 frames: ladybug walks across the bottom of the screen left→right
    for i in range(1, 17):
        t = (i - 1) / 15  # 0 → 1
        x = -80 + t * 960   # starts off-screen left, exits right
        y = 300 + 20 * math.sin(t * 4 * math.pi)  # slight vertical wobble
        _save(_composite_critter("ladybug.svg", 130, 141, x, y), d, i)

def gen_worm(d="faces/worm"):
    # 16 frames: worm wiggles in from the right across the centre
    for i in range(1, 17):
        t = (i - 1) / 15
        x = 960 - t * 960   # right to left
        y = 200 + 30 * math.sin(t * 6 * math.pi)  # wavy vertical path
        _save(_composite_critter("worm.svg", 180, 150, x, y), d, i)

# ── Speaking frames (fixed separately – needs two SVGs) ───────────────────────

def _fix_gen_speaking():
    d = "faces/speaking"
    vb_s = _get_vb("smile.svg")
    vb_o = _get_vb("open mouth.svg")
    smile   = _apply_vb(_read("smile.svg"),      vb_s)
    openmth = _apply_vb(_read("open mouth.svg"), vb_o)
    def _bounced(svg_text, vb, dy_px):
        parts = list(map(float, vb.split()))
        parts[1] -= dy_px * parts[3] / OUT_H
        new_vb = " ".join(f"{p:.2f}" for p in parts)
        return re.sub(r'viewBox="[^"]*"', f'viewBox="{new_vb}"', svg_text)
    frames = [
        (smile, 0), (smile, 0), (smile, 0), (smile, 0),
        (_bounced(_read("open mouth.svg"), vb_o, -2), 0),
        (openmth, 0),
        (_bounced(_read("open mouth.svg"), vb_o,  2), 0),
        (openmth, 0),
    ]
    os.makedirs(d, exist_ok=True)
    for i, (svg, _) in enumerate(frames, 1):
        _save(_render(svg), d, i)

# ── Main ──────────────────────────────────────────────────────────────────────

GENERATORS = [
    gen_idle, gen_speaking, gen_thinking, gen_listening,
    gen_happy, gen_sad, gen_angry, gen_surprised, gen_sleepy,
    gen_dizzy, gen_cheeky, gen_heart, gen_starry, gen_confused,
    gen_shhh, gen_jamming, gen_football, gen_detective, gen_sir_mano,
    gen_low_battery, gen_bee, gen_ladybug, gen_worm,
    gen_daydream, gen_bored, gen_curious,
    gen_error, gen_capturing, gen_warmup,
]

if __name__ == "__main__":
    # Pre-compute all normalised viewBoxes (measures content bbox per SVG)
    needed = {
        "smile.svg", "happy.svg", "frown.svg", "cheeky.svg", "hmmm.svg",
        "side eye.svg", "ooooooh.svg", "shocked and wonder.svg",
        "tired and happy.svg", "confused and mad.svg", "relax.svg",
        "meep.svg", "shouting.svg", "exasperated.svg", "dizzy.svg",
        "heart eyes.svg", "star eyes 2.svg", "open mouth.svg",
    }
    print("Computing normalised viewBoxes…")
    for name in sorted(needed):
        vb = _get_vb(name)
        scale_w = 1280 / float(vb.split()[2])
        print(f"  {name:<30}  scale={scale_w:.3f}  vb={vb}")

    print()
    for gen in GENERATORS:
        d = gen.__defaults__[0]
        print(f"  {d}…", end=" ", flush=True)
        if os.path.exists(d):
            shutil.rmtree(d)
        gen()
        n = len(glob.glob(f"{d}/*.png"))
        print(f"{n} frames")

    for f in glob.glob("faces/**/* *.png", recursive=True):
        os.remove(f)
    print("\nDone.")
