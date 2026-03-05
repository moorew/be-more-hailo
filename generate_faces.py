import os
from PIL import Image, ImageDraw

BG_COLOR = (189, 255, 203)
LINE_COLOR = (0, 0, 0)
WIDTH, HEIGHT = 800, 480
LINE_WIDTH = 12

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def create_face(filename, draw_func):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_func(draw)
    img.save(filename)
    print(f"Generated {filename}")

# Helper draw functions
def draw_arc_eye(draw, cx, cy, radius, start, end):
    # PIL arc requires a bounding box [x0, y0, x1, y1]
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.arc(bbox, start, end, fill=LINE_COLOR, width=LINE_WIDTH)

def draw_circle_eye(draw, cx, cy, radius):
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(bbox, fill=LINE_COLOR)

def draw_line(draw, x1, y1, x2, y2, width=LINE_WIDTH):
    draw.line([(x1, y1), (x2, y2)], fill=LINE_COLOR, width=width)

def draw_regular_eyes(draw, blink=0.0):
    # blink: 0.0 = open, 1.0 = closed
    # Left eye: arc from 0 to 180
    
    # BMO's standard eyes are little upward-facing arcs (u shape)
    # The original image has arcs that look like closed eyes pointing UP
    # Actually wait - BMO's classic eyes are just dots or small straight lines sometimes, but the existing idle face has "u" shaped eyes. 
    # Arc degrees: 0 is 3 o'clock, 90 is 6 o'clock, 180 is 9 o'clock.
    # So an upward-facing U shape is from 0 to 180.
    
    if blink >= 0.9:
        # Closed eyes (straight lines)
        draw_line(draw, 220, 200, 260, 200)
        draw_line(draw, 540, 200, 580, 200)
    elif blink > 0.0:
        # Half blink
        draw_arc_eye(draw, 240, 200 - int(10 * blink), 20, 0, 180)
        draw_arc_eye(draw, 560, 200 - int(10 * blink), 20, 0, 180)
    else:
        # Open eyes (U shape)
        draw_arc_eye(draw, 240, 200, 20, 0, 180)
        draw_arc_eye(draw, 560, 200, 20, 0, 180)

def draw_angry_eyes(draw):
    # Angled lines \  /
    draw_line(draw, 220, 180, 260, 220)
    draw_line(draw, 540, 220, 580, 180)
    
def draw_happy_eyes(draw):
    # Inverted U shapes ^ ^
    draw_arc_eye(draw, 240, 220, 20, 180, 360)
    draw_arc_eye(draw, 560, 220, 20, 180, 360)
    
def draw_surprised_eyes(draw):
    # Big wide open circles
    draw_circle_eye(draw, 240, 200, 15)
    draw_circle_eye(draw, 560, 200, 15)

def draw_sad_eyes(draw):
    # Angled lines /  \
    draw_line(draw, 220, 220, 260, 180)
    draw_line(draw, 540, 180, 580, 220)

def draw_mouth(draw, type="straight", open_amount=0):
    if type == "straight":
        draw_line(draw, 360, 300, 440, 300)
    elif type == "smile":
        # wide U shape
        draw_arc_eye(draw, 400, 280, 50, 45, 135)
    elif type == "frown":
        # wide inverted U shape
        draw_arc_eye(draw, 400, 320, 50, 225, 315)
    elif type == "surprised":
        # small circle
        draw.ellipse([380, 290, 420, 330], fill=None, outline=LINE_COLOR, width=LINE_WIDTH)
    elif type == "speaking":
        # Oval mouth
        h = max(10, min(50, open_amount))
        draw.ellipse([360, 300 - h//2, 440, 300 + h//2], fill=None, outline=LINE_COLOR, width=LINE_WIDTH)


# GENERATORS
def gen_idle(base_dir="faces/idle"):
    ensure_dir(base_dir)
    # A standard long idle waiting for a blink
    for i in range(1, 15):
        create_face(f"{base_dir}/idle_{i:02d}.png", lambda d: (draw_regular_eyes(d, 0.0), draw_mouth(d, "straight")))
    # Blink sequence
    create_face(f"{base_dir}/idle_15.png", lambda d: (draw_regular_eyes(d, 0.5), draw_mouth(d, "straight")))
    create_face(f"{base_dir}/idle_16.png", lambda d: (draw_regular_eyes(d, 1.0), draw_mouth(d, "straight")))
    create_face(f"{base_dir}/idle_17.png", lambda d: (draw_regular_eyes(d, 1.0), draw_mouth(d, "straight")))
    create_face(f"{base_dir}/idle_18.png", lambda d: (draw_regular_eyes(d, 0.5), draw_mouth(d, "straight")))

def gen_speaking(base_dir="faces/speaking"):
    ensure_dir(base_dir)
    # Animated mouth opening and closing
    heights = [10, 30, 50, 30, 15, 40, 20]
    for i, h in enumerate(heights):
        create_face(f"{base_dir}/speaking_{i:02d}.png", lambda d, h=h: (draw_regular_eyes(d, 0.0), draw_mouth(d, "speaking", h)))

def gen_happy(base_dir="faces/happy"):
    ensure_dir(base_dir)
    for i in range(1, 5):
        create_face(f"{base_dir}/happy_{i:02d}.png", lambda d: (draw_happy_eyes(d), draw_mouth(d, "smile")))

def gen_sad(base_dir="faces/sad"):
    ensure_dir(base_dir)
    for i in range(1, 5):
        create_face(f"{base_dir}/sad_{i:02d}.png", lambda d: (draw_sad_eyes(d), draw_mouth(d, "frown")))

def gen_angry(base_dir="faces/angry"):
    ensure_dir(base_dir)
    for i in range(1, 5):
        create_face(f"{base_dir}/angry_{i:02d}.png", lambda d: (draw_angry_eyes(d), draw_mouth(d, "straight")))

def gen_surprised(base_dir="faces/surprised"):
    ensure_dir(base_dir)
    for i in range(1, 4):
        create_face(f"{base_dir}/surprised_{i:02d}.png", lambda d: (draw_surprised_eyes(d), draw_mouth(d, "surprised")))

def gen_sleepy(base_dir="faces/sleepy"):
    ensure_dir(base_dir)
    # Eyes closed
    for i in range(1, 6):
        z_offset = i * 5
        def draw_sleepy(d, off=z_offset):
            draw_regular_eyes(d, 1.0)
            draw_mouth(d, "straight")
            # Draw a Z
            if off > 10: d.text((600, 120 - off), "Z", fill=LINE_COLOR, font=None, font_size=40)
            if off > 20: d.text((650, 80 - off), "z", fill=LINE_COLOR, font=None, font_size=30)
        create_face(f"{base_dir}/sleepy_{i:02d}.png", draw_sleepy)

def gen_thinking(base_dir="faces/thinking"):
    ensure_dir(base_dir)
    # Scanning eyes or moving dot
    for i in range(1, 10):
        offset = (i % 5) * 10
        def draw_think(d, off=offset):
            draw_regular_eyes(d, 0.0)
            draw_mouth(d, "straight")
            # Draw a little thinking dot
            d.ellipse([380 + off, 240, 400 + off, 260], fill=LINE_COLOR)
        create_face(f"{base_dir}/thinking_{i:02d}.png", draw_think)


if __name__ == "__main__":
    print("Generating BMO Faces...")
    gen_idle()
    gen_speaking()
    gen_happy()
    gen_sad()
    gen_angry()
    gen_surprised()
    gen_sleepy()
    gen_thinking()
    
    # We should also ensure old images are removed if they don't match the sequence format to avoid clutter
    # Actually, we can just leave them if they loop well. But overwriting idle/speaking animations gives BMO new life!
    print("Finished generating faces!")
