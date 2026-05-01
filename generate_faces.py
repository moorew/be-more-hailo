#!/usr/bin/env python3
"""Generate BMO face animation frames from SVG assets in svg_faces/."""

import copy, glob, io, math, os, re, shutil
import xml.etree.ElementTree as ET
import cairosvg
from PIL import Image

OUT_W, OUT_H = 800, 480
SUPERSAMPLE = 2
SVG_DIR = "svg_faces"
FACES_DIR = "faces"
NS = "http://www.w3.org/2000/svg"
BMO_BG = "#C9E4C3"

ET.register_namespace("", NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

# ── Low-level helpers ─────────────────────────────────────────────────────────

def _read(name):
    with open(f"{SVG_DIR}/{name}", encoding="utf-8") as f:
        return f.read()

BMO_BG_RGB = (201, 228, 195)  # #C9E4C3

def _render(svg_text, ss=SUPERSAMPLE):
    # Render at native SVG resolution (1280×720) * ss to avoid aspect-ratio letterboxing,
    # then resize to output dimensions. Composite over BMO green for any transparent areas.
    SVG_W, SVG_H = 1280, 720
    png = cairosvg.svg2png(
        bytestring=svg_text.encode(),
        output_width=SVG_W * ss, output_height=SVG_H * ss,
    )
    img = Image.open(io.BytesIO(png))
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, BMO_BG_RGB)
        bg.paste(img.convert("RGB"), mask=img.split()[3])
        img = bg
    else:
        img = img.convert("RGB")
    return img.resize((OUT_W, OUT_H), Image.LANCZOS)

def _save(img, directory, n):
    os.makedirs(directory, exist_ok=True)
    stem = os.path.basename(directory)
    img.save(f"{directory}/{stem}_{n:02d}.png")

def _bounce(svg_text, dy):
    """Shift content by dy px (positive = down) via viewBox."""
    return svg_text.replace('viewBox="0 0 1280 720"',
                            f'viewBox="0 {-dy} 1280 720"')

def _hshift(svg_text, dx):
    """Shift content by dx px (positive = right) via viewBox."""
    return svg_text.replace('viewBox="0 0 1280 720"',
                            f'viewBox="{-dx} 0 1280 720"')

def _parse(name):
    tree = ET.parse(f"{SVG_DIR}/{name}")
    return tree

def _tostr(tree):
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + \
           ET.tostring(tree.getroot(), encoding="unicode")

def _find_eyes(root):
    """Return fill=black ellipses large enough to be eyes (up to 2)."""
    eyes = []
    for e in root.iter(f"{{{NS}}}ellipse"):
        if e.get("fill") == "black":
            rx = float(e.get("rx", 0))
            ry = float(e.get("ry", 0))
            if rx > 15 and ry > 15:
                eyes.append(e)
    return eyes[:2]

def _blink_frame(tree, factor):
    """Render tree with eyes factor-closed (0=open, 1=closed). Non-destructive."""
    root = tree.getroot()
    eyes = _find_eyes(root)
    orig = {id(e): float(e.get("ry")) for e in eyes}
    for e in eyes:
        e.set("ry", str(max(1.5, orig[id(e)] * (1 - factor * 0.97))))
    img = _render(_tostr(tree))
    for e in eyes:
        e.set("ry", str(orig[id(e)]))
    return img

def _svg_body(svg_text):
    """Strip outer <svg> tags, return inner content string."""
    inner = re.sub(r'<\?xml[^>]*\?>', '', svg_text)
    inner = re.sub(r'<svg[^>]*>', '', inner, count=1)
    inner = re.sub(r'</svg>\s*$', '', inner.strip())
    return inner

def _composite_critter(critter_name, critter_w, critter_h, x, y):
    """Return SVG string: BMO green bg with critter scaled to critter_w × critter_h at (x, y)."""
    body = _svg_body(_read(critter_name))
    # parse original viewBox from file
    raw = _read(critter_name)
    vb = re.search(r'viewBox="0 0 (\S+) (\S+)"', raw)
    orig_w = float(vb.group(1)) if vb else 578
    orig_h = float(vb.group(2)) if vb else 584
    sx = critter_w / orig_w
    sy = critter_h / orig_h
    return (
        f'<svg width="1280" height="720" viewBox="0 0 1280 720" '
        f'xmlns="http://www.w3.org/2000/svg" fill="none">\n'
        f'<rect width="1280" height="720" fill="{BMO_BG}"/>\n'
        f'<g transform="translate({x:.1f},{y:.1f}) scale({sx:.5f},{sy:.5f})">\n'
        f'{body}\n</g>\n</svg>'
    )

# ── Face generators ───────────────────────────────────────────────────────────

def gen_idle(d="faces/idle"):
    t = _parse("smile.svg")
    # 12 frames: blink on frames 7–9
    blinks = [0, 0, 0, 0, 0, 0, 0.55, 0.97, 0.55, 0, 0, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

def gen_speaking(d="faces/speaking"):
    smile = _read("smile.svg")
    openmth = _read("open mouth.svg")
    # ordered closed→open so mouth_ema maps naturally
    frames = [smile, smile, smile, smile,
              _bounce(openmth, -2), openmth, _bounce(openmth, 2), openmth]
    for i, svg in enumerate(frames, 1):
        _save(_render(svg), d, i)

def gen_thinking(d="faces/thinking"):
    svg = _read("hmmm.svg")
    for i in range(1, 9):
        dy = round(4 * math.sin(i * math.pi / 4))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_listening(d="faces/listening"):
    t = _parse("smile.svg")
    blinks = [0, 0, 0, 0.6, 0.97, 0.6, 0, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

def gen_happy(d="faces/happy"):
    svg = _read("happy.svg")
    for i in range(1, 9):
        dy = round(6 * math.sin(i * math.pi / 4))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_sad(d="faces/sad"):
    t = _parse("frown.svg")
    svg = _read("frown.svg")
    for i in range(1, 9):
        dy = round(2 * math.sin(i * math.pi / 8))
        if i == 6:
            _save(_blink_frame(t, 0.9), d, i)
        else:
            _save(_render(_bounce(svg, dy)), d, i)

def gen_angry(d="faces/angry"):
    svg = _read("confused and mad.svg")
    shakes = [0, 6, -6, 8, -8, 4, -4, 0]
    for i, dx in enumerate(shakes, 1):
        _save(_render(_hshift(svg, dx)), d, i)

def gen_surprised(d="faces/surprised"):
    svg = _read("shocked and wonder.svg")
    for i in range(1, 5):
        dy = round(8 * math.sin(i * math.pi / 2))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_sleepy(d="faces/sleepy"):
    t = _parse("tired and happy.svg")
    # slow closing blink
    blinks = [0.1, 0.3, 0.6, 0.9, 0.97, 0.9, 0.6, 0.3]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

def gen_dizzy(d="faces/dizzy"):
    svg = _read("dizzy.svg")
    # slight sway
    for i in range(1, 5):
        dx = round(5 * math.sin(i * math.pi / 2))
        _save(_render(_hshift(svg, dx)), d, i)

def gen_cheeky(d="faces/cheeky"):
    t = _parse("cheeky.svg")
    blinks = [0, 0, 0, 0, 0.5, 0.97, 0.5, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

def gen_heart(d="faces/heart"):
    svg = _read("heart eyes.svg")
    for i in range(1, 7):
        # subtle zoom pulse
        factor = 1 + 0.04 * math.sin(i * math.pi / 3)
        dw = (1280 * factor - 1280) / 2
        dh = (720 * factor - 720) / 2
        pulsed = svg.replace(
            'viewBox="0 0 1280 720"',
            f'viewBox="{-dw:.2f} {-dh:.2f} {1280*factor:.2f} {720*factor:.2f}"'
        )
        _save(_render(pulsed), d, i)

def gen_starry(d="faces/starry_eyed"):
    svg = _read("star eyes 2.svg")
    for i in range(1, 9):
        dy = round(4 * math.sin(i * math.pi / 4))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_confused(d="faces/confused"):
    svg = _read("hmmm.svg")
    for i in range(1, 7):
        dy = round(3 * math.sin(i * math.pi / 3))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_shhh(d="faces/shhh"):
    t = _parse("meep.svg")
    for i in range(1, 9):
        factor = 0.9 if i in (4, 5) else 0
        _save(_blink_frame(t, factor), d, i)

def gen_jamming(d="faces/jamming"):
    svg = _read("happy.svg")
    for i in range(1, 9):
        dy = round(10 * abs(math.sin(i * math.pi / 4)))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_football(d="faces/football"):
    svg = _read("shouting.svg")
    for i in range(1, 9):
        dy = round(7 * math.sin(i * math.pi / 4))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_detective(d="faces/detective"):
    t = _parse("side eye.svg")
    blinks = [0, 0, 0, 0, 0, 0, 0.9, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

def gen_sir_mano(d="faces/sir_mano"):
    svg = _read("cheeky.svg")
    for i in range(1, 9):
        dy = round(4 * math.sin(i * math.pi / 4))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_low_battery(d="faces/low_battery"):
    t = _parse("tired and happy.svg")
    # very slow blink, barely moving
    blinks = [0.7, 0.8, 0.9, 0.97, 0.9, 0.8, 0.7, 0.6]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

def gen_bee(d="faces/bee"):
    for i in range(1, 17):
        t = (i - 1) / 16
        x = 540 + 340 * math.sin(t * 2 * math.pi)
        y = 240 + 110 * math.sin(t * 4 * math.pi)
        svg = _composite_critter("bee.svg", 220, 222, x, y)
        _save(_render(svg), d, i)

def gen_daydream(d="faces/daydream"):
    svg = _read("relax.svg")
    for i in range(1, 13):
        dy = round(5 * math.sin(i * math.pi / 6))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_bored(d="faces/bored"):
    t = _parse("side eye.svg")
    blinks = [0, 0, 0, 0.4, 0.9, 0.4, 0, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

def gen_curious(d="faces/curious"):
    svg = _read("ooooooh.svg")
    for i in range(1, 9):
        dy = round(5 * math.sin(i * math.pi / 4))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_error(d="faces/error"):
    svg = _read("exasperated.svg")
    shakes = [0, -10, 10, 0]
    for i, dx in enumerate(shakes, 1):
        _save(_render(_hshift(svg, dx)), d, i)

def gen_capturing(d="faces/capturing"):
    svg = _read("ooooooh.svg")
    for i in range(1, 5):
        dy = round(5 * math.sin(i * math.pi / 2))
        _save(_render(_bounce(svg, dy)), d, i)

def gen_warmup(d="faces/warmup"):
    # Boot-up: eyes open from closed
    t = _parse("smile.svg")
    blinks = [0.97, 0.6, 0.2, 0]
    for i, b in enumerate(blinks, 1):
        _save(_blink_frame(t, b), d, i)

# ── Main ──────────────────────────────────────────────────────────────────────

GENERATORS = [
    gen_idle, gen_speaking, gen_thinking, gen_listening,
    gen_happy, gen_sad, gen_angry, gen_surprised, gen_sleepy,
    gen_dizzy, gen_cheeky, gen_heart, gen_starry, gen_confused,
    gen_shhh, gen_jamming, gen_football, gen_detective, gen_sir_mano,
    gen_low_battery, gen_bee, gen_daydream, gen_bored, gen_curious,
    gen_error, gen_capturing, gen_warmup,
]

if __name__ == "__main__":
    for gen in GENERATORS:
        d = gen.__defaults__[0]
        print(f"  {d}...", end=" ", flush=True)
        if os.path.exists(d):
            shutil.rmtree(d)
        gen()
        n = len(glob.glob(f"{d}/*.png"))
        print(f"{n} frames")
    # Remove any leftover files with spaces (old generator artefact)
    for f in glob.glob("faces/**/* *.png", recursive=True):
        os.remove(f)
    print("Done.")
