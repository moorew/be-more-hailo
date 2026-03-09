import os
from PIL import Image, ImageDraw

BG_COLOR = (189, 255, 203)
LINE_COLOR = (0, 0, 0)
MOUTH_DARK = (41, 131, 57)
TONGUE_COLOR = (112, 195, 112) # Slightly lighter green for tongue
TEETH_COLOR = (255, 255, 255)
WIDTH, HEIGHT = 800, 480
SCALE = 4
LINE_WIDTH = 8
LEFT_EYE_X = 217
RIGHT_EYE_X = 581
EYE_Y = 195 # Arc center point for U-shaped eyes
EYE_VISUAL_Y = 200 # Visual center of the arc eye (arc 335-205 shifts mass down ~5px)
EYE_R = 18
MOUTH_Y = 302
MOUTH_W = 97

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def create_face(filename, draw_func):
    # Render at 4x resolution and scale down for perfect anti-aliasing
    img = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_func(draw)
    final_img = img.resize((WIDTH, HEIGHT), resample=Image.Resampling.LANCZOS)
    final_img.save(filename)
    print(f"Generated {filename}")

# Helper draw functions
def draw_arc_eye(draw, cx, cy, radius, start, end):
    cx, cy, radius = cx * SCALE, cy * SCALE, radius * SCALE
    width = LINE_WIDTH * SCALE
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.arc(bbox, start, end, fill=LINE_COLOR, width=width)
    
    # PIL draws arc stroke widths *inward* from the bounding box.
    # Therefore, the centerline of the stroke is at `radius - (width / 2.0)`
    import math
    r = width / 2.0 # Radius of the end cap
    effective_radius = radius - r # Centerline of the arc
    
    s_rad = math.radians(start)
    e_rad = math.radians(end)
    sx = cx + effective_radius * math.cos(s_rad)
    sy = cy + effective_radius * math.sin(s_rad)
    ex = cx + effective_radius * math.cos(e_rad)
    ey = cy + effective_radius * math.sin(e_rad)
    
    draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=LINE_COLOR)
    draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=LINE_COLOR)

def draw_circle_eye(draw, cx, cy, radius):
    cx, cy, radius = cx * SCALE, cy * SCALE, radius * SCALE
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(bbox, fill=LINE_COLOR)

def draw_line(draw, x1, y1, x2, y2, width=LINE_WIDTH):
    x1, y1, x2, y2 = x1 * SCALE, y1 * SCALE, x2 * SCALE, y2 * SCALE
    width = width * SCALE
    draw.line([(x1, y1), (x2, y2)], fill=LINE_COLOR, width=width)
    # Rounded caps
    r = width / 2.0
    draw.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=LINE_COLOR)
    draw.ellipse([x2 - r, y2 - r, x2 + r, y2 + r], fill=LINE_COLOR)

def draw_ellipse(draw, bbox, fill=None, outline=None, width=0):
    box = [bbox[0]*SCALE, bbox[1]*SCALE, bbox[2]*SCALE, bbox[3]*SCALE]
    draw.ellipse(box, fill=fill, outline=outline, width=width*SCALE)

def draw_regular_eyes(draw, blink=0.0):
    if blink >= 0.9:
        # Closed eyes (straight lines) - use visual center so they align
        draw_line(draw, LEFT_EYE_X - EYE_R, EYE_VISUAL_Y, LEFT_EYE_X + EYE_R, EYE_VISUAL_Y)
        draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_VISUAL_Y, RIGHT_EYE_X + EYE_R, EYE_VISUAL_Y)
    elif blink > 0.0:
        # Half blink
        draw_arc_eye(draw, LEFT_EYE_X, EYE_Y - int((EYE_R/2) * blink), EYE_R, 345, 195)
        draw_arc_eye(draw, RIGHT_EYE_X, EYE_Y - int((EYE_R/2) * blink), EYE_R, 345, 195)
    else:
        # Open eyes (steeper U shape extends past 180)
        draw_arc_eye(draw, LEFT_EYE_X, EYE_Y, EYE_R, 335, 205)
        draw_arc_eye(draw, RIGHT_EYE_X, EYE_Y, EYE_R, 335, 205)

def draw_angry_eyes(draw):
    draw_line(draw, LEFT_EYE_X - EYE_R, EYE_VISUAL_Y - 10, LEFT_EYE_X + EYE_R, EYE_VISUAL_Y + 10)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_VISUAL_Y + 10, RIGHT_EYE_X + EYE_R, EYE_VISUAL_Y - 10)
    
def draw_happy_eyes(draw):
    # Inverted arc (180-360) shifts visual center UP, so push down further
    draw_arc_eye(draw, LEFT_EYE_X, EYE_Y + 13, EYE_R, 180, 360)
    draw_arc_eye(draw, RIGHT_EYE_X, EYE_Y + 13, EYE_R, 180, 360)
    
def draw_surprised_eyes(draw):
    draw_circle_eye(draw, LEFT_EYE_X, EYE_VISUAL_Y, EYE_R - 2)
    draw_circle_eye(draw, RIGHT_EYE_X, EYE_VISUAL_Y, EYE_R - 2)

def draw_sad_eyes(draw):
    draw_line(draw, LEFT_EYE_X - EYE_R, EYE_VISUAL_Y + 10, LEFT_EYE_X + EYE_R, EYE_VISUAL_Y - 10)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_VISUAL_Y - 10, RIGHT_EYE_X + EYE_R, EYE_VISUAL_Y + 10)

def draw_dizzy_eyes(draw):
    draw_line(draw, LEFT_EYE_X - 15, EYE_VISUAL_Y - 15, LEFT_EYE_X + 15, EYE_VISUAL_Y + 15)
    draw_line(draw, LEFT_EYE_X - 15, EYE_VISUAL_Y + 15, LEFT_EYE_X + 15, EYE_VISUAL_Y - 15)
    draw_line(draw, RIGHT_EYE_X - 15, EYE_VISUAL_Y - 15, RIGHT_EYE_X + 15, EYE_VISUAL_Y + 15)
    draw_line(draw, RIGHT_EYE_X - 15, EYE_VISUAL_Y + 15, RIGHT_EYE_X + 15, EYE_VISUAL_Y - 15)

def draw_heart_eye(draw, cx, cy, scale=1.0):
    # Draw a cute heart shape centered at cx, cy using polygons
    # Scaled to beat
    size = 20 * scale
    import math
    points = []
    # Parametric heart equation
    for t in range(0, 360, 5):
        rad = math.radians(t)
        # Heart math
        x = 16 * (math.sin(rad)**3)
        y = 13 * math.cos(rad) - 5 * math.cos(2*rad) - 2 * math.cos(3*rad) - math.cos(4*rad)
        # Flip Y since PIL origin is top-left
        points.append((cx + x * (size/16.0), cy - y * (size/16.0)))
    
    scaled_points = [(p[0]*SCALE, p[1]*SCALE) for p in points]
    draw.polygon(scaled_points, fill=LINE_COLOR)

def draw_star_eye(draw, cx, cy, rotation=0):
    # Draw a 4-point sparkle star
    import math
    points = []
    outer_r = 22
    inner_r = 6
    for i in range(8):
        angle = math.radians(rotation + i * 45)
        r = outer_r if i % 2 == 0 else inner_r
        points.append((cx + math.sin(angle) * r, cy - math.cos(angle) * r))
        
    scaled_points = [(p[0]*SCALE, p[1]*SCALE) for p in points]
    draw.polygon(scaled_points, fill=LINE_COLOR)

def draw_confused_eyes(draw):
    # One big, one flat
    draw_circle_eye(draw, LEFT_EYE_X, EYE_VISUAL_Y, EYE_R + 5)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_VISUAL_Y, RIGHT_EYE_X + EYE_R, EYE_VISUAL_Y)

def draw_cheeky_eyes(draw):
    draw_circle_eye(draw, LEFT_EYE_X, EYE_VISUAL_Y, EYE_R - 2)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_VISUAL_Y, RIGHT_EYE_X + EYE_R, EYE_VISUAL_Y)

def draw_mouth(draw, type="straight", open_amount=0):
    m_left = 399 - (MOUTH_W // 2)
    m_right = 399 + (MOUTH_W // 2)
    
    if type == "straight":
        draw_line(draw, m_left, MOUTH_Y, m_right, MOUTH_Y)
    elif type == "smile":
        # wide U shape
        draw_arc_eye(draw, 399, MOUTH_Y - 20, MOUTH_W // 2, 45, 135)
    elif type == "frown":
        # wide inverted U shape
        draw_arc_eye(draw, 399, MOUTH_Y + 20, MOUTH_W // 2, 225, 315)
    elif type == "surprised":
        # small circle
        draw_ellipse(draw, [399 - 20, MOUTH_Y - 20, 399 + 20, MOUTH_Y + 20], fill=MOUTH_DARK, outline=LINE_COLOR, width=LINE_WIDTH)
    elif type == "speaking":
        # Complex pill-shaped mouth with teeth and tongue
        # Outer pill bounding box
        h = max(15, min(65, open_amount))
        
        box = [m_left * SCALE, (MOUTH_Y - h//2) * SCALE, m_right * SCALE, (MOUTH_Y + h//2) * SCALE]
        rad = (h//2) * SCALE
        
        # Draw background dark cavity pill shape
        draw.rounded_rectangle(box, radius=rad, fill=MOUTH_DARK, outline=LINE_COLOR, width=LINE_WIDTH * SCALE)
        
        # Draw teeth (white bar across the top inside of the mouth)
        if h > 20: # Only show teeth if mouth is open wide enough
            teeth_h = min(12, h // 3) * SCALE
            teeth_box = [box[0] + (LINE_WIDTH*SCALE), box[1] + (LINE_WIDTH*SCALE), box[2] - (LINE_WIDTH*SCALE), box[1] + teeth_h + (LINE_WIDTH*SCALE)]
            # Draw teeth as a rounded slice at the top
            draw.rounded_rectangle(teeth_box, radius=rad, fill=TEETH_COLOR)
            
        # Draw tongue hump (light green pill slice at the bottom)
        if h > 30:
            tongue_h = min(20, h // 2) * SCALE
            tongue_w = (MOUTH_W - 30) * SCALE
            t_left = (399 * SCALE) - (tongue_w // 2)
            t_right = (399 * SCALE) + (tongue_w // 2)
            t_bottom = box[3] - (LINE_WIDTH*SCALE)
            t_top = t_bottom - tongue_h
            
            draw.ellipse([t_left, t_top, t_right, t_bottom + (tongue_h//2)], fill=TONGUE_COLOR)
            # Re-stroke the outer mouth line just in case tongue overflowed the bottom curve cleanly 
            draw.rounded_rectangle(box, radius=rad, fill=None, outline=LINE_COLOR, width=LINE_WIDTH * SCALE)
    elif type == "tongue":
        # Straight line mouth with a colored tongue poking out below
        draw_line(draw, m_left, MOUTH_Y, m_right, MOUTH_Y)
        # Tongue as a filled half-circle in TONGUE_COLOR, outlined in black
        tongue_cx = 399 + 15
        tongue_cy = MOUTH_Y
        tongue_r = 15
        # Draw filled tongue
        bbox = [(tongue_cx - tongue_r) * SCALE, tongue_cy * SCALE,
                (tongue_cx + tongue_r) * SCALE, (tongue_cy + tongue_r * 2) * SCALE]
        draw.ellipse(bbox, fill=TONGUE_COLOR, outline=LINE_COLOR, width=LINE_WIDTH * SCALE)
        # Re-draw the mouth line on top so it covers the top edge of the tongue cleanly
        x1, y1 = m_left * SCALE, MOUTH_Y * SCALE
        x2, y2 = m_right * SCALE, MOUTH_Y * SCALE
        w = LINE_WIDTH * SCALE
        draw.line([(x1, y1), (x2, y2)], fill=LINE_COLOR, width=w)
        r = w / 2.0
        draw.ellipse([x1-r, y1-r, x1+r, y1+r], fill=LINE_COLOR)
        draw.ellipse([x2-r, y2-r, x2+r, y2+r], fill=LINE_COLOR)
    elif type == "wavy":
        # squiggly mouth for dizzy (shift centers to account for PIL inward stroke)
        shift = LINE_WIDTH // 2
        draw_arc_eye(draw, 399 - 15 + shift, MOUTH_Y, 15, 180, 360)
        draw_arc_eye(draw, 399 + 15 - shift, MOUTH_Y, 15, 0, 180)
    elif type == "mute":
        # whimsical 'x' mouth for shhh
        sz = max(8, open_amount)
        draw_line(draw, 399 - sz, MOUTH_Y - sz, 399 + sz, MOUTH_Y + sz)
        draw_line(draw, 399 - sz, MOUTH_Y + sz, 399 + sz, MOUTH_Y - sz)


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
    # Natural speech rhythm: 0 = closed mouth (straight line), >0 = open speaking mouth
    # Pattern simulates syllable cadence with word-boundary pauses for realistic lip-sync
    heights = [
        0,          # 00: closed (clean start / rest)
        35, 50,     # 01-02: first syllable
        0,          # 03: brief close between syllables
        45, 30,     # 04-05: second syllable
        55, 25,     # 06-07: third syllable (emphasis)
        0,          # 08: word boundary pause
        40, 60,     # 09-10: stressed syllable
        20,         # 11: quick consonant
        45, 30,     # 12-13: next syllable
        0,          # 14: word boundary pause
        35, 50, 20, # 15-17: trailing word
        0,          # 18: closed (clean loop back to start)
    ]
    for i, h in enumerate(heights):
        def draw_spk(d, hm=h):
            draw_circle_eye(d, LEFT_EYE_X, EYE_VISUAL_Y, EYE_R - 1)
            draw_circle_eye(d, RIGHT_EYE_X, EYE_VISUAL_Y, EYE_R - 1)
            if hm == 0:
                draw_mouth(d, "straight")
            else:
                draw_mouth(d, "speaking", hm)
        create_face(f"{base_dir}/speaking_{i:02d}.png", draw_spk)

def gen_happy(base_dir="faces/happy"):
    ensure_dir(base_dir)
    # Happy eyes with a bouncing smile effect
    offsets = [0, -2, -4, -2, 0, 2, 4, 2]
    for i, off in enumerate(offsets):
        def draw_h(d, o=off):
            draw_arc_eye(d, LEFT_EYE_X, EYE_Y + 13, EYE_R, 180, 360)
            draw_arc_eye(d, RIGHT_EYE_X, EYE_Y + 13, EYE_R, 180, 360)
            draw_arc_eye(d, 399, MOUTH_Y - 20 + o, MOUTH_W // 2, 45, 135)
        create_face(f"{base_dir}/happy_{i+1:02d}.png", draw_h)

def gen_sad(base_dir="faces/sad"):
    ensure_dir(base_dir)
    # Sad eyes droop progressively
    droops = [0, 2, 4, 6, 4, 2]
    for i, droop in enumerate(droops):
        def draw_s(d, dr=droop):
            draw_line(d, LEFT_EYE_X - EYE_R, EYE_VISUAL_Y + 10 + dr, LEFT_EYE_X + EYE_R, EYE_VISUAL_Y - 10 + dr)
            draw_line(d, RIGHT_EYE_X - EYE_R, EYE_VISUAL_Y - 10 + dr, RIGHT_EYE_X + EYE_R, EYE_VISUAL_Y + 10 + dr)
            draw_mouth(d, "frown")
        create_face(f"{base_dir}/sad_{i+1:02d}.png", draw_s)

def gen_angry(base_dir="faces/angry"):
    ensure_dir(base_dir)
    # Trembling angry effect — slight X jitter on the eyes
    jitters = [0, -2, 0, 2, 0, -1, 0, 1]
    for i, jit in enumerate(jitters):
        def draw_a(d, j=jit):
            draw_line(d, LEFT_EYE_X - EYE_R + j, EYE_VISUAL_Y - 10, LEFT_EYE_X + EYE_R + j, EYE_VISUAL_Y + 10)
            draw_line(d, RIGHT_EYE_X - EYE_R - j, EYE_VISUAL_Y + 10, RIGHT_EYE_X + EYE_R - j, EYE_VISUAL_Y - 10)
            draw_mouth(d, "straight")
        create_face(f"{base_dir}/angry_{i+1:02d}.png", draw_a)

def gen_surprised(base_dir="faces/surprised"):
    ensure_dir(base_dir)
    # Surprise mouth pulsing slightly
    sizes = [18, 20, 22, 20, 18, 16, 18, 20]
    for i, s in enumerate(sizes):
        def draw_su(d, sz=s):
            draw_circle_eye(d, LEFT_EYE_X, EYE_VISUAL_Y, EYE_R - 2)
            draw_circle_eye(d, RIGHT_EYE_X, EYE_VISUAL_Y, EYE_R - 2)
            draw_ellipse(d, [399 - sz, MOUTH_Y - sz, 399 + sz, MOUTH_Y + sz], fill=MOUTH_DARK, outline=LINE_COLOR, width=LINE_WIDTH)
        create_face(f"{base_dir}/surprised_{i+1:02d}.png", draw_su)

def gen_sleepy(base_dir="faces/sleepy"):
    ensure_dir(base_dir)
    # Longer z-floating sequence
    for i in range(1, 9):
        z_offset = i * 4
        def draw_sleepy(d, off=z_offset):
            draw_regular_eyes(d, 1.0)
            draw_mouth(d, "straight")
            if off > 8:
                bx, by = 600, 130 - off
                s = 25
                draw_line(d, bx, by, bx+s, by, width=4)
                draw_line(d, bx+s, by, bx, by+s, width=4)
                draw_line(d, bx, by+s, bx+s, by+s, width=4)
            if off > 16: 
                bx, by = 650, 90 - off
                s = 15
                draw_line(d, bx, by, bx+s, by, width=3)
                draw_line(d, bx+s, by, bx, by+s, width=3)
                draw_line(d, bx, by+s, bx+s, by+s, width=3)
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
            draw_ellipse(d, [380 + off, 240, 400 + off, 260], fill=LINE_COLOR)
        create_face(f"{base_dir}/thinking_{i:02d}.png", draw_think)

def gen_dizzy(base_dir="faces/dizzy"):
    ensure_dir(base_dir)
    for i in range(1, 5):
        # alternate wavy mouth direction to make it look like it's shaking
        shift = LINE_WIDTH // 2
        def draw_dizzy1(d):
            draw_dizzy_eyes(d)
            draw_arc_eye(d, 380 + shift, 300, 20, 180, 360)
            draw_arc_eye(d, 420 - shift, 300, 20, 0, 180)
        def draw_dizzy2(d):
            draw_dizzy_eyes(d)
            draw_arc_eye(d, 380 + shift, 300, 20, 0, 180)
            draw_arc_eye(d, 420 - shift, 300, 20, 180, 360)
        create_face(f"{base_dir}/dizzy_{i:02d}.png", draw_dizzy1 if i % 2 == 0 else draw_dizzy2)

def gen_cheeky(base_dir="faces/cheeky"):
    ensure_dir(base_dir)
    # Tongue wagging side to side
    tongue_offsets = [10, 15, 20, 15, 10, 5, 0, 5]
    for i, toff in enumerate(tongue_offsets):
        def draw_chk(d, to=toff):
            draw_cheeky_eyes(d)
            m_left = 399 - (MOUTH_W // 2)
            m_right = 399 + (MOUTH_W // 2)
            draw_line(d, m_left, MOUTH_Y, m_right, MOUTH_Y)
            tc = 399 + to
            tr = 15
            bbox = [(tc - tr) * SCALE, MOUTH_Y * SCALE,
                    (tc + tr) * SCALE, (MOUTH_Y + tr * 2) * SCALE]
            d.ellipse(bbox, fill=TONGUE_COLOR, outline=LINE_COLOR, width=LINE_WIDTH * SCALE)
            # Re-draw mouth line on top
            x1, y1 = m_left * SCALE, MOUTH_Y * SCALE
            x2, y2 = m_right * SCALE, MOUTH_Y * SCALE
            w = LINE_WIDTH * SCALE
            d.line([(x1, y1), (x2, y2)], fill=LINE_COLOR, width=w)
            r = w / 2.0
            d.ellipse([x1-r, y1-r, x1+r, y1+r], fill=LINE_COLOR)
            d.ellipse([x2-r, y2-r, x2+r, y2+r], fill=LINE_COLOR)
        create_face(f"{base_dir}/cheeky_{i+1:02d}.png", draw_chk)

def gen_heart(base_dir="faces/heart"):
    ensure_dir(base_dir)
    scales = [1.0, 1.2, 1.5, 1.2, 1.0, 1.0]
    for i, s in enumerate(scales):
        create_face(f"{base_dir}/heart_{i:02d}.png", lambda d, s=s: (draw_heart_eye(d, LEFT_EYE_X, EYE_VISUAL_Y, s), draw_heart_eye(d, RIGHT_EYE_X, EYE_VISUAL_Y, s), draw_mouth(d, "smile")))

def gen_starry(base_dir="faces/starry_eyed"):
    ensure_dir(base_dir)
    for i in range(8):
        create_face(f"{base_dir}/starry_{i:02d}.png", lambda d, r=i*11.25: (draw_star_eye(d, LEFT_EYE_X, EYE_VISUAL_Y, r), draw_star_eye(d, RIGHT_EYE_X, EYE_VISUAL_Y, r), draw_mouth(d, "surprised")))

def gen_confused(base_dir="faces/confused"):
    ensure_dir(base_dir)
    for i in range(1, 5):
        # reuse wavy mouth logic alternating directions
        shift = LINE_WIDTH // 2
        def draw_conf1(d):
            draw_confused_eyes(d)
            draw_arc_eye(d, 380 + shift, 300, 20, 180, 360)
            draw_arc_eye(d, 420 - shift, 300, 20, 0, 180)
        def draw_conf2(d):
            draw_confused_eyes(d)
            draw_arc_eye(d, 380 + shift, 300, 20, 0, 180)
            draw_arc_eye(d, 420 - shift, 300, 20, 180, 360)
        create_face(f"{base_dir}/confused_{i:02d}.png", draw_conf1 if i % 2 == 0 else draw_conf2)
def gen_listening(base_dir="faces/listening"):
    ensure_dir(base_dir)
    # Attentive eyes - slightly wider, straight mouth
    for i in range(1, 3):
        create_face(f"{base_dir}/listening_{i:02d}.png", lambda d: (draw_circle_eye(d, LEFT_EYE_X, EYE_VISUAL_Y, EYE_R - 2), draw_circle_eye(d, RIGHT_EYE_X, EYE_VISUAL_Y, EYE_R - 2), draw_mouth(d, "straight")))

def gen_error(base_dir="faces/error"):
    ensure_dir(base_dir)
    create_face(f"{base_dir}/error_01.png", lambda d: (draw_dizzy_eyes(d), draw_mouth(d, "frown")))

def gen_capturing(base_dir="faces/capturing"):
    ensure_dir(base_dir)
    create_face(f"{base_dir}/capturing_01.png", lambda d: (draw_surprised_eyes(d), draw_mouth(d, "surprised")))

def gen_warmup(base_dir="faces/warmup"):
    ensure_dir(base_dir)
    create_face(f"{base_dir}/warmup_01.png", lambda d: (draw_regular_eyes(d, 0.5), draw_mouth(d, "straight")))
def gen_daydream(base_dir="faces/daydream"):
    """Eyes drift upward with floating thought bubbles — BMO lost in thought"""
    ensure_dir(base_dir)
    import math
    for i in range(10):
        drift = int(3 * math.sin(i * math.pi / 5))  # gentle up-down
        bubble_y = 180 - i * 8  # bubbles float upward
        def draw_dd(d, dr=drift, by=bubble_y, frame=i):
            # Dreamy half-closed eyes looking up
            draw_arc_eye(d, LEFT_EYE_X, EYE_Y - 3 + dr, EYE_R, 340, 200)
            draw_arc_eye(d, RIGHT_EYE_X, EYE_Y - 3 + dr, EYE_R, 340, 200)
            # Gentle straight mouth
            draw_mouth(d, "straight")
            # Floating thought bubbles (small circles rising)
            if frame > 2:
                draw_ellipse(d, [620, by + 20, 630, by + 30], fill=LINE_COLOR)
            if frame > 4:
                draw_ellipse(d, [635, by, 650, by + 15], fill=LINE_COLOR)
            if frame > 6:
                draw_ellipse(d, [642, by - 25, 665, by - 5], fill=LINE_COLOR)
        create_face(f"{base_dir}/daydream_{i+1:02d}.png", draw_dd)

def gen_bored(base_dir="faces/bored"):
    """Eyes scanning left and right — BMO looking around"""
    ensure_dir(base_dir)
    # Eye offsets for scanning: left, center, right, center, repeat
    offsets = [-8, -5, 0, 5, 8, 5, 0, -5]
    for i, off in enumerate(offsets):
        def draw_bored(d, o=off):
            # Arc eyes shifted horizontally
            draw_arc_eye(d, LEFT_EYE_X + o, EYE_Y, EYE_R, 335, 205)
            draw_arc_eye(d, RIGHT_EYE_X + o, EYE_Y, EYE_R, 335, 205)
            # Slight frown
            draw_arc_eye(d, 399, MOUTH_Y + 15, MOUTH_W // 2, 235, 305)
        create_face(f"{base_dir}/bored_{i+1:02d}.png", draw_bored)

def gen_jamming(base_dir="faces/jamming"):
    """Eyes closed, smiling, musical notes bouncing — BMO enjoying music"""
    ensure_dir(base_dir)
    import math
    for i in range(8):
        note_bounce = int(5 * math.sin(i * math.pi / 4))
        def draw_jam(d, nb=note_bounce, frame=i):
            # Closed happy eyes (straight lines slightly curved up)
            draw_line(d, LEFT_EYE_X - EYE_R, EYE_VISUAL_Y, LEFT_EYE_X + EYE_R, EYE_VISUAL_Y)
            draw_line(d, RIGHT_EYE_X - EYE_R, EYE_VISUAL_Y, RIGHT_EYE_X + EYE_R, EYE_VISUAL_Y)
            # Big smile
            draw_arc_eye(d, 399, MOUTH_Y - 20, MOUTH_W // 2, 45, 135)
            # Musical notes: ♪ drawn as small circles with stems
            # Note 1
            nx, ny = 620 + (frame % 4) * 5, 150 + nb
            draw_ellipse(d, [nx, ny, nx+10, ny+8], fill=LINE_COLOR)
            draw_line(d, nx+10, ny, nx+10, ny-20, width=3)
            draw_line(d, nx+10, ny-20, nx+16, ny-18, width=3)
            # Note 2 (offset)
            if frame > 2:
                nx2, ny2 = 650 - (frame % 3) * 4, 130 - nb
                draw_ellipse(d, [nx2, ny2, nx2+10, ny2+8], fill=LINE_COLOR)
                draw_line(d, nx2+10, ny2, nx2+10, ny2-20, width=3)
                draw_line(d, nx2+10, ny2-20, nx2+16, ny2-18, width=3)
        create_face(f"{base_dir}/jamming_{i+1:02d}.png", draw_jam)

def gen_curious(base_dir="faces/curious"):
    """One eye bigger than the other, tilted — BMO noticing something"""
    ensure_dir(base_dir)
    import math
    for i in range(8):
        # Subtle eye size pulsing
        big_r = EYE_R + 2 + int(3 * math.sin(i * math.pi / 4))
        small_r = EYE_R - 4
        def draw_cur(d, br=big_r, sr=small_r):
            # Big curious left eye
            draw_circle_eye(d, LEFT_EYE_X, EYE_VISUAL_Y, br)
            # Small squinting right eye
            draw_circle_eye(d, RIGHT_EYE_X, EYE_VISUAL_Y, sr)
            # Slightly asymmetric mouth
            draw_mouth(d, "straight")
        create_face(f"{base_dir}/curious_{i+1:02d}.png", draw_cur)

def gen_shhh(base_dir="faces/shhh"):
    """Shhh mouth with a cute whimsical X, animated eyes slightly squinting"""
    ensure_dir(base_dir)
    # 8 frames of animation to match others
    for i in range(8):
        # Eyes slowly half-close
        blink_amt = (4 - abs(i - 4)) * 0.1  # max ~0.4 blink
        # X mouth pulsates gently
        x_size = 10 + (4 - abs(i - 4)) * 1.5
        def draw_sh(d, blink=blink_amt, sz=int(x_size)):
            draw_regular_eyes(d, blink)
            draw_mouth(d, "mute", open_amount=sz)
        create_face(f"{base_dir}/shhh_{i+1:02d}.png", draw_sh)

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
    
    # Remove any leftover original (space-named) files that would cause frame jumping
    import glob
    for f in glob.glob("faces/**/* *.png", recursive=True):
        os.remove(f)
        print(f"Cleaned up original: {f}")
    
    print("Finished generating faces!")
