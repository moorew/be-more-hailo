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
EYE_Y = 195 # Tuned: original center Y=199.7, was 201.7 at 197, now -2 → 195
EYE_R = 18
MOUTH_Y = 302 # Tuned: original center Y=301.5, was 304.5 at 305, now -3 → 302
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
        # Closed eyes (straight lines)
        draw_line(draw, LEFT_EYE_X - EYE_R, EYE_Y, LEFT_EYE_X + EYE_R, EYE_Y)
        draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_Y, RIGHT_EYE_X + EYE_R, EYE_Y)
    elif blink > 0.0:
        # Half blink
        draw_arc_eye(draw, LEFT_EYE_X, EYE_Y - int((EYE_R/2) * blink), EYE_R, 345, 195)
        draw_arc_eye(draw, RIGHT_EYE_X, EYE_Y - int((EYE_R/2) * blink), EYE_R, 345, 195)
    else:
        # Open eyes (steeper U shape extends past 180)
        draw_arc_eye(draw, LEFT_EYE_X, EYE_Y, EYE_R, 335, 205)
        draw_arc_eye(draw, RIGHT_EYE_X, EYE_Y, EYE_R, 335, 205)

def draw_angry_eyes(draw):
    draw_line(draw, LEFT_EYE_X - EYE_R, EYE_Y - 10, LEFT_EYE_X + EYE_R, EYE_Y + 10)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_Y + 10, RIGHT_EYE_X + EYE_R, EYE_Y - 10)
    
def draw_happy_eyes(draw):
    draw_arc_eye(draw, LEFT_EYE_X, EYE_Y + 10, EYE_R, 180, 360)
    draw_arc_eye(draw, RIGHT_EYE_X, EYE_Y + 10, EYE_R, 180, 360)
    
def draw_surprised_eyes(draw):
    draw_circle_eye(draw, LEFT_EYE_X, EYE_Y, EYE_R - 2)
    draw_circle_eye(draw, RIGHT_EYE_X, EYE_Y, EYE_R - 2)

def draw_sad_eyes(draw):
    draw_line(draw, LEFT_EYE_X - EYE_R, EYE_Y + 10, LEFT_EYE_X + EYE_R, EYE_Y - 10)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_Y - 10, RIGHT_EYE_X + EYE_R, EYE_Y + 10)

def draw_dizzy_eyes(draw):
    draw_line(draw, LEFT_EYE_X - 15, EYE_Y - 15, LEFT_EYE_X + 15, EYE_Y + 15)
    draw_line(draw, LEFT_EYE_X - 15, EYE_Y + 15, LEFT_EYE_X + 15, EYE_Y - 15)
    draw_line(draw, RIGHT_EYE_X - 15, EYE_Y - 15, RIGHT_EYE_X + 15, EYE_Y + 15)
    draw_line(draw, RIGHT_EYE_X - 15, EYE_Y + 15, RIGHT_EYE_X + 15, EYE_Y - 15)

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
    draw_circle_eye(draw, LEFT_EYE_X, EYE_Y, EYE_R + 5)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_Y, RIGHT_EYE_X + EYE_R, EYE_Y)

def draw_cheeky_eyes(draw):
    draw_circle_eye(draw, LEFT_EYE_X, EYE_Y, EYE_R - 2)
    draw_line(draw, RIGHT_EYE_X - EYE_R, EYE_Y, RIGHT_EYE_X + EYE_R, EYE_Y)

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
        # straight line with a U underneath for tongue
        draw_line(draw, m_left, MOUTH_Y, m_right, MOUTH_Y)
        draw_arc_eye(draw, 399 + 15, MOUTH_Y, 15, 0, 180)
    elif type == "wavy":
        # squiggly mouth for dizzy (shift centers to account for PIL inward stroke)
        shift = LINE_WIDTH // 2
        draw_arc_eye(draw, 399 - 15 + shift, MOUTH_Y, 15, 180, 360)
        draw_arc_eye(draw, 399 + 15 - shift, MOUTH_Y, 15, 0, 180)


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
    heights = [15, 35, 60, 45, 25, 55, 30]
    for i, h in enumerate(heights):
        # Speaking BMO has fully open circular eyes, matching the idle eye radius
        def draw_spk(d, hm=h):
            draw_circle_eye(d, LEFT_EYE_X, EYE_Y, EYE_R - 1) # matching size exactly
            draw_circle_eye(d, RIGHT_EYE_X, EYE_Y, EYE_R - 1)
            draw_mouth(d, "speaking", hm)
        create_face(f"{base_dir}/speaking_{i:02d}.png", draw_spk)

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
            # Draw a Z using lines
            if off > 10:
                bx, by = 600, 120 - off
                s = 25
                draw_line(d, bx, by, bx+s, by, width=4)
                draw_line(d, bx+s, by, bx, by+s, width=4)
                draw_line(d, bx, by+s, bx+s, by+s, width=4)
            if off > 20: 
                bx, by = 650, 80 - off
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
    for i in range(1, 5):
        create_face(f"{base_dir}/cheeky_{i:02d}.png", lambda d: (draw_cheeky_eyes(d), draw_mouth(d, "tongue")))

def gen_heart(base_dir="faces/heart"):
    ensure_dir(base_dir)
    scales = [1.0, 1.2, 1.5, 1.2, 1.0, 1.0]
    for i, s in enumerate(scales):
        create_face(f"{base_dir}/heart_{i:02d}.png", lambda d, s=s: (draw_heart_eye(d, LEFT_EYE_X, EYE_Y, s), draw_heart_eye(d, RIGHT_EYE_X, EYE_Y, s), draw_mouth(d, "smile")))

def gen_starry(base_dir="faces/starry_eyed"):
    ensure_dir(base_dir)
    for i in range(8):
        create_face(f"{base_dir}/starry_{i:02d}.png", lambda d, r=i*11.25: (draw_star_eye(d, LEFT_EYE_X, EYE_Y, r), draw_star_eye(d, RIGHT_EYE_X, EYE_Y, r), draw_mouth(d, "surprised")))

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
    
    print("Finished generating faces!")
