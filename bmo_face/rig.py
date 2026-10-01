"""Procedural face rig for BMO.

Every mouth and eye pose from the artwork lives in shapes.json as a contour
with the same number of points, so poses can be blended freely. The rig
drives those blends with springs and layers behaviour on top: blinks, winks,
glances, breathing, a nod on stressed syllables, "marks" (tongues, dimples,
sparkles, notes...) that pop in with an expression, and critters (bee,
ladybug, worm, butterfly) that BMO watches.

Mirrors web/bmo-face.js (FaceRig) - keep the two in step.
"""

from __future__ import annotations

import json
import math
import os
import random

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TAU = 2 * math.pi


def load_shapes(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, "shapes.json"), encoding="utf-8") as f:
        shapes = json.load(f)
    # Pre-convert contours to numpy once; blending is then a weighted sum.
    for m in shapes["mouths"].values():
        m["outer_np"] = np.asarray(m["outer"], dtype=np.float64)
        m["tongue_np"] = np.asarray(m["tongue"], dtype=np.float64)
    for e in shapes["eyes"].values():
        e["pts_np"] = np.asarray(e["pts"], dtype=np.float64)
        e["fill_rgb"] = np.asarray(_hex_rgb(e.get("fill", "#000000")), dtype=np.float64)
        e["stroke_rgb"] = np.asarray(_hex_rgb(e.get("strokeColor", "#000000")), dtype=np.float64)
        for d in e.get("details", []):
            d["pts_np"] = np.asarray(d["pts"], dtype=np.float64)
    for mk in shapes.get("marks", {}).values():
        for it in mk["items"]:
            it["pts_np"] = np.asarray(it["pts"], dtype=np.float64)
        allp = np.vstack([it["pts_np"] for it in mk["items"]])
        mk["centroid"] = allp.mean(axis=0)
    for c in shapes.get("critters", {}).values():
        for pt in c["parts"]:
            pt["pts_np"] = np.asarray(pt["pts"], dtype=np.float64)
    return shapes


def load_presets(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, "expressions.json"), encoding="utf-8") as f:
        return json.load(f)


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def ease_in_quad(t: float) -> float:
    return t * t


def ease_in_out_sine(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


def smoothstep(a: float, b: float, x: float) -> float:
    t = clamp((x - a) / (b - a))
    return t * t * (3 - 2 * t)


def wrap_pi(a: float) -> float:
    return a - TAU * math.floor(a / TAU + 0.5)


def _hex_rgb(h: str) -> list:
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def _rgb_hex(c) -> str:
    # floor(v + 0.5) rounds halves up like JS Math.round
    return "#" + "".join(f"{int(math.floor(clamp(float(v), 0, 255) + 0.5)):02x}" for v in c)


class Spring:
    """Damped spring. freq in Hz; damping 1.0 = critical (no overshoot)."""

    __slots__ = ("value", "target", "velocity", "freq", "damping")

    def __init__(self, value: float = 0.0, freq: float = 5.0, damping: float = 0.9):
        self.value = value
        self.target = value
        self.velocity = 0.0
        self.freq = freq
        self.damping = damping

    def step(self, dt: float) -> float:
        w = 2 * math.pi * self.freq
        n = max(1, math.ceil(dt * w / 0.3))  # keep semi-implicit Euler stable
        h = dt / n
        for _ in range(n):
            a = w * w * (self.target - self.value) - 2 * self.damping * w * self.velocity
            self.velocity += a * h
            self.value += self.velocity * h
        return self.value

    def snap(self, v: float | None = None) -> None:
        if v is None:
            v = self.target
        self.value = self.target = v
        self.velocity = 0.0


NO_LID_Y = -95.0
NO_LID2_Y = 95.0

SILENT = {"viseme": "X", "intensity": 0.0, "active": False, "onset": False}


def resolve_expression(presets: dict, name: str) -> dict:
    exprs = presets["expressions"]
    e = exprs.get(name) or exprs.get("idle") or {}
    d = presets["default"]

    def pick(k):
        return e[k] if k in e else d[k]

    return {
        "name": name,
        "mouth": pick("mouth"),
        "mouthMods": {**d["mouthMods"], **e.get("mouthMods", {})},
        "talk": {**d["talk"], **e.get("talk", {})},
        "eye": pick("eye"),
        "eyeScale": pick("eyeScale"),
        "eyeOffset": pick("eyeOffset"),
        "eyeSpin": pick("eyeSpin"),
        "lid": {**d["lid"], **e.get("lid", {})},
        "lid2": {**d["lid2"], **e.get("lid2", {})},
        "brows": pick("brows"),
        "marks": pick("marks"),
        "blush": pick("blush"),
        "blushColor": pick("blushColor"),
        "gaze": pick("gaze"),
        "blink": pick("blink"),
        "motion": pick("motion"),
        "head": {**d["head"], **e.get("head", {})},
        "breathe": pick("breathe"),
        "flash": pick("flash"),
        "critter": pick("critter"),
        "react": pick("react"),
        "enter": pick("enter"),
    }


# ------------------------------------------------------------------ behaviours
BLINK_MODES = {
    #            interval range   close   hold  open   double-blink chance
    "normal":    {"every": (2.2, 5.5), "c": 0.06, "h": 0.04, "o": 0.12, "dbl": 0.18},
    "attentive": {"every": (3.0, 6.5), "c": 0.055, "h": 0.03, "o": 0.11, "dbl": 0.10},
    "slow":      {"every": (3.0, 6.0), "c": 0.10, "h": 0.08, "o": 0.22, "dbl": 0.05},
    "sleepy":    {"every": (1.4, 3.2), "c": 0.16, "h": 0.25, "o": 0.45, "dbl": 0.25},
    "wink":      {"every": (2.2, 5.5), "c": 0.06, "h": 0.04, "o": 0.12, "dbl": 0.10},
    "none":      {"every": (1e9, 1e9), "c": 0.06, "h": 0.04, "o": 0.12, "dbl": 0.0},
}
WINK = {"every": (2.5, 5.0), "c": 0.08, "h": 0.35, "o": 0.18, "dbl": 0.0}  # right eye only


class Blinker:
    def __init__(self):
        self.phase = -1.0
        self.next = random.uniform(1.2, 3.0)
        self.queued = 0
        self.value = 0.0
        self.cfg = BLINK_MODES["normal"]

    def trigger(self, double: bool = False) -> None:
        if self.phase >= 0:
            return
        self.phase = 0.0
        self.queued = 1 if double else 0

    def update(self, dt: float, mode) -> float:
        self.cfg = BLINK_MODES.get(mode, BLINK_MODES["normal"]) if isinstance(mode, str) else mode
        c, h, o = self.cfg["c"], self.cfg["h"], self.cfg["o"]
        if self.phase >= 0:
            self.phase += dt
            p = self.phase
            if p < c:
                self.value = ease_in_quad(p / c)
            elif p < c + h:
                self.value = 1.0
            elif p < c + h + o:
                self.value = 1.0 - ease_in_out_sine((p - c - h) / o)
            else:
                self.value = 0.0
                self.phase = -1.0
                if self.queued > 0:
                    self.queued -= 1
                    self.next = 0.07
                else:
                    self.next = random.uniform(*self.cfg["every"])
        elif self.cfg["every"][0] >= 1e8:
            self.next = 1e9  # 'none': never blink (a later mode clamps this back down)
        else:
            self.next = min(self.next, self.cfg["every"][1]) - dt
            if self.next <= 0:
                self.trigger(random.random() < self.cfg["dbl"])
        return self.value


class Gaze:
    def __init__(self):
        self.x = Spring(0, 7, 0.72)  # saccades: quick with a tiny overshoot
        self.y = Spring(0, 7, 0.72)
        self.hold = 0.5
        self.mode = "wander"
        self.side = 1

    def pick(self, mode: str) -> None:
        r = random.uniform
        x = y = 0.0
        hold, freq = 1.5, 7.0

        def side():
            return -1 if random.random() < 0.5 else 1

        if mode == "wander":
            if random.random() < 0.3:
                x = r(14, 24) * side()
                y, hold = r(-12, 10), r(0.5, 1.3)
            else:
                x = r(-5, 5)
                y, hold = r(-3, 3), r(1.0, 3.2)
        elif mode == "attentive":
            x = r(-3, 3)
            y, hold = r(-2, 2), r(1.2, 3.5)
        elif mode == "think":
            q = random.random()
            if q < 0.75:
                self.side = -self.side
            x = 20 * self.side + r(-4, 4) if q < 0.85 else r(-4, 4)
            y = r(-20, -13)
            hold = r(0.9, 2.2)
        elif mode == "talk":
            if random.random() < 0.2:
                x = r(9, 15) * side()
                y, hold = r(-6, 4), r(0.4, 0.9)
            else:
                x = r(-4, 4)
                y, hold = r(-3, 2), r(0.8, 2.2)
        elif mode == "down":
            x = r(-9, 9)
            y, hold = r(9, 14), r(1.5, 3.5)
        elif mode == "shifty":  # detective: slow slides from side to side
            if random.random() < 0.8:
                self.side = -self.side
            x = r(18, 26) * self.side if random.random() < 0.85 else 0.0
            y, hold, freq = r(-2, 2), r(1.0, 2.4), 2.2
        elif mode == "away":  # bored: looks off and up, rarely back
            if random.random() < 0.18:
                x = r(-3, 3)
                y, hold = r(-2, 2), r(0.6, 1.2)
            else:
                x = r(14, 22) * self.side
                y, hold = r(-14, -6), r(2.5, 5)
            freq = 3.5
        else:  # fixed
            hold = 1.0
        self.x.target, self.y.target, self.hold = x, y, hold
        self.x.freq = self.y.freq = freq

    def update(self, dt: float, mode: str, target=None) -> None:
        if mode != self.mode:
            self.mode = mode
            self.hold = 0
        if mode == "track" and target is not None:
            self.x.target, self.y.target = target
            self.x.freq = self.y.freq = 5
        else:
            self.hold -= dt
            if self.hold <= 0:
                self.pick(mode)
        self.x.step(dt)
        self.y.step(dt)


def critter_pose(name: str, t: float) -> dict:
    """Critter paths in art pixels. facing: +1 moving right, -1 moving left."""
    if name == "bee":
        u = TAU * t / 8
        return {"x": 640 + 470 * math.sin(u),
                "y": 290 + 140 * math.sin(2 * u + 0.6) + 6 * math.sin(TAU * 9 * t),
                "facing": clamp(math.cos(u) * 4, -1, 1),
                "angle": 0.12 * math.sin(TAU * 0.7 * t),
                "flap": 0.55 + 0.45 * abs(math.sin(TAU * 13 * t)), "sx": 1.0, "sy": 1.0}
    if name == "ladybug":
        s = math.fmod(t, 15)
        if s < 7:
            x, facing = lerp(-110, 1390, s / 7), 1
        elif s < 7.5:
            x, facing = 1390, 1
        elif s < 14.5:
            x, facing = lerp(1390, -110, (s - 7.5) / 7), -1
        else:
            x, facing = -110, -1
        return {"x": x, "y": 652 - 3 * abs(math.sin(TAU * 3 * t)), "facing": facing,
                "angle": 0.07 * math.sin(TAU * 3 * t), "flap": 1.0, "sx": 1.0, "sy": 1.0}
    if name == "worm":
        s, k = math.fmod(t, 18), math.sin(TAU * 1.1 * t)
        return {"x": 1400 - 1520 * min(s, 16) / 16 + 18 * k, "y": 600, "facing": -1,
                "angle": 0.03 * k, "flap": 1.0, "sx": 1 + 0.1 * k, "sy": 1 - 0.07 * k}
    if name == "butterfly":
        u = TAU * t / 12
        return {"x": 640 + 520 * math.sin(u),
                "y": 165 + 60 * math.sin(TAU * t / 6 + 1) + 12 * math.sin(TAU * 0.9 * t),
                "facing": clamp(math.cos(u) * 4, -1, 1),
                "angle": 0.18 * math.sin(TAU * t / 3.3), "flap": 1.0,
                "sx": 0.3 + 0.7 * abs(math.cos(TAU * 2.4 * t)), "sy": 1.0}
    return {"x": -500, "y": -500, "facing": 1, "angle": 0.0, "flap": 1.0, "sx": 1.0, "sy": 1.0}


def heartbeat(t: float) -> float:
    """Lub-dub, once a second (0..~1)."""
    ph = math.fmod(t, 1.0)
    p1 = ph - 1 if ph > 0.5 else ph
    return math.exp(-((p1 / 0.06) ** 2)) + 0.6 * math.exp(-(((ph - 0.22) / 0.07) ** 2))


JAW_VISEMES = {"C", "D", "E"}


def _rot(pts: np.ndarray, cx: float, cy: float, ang: float) -> np.ndarray:
    c, s = math.cos(ang), math.sin(ang)
    dx, dy = pts[:, 0] - cx, pts[:, 1] - cy
    return np.stack([dx * c - dy * s + cx, dx * s + dy * c + cy], axis=1)


# ------------------------------------------------------------------------- rig
class FaceRig:
    def __init__(self, shapes: dict | None = None, presets: dict | None = None):
        self.shapes = shapes or load_shapes()
        self.presets = presets or load_presets()
        self.t = 0.0
        self.springs: list[Spring] = []

        def S(v, f, d):
            s = Spring(v, f, d)
            self.springs.append(s)
            return s

        sh = self.shapes
        self.mouth_w = {k: S(1.0 if k == "smile" else 0.0, 5, 0.9) for k in sh["mouthOrder"]}
        self.eye_w = {k: S(1.0 if k == "open" else 0.0, 4.5, 0.85) for k in sh["eyeOrder"] if k != "closed"}
        self.mark_vis = {k: S(0, 4.5, 0.55) for k in sh.get("marks", {})}
        self.p = {
            "smile": S(0, 5, 0.85), "jaw": S(1, 9, 0.55), "width": S(1, 5, 0.8),
            "mdx": S(0, 4, 0.85), "mdy": S(0, 4, 0.85), "mtilt": S(0, 4, 0.85),
            "esx": S(1, 4.5, 0.55), "esy": S(1, 4.5, 0.55), "eox": S(0, 4, 0.85), "eoy": S(0, 4, 0.85),
            "lidY": S(NO_LID_Y, 4, 0.9), "lidSlope": S(0, 4, 0.9), "lidLine": S(0, 4, 0.9), "lidLen": S(46, 4, 0.9),
            "lid2Y": S(NO_LID2_Y, 4, 0.9), "lid2Slope": S(0, 4, 0.9), "lid2Line": S(0, 4, 0.9), "lid2Len": S(46, 4, 0.9),
            "blush": S(0, 1.5, 1), "tilt": S(0, 2.5, 0.8), "headDy": S(0, 2.5, 0.8),
            "bob": S(0, 5, 0.38), "squash": S(0, 6, 0.4), "talkMix": S(0, 5, 1),
            "motion": S(0, 1.5, 1), "breathe": S(1, 1, 1), "spinSpeed": S(0, 1.2, 1),
        }
        self.brows = [
            {"ox": S(0, 5, 0.8), "oy": S(-100, 5, 0.8), "ix": S(0, 5, 0.8), "iy": S(-100, 5, 0.8), "w": S(0, 5, 0.9)}
            for _ in range(2)
        ]
        self.critter = {"name": None, "t": 0.0, "vis": S(0, 3, 0.7), "pose": None}
        self.blinker = Blinker()
        self.winker = Blinker()
        self.gaze = Gaze()
        self.speech = dict(SILENT)
        self.spin_angle = 0.0
        self.flash = 0.0
        self.wink = 0.0
        self._swap = -1.0          # glyph-eye swap progress (0..1), -1 when idle
        self._swap_targets = None  # eye weights to apply at the swap midpoint
        self.blink = 0.0
        self._was_talking = False
        self._intro = -1.0
        self._motion_kind = None
        self.expr: dict = {}
        self.set_expression("idle", instant=True)

    # ------------------------------------------------------------- control
    def set_expression(self, name: str, instant: bool = False) -> None:
        """Switch expression; springs carry the transition."""
        e = resolve_expression(self.presets, name)
        self.expr = e
        p = self.p
        for k, s in self.mouth_w.items():
            s.target = e["mouth"].get(k, 0.0)
        # Glyph eyes (hearts, stars, spirals...) can't morph cleanly into other
        # shapes, so those swaps shrink the eyes away and pop the new ones in.
        eye_targets = {k: e["eye"].get(k, 0.0) for k in self.eye_w}
        keys = list(self.eye_w)

        def dominant(get):
            best = keys[0]
            for k in keys[1:]:
                if get(k) > get(best):
                    best = k
            return best

        was = dominant(lambda k: self.eye_w[k].value)
        nxt = dominant(lambda k: eye_targets[k])
        glyph = lambda k: bool(self.shapes["eyes"][k].get("glyph"))  # noqa: E731
        if not instant and was != nxt and (glyph(was) or glyph(nxt)):
            self._swap_targets = eye_targets
            if self._swap < 0 or self._swap >= 0.5:
                self._swap = 0.0
        else:
            self._swap_targets = None
            for k, s in self.eye_w.items():
                s.target = eye_targets[k]
        for k, s in self.mark_vis.items():
            s.target = 1.0 if k in e["marks"] else 0.0
        mm = e["mouthMods"]
        p["smile"].target, p["jaw"].target, p["width"].target = mm["smile"], mm["jaw"], mm["width"]
        p["mdx"].target, p["mdy"].target, p["mtilt"].target = mm["dx"], mm["dy"], mm["tilt"]
        p["esx"].target, p["esy"].target = e["eyeScale"]
        p["eox"].target, p["eoy"].target = e["eyeOffset"]
        for pre, lid in (("lid", e["lid"]), ("lid2", e["lid2"])):
            p[pre + "Y"].target, p[pre + "Slope"].target = lid["y"], lid["slope"]
            p[pre + "Line"].target, p[pre + "Len"].target = lid["line"], lid["len"]
        p["blush"].target = e["blush"]
        p["tilt"].target = math.radians(e["head"]["tilt"])
        p["headDy"].target = e["head"]["dy"]
        p["motion"].target = 1.0 if e["motion"] else 0.0
        p["breathe"].target = e["breathe"]
        p["spinSpeed"].target = e["eyeSpin"]
        for i, b in enumerate(self.brows):
            key = e["brows"][i]
            if not key:
                b["w"].target = 0.0
                continue
            (ox, oy), (ix, iy), w = self.presets["brows"][key]
            if b["w"].value < 1:
                # grow in place from the brow's midpoint
                mx, my = (ox + ix) / 2, (oy + iy) / 2
                for k, v in (("ox", mx), ("oy", my), ("ix", mx), ("iy", my)):
                    b[k].snap(v)
            b["ox"].target, b["oy"].target, b["ix"].target, b["iy"].target, b["w"].target = ox, oy, ix, iy, w
        if e["motion"]:
            self._motion_kind = e["motion"]
        c = self.critter
        if e["critter"]:
            if c["name"] != e["critter"] or c["vis"].value < 0.05:
                c["name"] = e["critter"]
                c["t"] = 0.0
                c["vis"].snap(0)
            c["vis"].target = 1.0
        else:
            c["vis"].target = 0.0
        if e["flash"]:
            self.flash = 1.0
        if instant:
            for s in self.springs:
                s.snap()
        elif e["enter"]:
            pop = e["enter"].get("eyePop")
            if pop:
                p["esx"].value *= pop
                p["esy"].value *= pop
            kick = e["enter"].get("headKick")
            if kick:
                p["bob"].velocity += kick

    def play_intro(self) -> None:
        """Wake-up: eyes shut, then open with a stretch."""
        self._intro = 0.0

    def set_speech(self, speech: dict) -> None:
        """Latest lip-sync result: {viseme, intensity 0..1, active, onset}."""
        self.speech = speech

    # -------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        dt = min(dt, 0.1)
        self.t += dt
        e, p, sp = self.expr, self.p, self.speech
        talking = bool(sp.get("active"))
        vis = sp.get("viseme", "X")
        intensity = float(sp.get("intensity", 0.0))

        # Critter: advance its path; BMO watches it and reacts when it's close.
        c = self.critter
        near, track = 0.0, None
        if c["name"] and (c["vis"].target > 0 or c["vis"].value > 0.01):
            c["t"] += dt
            q = c["pose"] = critter_pose(c["name"], c["t"])
            if e["critter"] == c["name"]:
                track = (clamp((q["x"] - 640) * 0.045, -24, 24), clamp((q["y"] - 300) * 0.06, -16, 18))
                if e["react"]:
                    rad = e["react"]["radius"]
                    near = smoothstep(rad, rad * 0.45, math.hypot(q["x"] - 640, q["y"] - 400)) * c["vis"].value

        react = e["react"]
        for k, s in self.mouth_w.items():
            if talking:
                s.target = 1.0 if k == vis else 0.0
                s.freq, s.damping = 11, 0.92
            else:
                rest = e["mouth"].get(k, 0.0)
                s.target = lerp(rest, react["mouth"].get(k, 0.0), near) if react else rest
                s.freq, s.damping = 5, 0.88
        if react:
            k = 1 + (react["eyeScale"] - 1) * near
            p["esx"].target, p["esy"].target = e["eyeScale"][0] * k, e["eyeScale"][1] * k
        # Marks on the mouth (tongue, dimples...) tuck away while talking.
        for k, s in self.mark_vis.items():
            on = k in e["marks"] and not (talking and self.shapes["marks"][k]["anchor"] == "mouth")
            s.target = 1.0 if on else 0.0
        mm, tk = e["mouthMods"], e["talk"]
        p["talkMix"].target = 1.0 if talking else 0.0
        p["smile"].target = tk["smile"] if talking else mm["smile"]
        p["width"].target = tk["width"] if talking else mm["width"]
        if talking:
            p["jaw"].target = 0.78 + 0.34 * intensity if vis in JAW_VISEMES else 1.0
        else:
            p["jaw"].target = mm["jaw"]
        p["mdx"].target = 0 if talking else mm["dx"]
        p["mdy"].target = 0 if talking else mm["dy"]
        p["mtilt"].target = 0 if talking else mm["tilt"]

        if talking and sp.get("onset"):
            p["bob"].velocity += 55 + 50 * intensity  # nod into the stressed syllable
            p["squash"].velocity += 4 + 4 * intensity
        if talking and not self._was_talking and random.random() < 0.5:
            self.blinker.trigger()
        self._was_talking = talking

        intro_blink = 0.0
        if self._intro >= 0:
            self._intro += dt
            t = self._intro
            if t < 0.7:
                intro_blink = 1.0
                p["headDy"].value = 22
            elif t < 1.25:
                intro_blink = 1 - ease_in_out_sine((t - 0.7) / 0.55)
                if t - dt < 0.7:
                    p["esy"].value = 1.25
                    p["bob"].velocity -= 120
            else:
                self._intro = -1.0

        self.blink = max(self.blinker.update(dt, e["blink"]), intro_blink)
        self.wink = self.winker.update(dt, WINK if e["blink"] == "wink" else BLINK_MODES["none"])
        self.gaze.update(dt, "talk" if talking else e["gaze"], track)
        self.flash *= math.exp(-dt / 0.14)
        if self._swap >= 0:
            before = self._swap
            self._swap += dt / 0.26
            if before < 0.5 <= self._swap and self._swap_targets is not None:
                for k, s in self.eye_w.items():
                    s.snap(self._swap_targets[k])
                self.spin_angle = 0.0  # new glyphs appear upright
                self._swap_targets = None
            if self._swap >= 1:
                self._swap = -1.0
        for s in self.springs:
            s.step(dt)

        # Spinning eyes (dizzy); once the spin stops they settle back upright.
        self.spin_angle += p["spinSpeed"].value * dt
        if abs(p["spinSpeed"].target) < 1e-3:
            self.spin_angle -= wrap_pi(self.spin_angle) * (1 - math.exp(-dt * 5))

    # ------------------------------------------------------------ geometry
    def frame(self) -> dict:
        """Current face as plain geometry in art space (1280x720)."""
        S, p, t, e = self.shapes, self.p, self.t, self.expr

        hx = 0.0
        hy = p["headDy"].value + p["bob"].value
        tilt = p["tilt"].value
        hy += math.sin(TAU * t / 4.2) * 2.2 * p["breathe"].value
        tilt += math.sin(TAU * t / 7.3) * 0.006 * p["breathe"].value
        m = p["motion"].value
        kind = self._motion_kind
        eye_mul, eye_rot = 1.0, 0.0
        if kind == "bounce":
            hy -= abs(math.sin(math.pi * t * 1.5)) * 9 * m
        elif kind == "hop":
            hy -= abs(math.sin(math.pi * t * 2.3)) * 15 * m
        elif kind == "tremble":
            hx += math.sin(TAU * t * 13) * 2.2 * m
        elif kind == "droop":
            hy += (1 - math.cos(TAU * t / 6)) * 5 * m
            tilt += math.sin(TAU * t / 6) * 0.01 * m
        elif kind == "woozy":
            hx += math.cos(TAU * 0.55 * t) * 12 * m
            hy += math.sin(TAU * 0.55 * t) * 8 * m
            tilt += math.sin(TAU * 0.55 * t) * 0.025 * m
        elif kind == "pulse":
            eye_mul = 1 + 0.12 * heartbeat(t) * m
        elif kind == "twinkle":
            eye_rot = 0.16 * math.sin(TAU * 0.45 * t) * m
            eye_mul = 1 + 0.05 * math.sin(TAU * 1.3 * t) * m
        elif kind == "shake":
            ph = math.fmod(t, 2.4)
            env = math.sin(math.pi * ph / 0.4) if ph < 0.4 else 0.0
            hx += math.sin(TAU * 16 * t) * 9 * env * m
        elif kind == "groove":
            hy -= abs(math.sin(TAU * t)) * 11 * m
            tilt += math.sin(math.pi * t) * 0.025 * m
        cT, sT = math.cos(tilt), math.sin(tilt)

        def head(pts: np.ndarray) -> np.ndarray:
            dx, dy = pts[:, 0] - 640, pts[:, 1] - 420
            return np.stack([640 + dx * cT - dy * sT + hx, 420 + dx * sT + dy * cT + hy], axis=1)

        # ---- mouth: weighted blend of every pose
        ws = [(k, max(0.0, self.mouth_w[k].value)) for k in S["mouthOrder"]]
        ws = [(k, w) for k, w in ws if w > 1e-4] or [("X", 1.0)]
        wsum = sum(w for _, w in ws)
        outer = tongue = None
        stroke = tT = tB = 0.0
        for k, w0 in ws:
            w, M = w0 / wsum, S["mouths"][k]
            outer = M["outer_np"] * w if outer is None else outer + M["outer_np"] * w
            tongue = M["tongue_np"] * w if tongue is None else tongue + M["tongue_np"] * w
            stroke += M["stroke"] * w
            tT += M["teethTop"] * w
            tB += M["teethBot"] * w
        min_x, max_x = float(outer[:, 0].min()), float(outer[:, 0].max())
        top, bottom = float(outer[:, 1].min()), float(outer[:, 1].max())
        jaw, width, bend = p["jaw"].value, p["width"].value, p["smile"].value
        cM, sM = math.cos(p["mtilt"].value), math.sin(p["mtilt"].value)
        mdx, mdy = p["mdx"].value, p["mdy"].value

        def mouth_xf(pts: np.ndarray) -> np.ndarray:
            y = top + (pts[:, 1] - top) * jaw
            x = 640 + (pts[:, 0] - 640) * width
            u = np.clip((x - 640) / 110, -1.6, 1.6)
            y = y - bend * 24 * u * u
            dx, dy = x - 640, y - 470
            return head(np.stack([640 + dx * cM - dy * sM + mdx, 470 + dx * sM + dy * cM + mdy], axis=1))

        def teeth_line(y: float) -> np.ndarray:
            xs = np.linspace(min_x - 40, max_x + 40, 25)
            return mouth_xf(np.stack([xs, np.full_like(xs, y)], axis=1))

        mouth = {
            "outer": mouth_xf(outer),
            "tongue": mouth_xf(tongue),
            "stroke": stroke,
            "teethTop": teeth_line(tT) if tT > top + 0.75 else None,
            "teethBot": teeth_line(tB) if tB < bottom - 0.75 else None,
        }
        openness = clamp(((bottom - top) * jaw - 18) / 110)

        # ---- eyes: blend poses (each pose mirrors for the right eye unless noMirror)
        blink_pose = S["eyes"]["closed"]
        ews = [(k, max(0.0, s.value)) for k, s in self.eye_w.items()]
        ews = [(k, w) for k, w in ews if w > 1e-4] or [("open", 1.0)]
        esum = sum(w for _, w in ews)
        base = [None, None]
        e_stroke = open_like = 0.0
        fill = np.zeros(3)
        s_col = np.zeros(3)
        flip = np.array([-1.0, 1.0])
        for k, w0 in ews:
            w, E = w0 / esum, S["eyes"][k]
            for side in (0, 1):
                pts = E["pts_np"] * flip if side == 1 and not E.get("noMirror") else E["pts_np"]
                base[side] = pts * w if base[side] is None else base[side] + pts * w
            e_stroke += E["stroke"] * w
            fill += E["fill_rgb"] * w
            s_col += E["stroke_rgb"] * w
            if E.get("blinks"):
                open_like += w
        sq = p["squash"].value
        swap_k = max(0.03, abs(math.cos(math.pi * self._swap))) if self._swap >= 0 else 1.0
        sx = p["esx"].value * (1 + 0.035 * sq) * eye_mul * swap_k
        sy = p["esy"].value * (1 - 0.07 * sq) * (1 + 0.04 * openness) * eye_mul * swap_k
        lift = 5 * openness * p["talkMix"].value
        rot = self.spin_angle + eye_rot
        cR, sR = math.cos(rot), math.sin(rot)
        gx, gy = self.gaze.x.value, self.gaze.y.value
        lid_y, lid_slope = p["lidY"].value, p["lidSlope"].value
        lid2_y, lid2_slope = p["lid2Y"].value, p["lid2Slope"].value
        fill_hex, stroke_hex = _rgb_hex(fill), _rgb_hex(s_col)
        eyes, brows = [], []
        for side in (0, 1):
            mir = 1 if side == 0 else -1
            blink_amt = max(self.blink, self.wink if side == 1 else 0.0) * open_like
            cx0, cy0 = S["eyeCenters"][side]
            sock_x, sock_y = cx0 + p["eox"].value * mir, cy0 + p["eoy"].value - lift
            cx, cy = sock_x + gx, sock_y + gy

            def place(rel: np.ndarray, cx=cx, cy=cy) -> np.ndarray:
                x, y = rel[:, 0] * sx, rel[:, 1] * sy
                return head(np.stack([cx + x * cR - y * sR, cy + x * sR + y * cR], axis=1))

            rel = base[side] + (blink_pose["pts_np"] - base[side]) * blink_amt
            details = []
            for k, w0 in ews:
                E = S["eyes"][k]
                if not E.get("details"):
                    continue
                a = smoothstep(0.35, 0.9, w0 / esum) * (1 - blink_amt)
                if a < 0.01:
                    continue
                for d in E["details"]:
                    mirror_d = side == 1 and not E.get("noMirror") and not d.get("noMirror")
                    dp = d["pts_np"] * flip if mirror_d else d["pts_np"]
                    details.append({"pts": place(dp), "fill": d["fill"], "alpha": d["alpha"] * a})
            # Lids sit on the socket and only partly follow the gaze.
            lcx, lcy = sock_x + gx * 0.15, sock_y + gy * 0.7

            def at(xi):
                return lid_y + lid_slope * xi

            def at2(xi):
                return lid2_y + lid2_slope * xi

            def lid_pts(seg, lcx=lcx, lcy=lcy, mir=mir):
                seg = np.asarray(seg, dtype=np.float64)
                return head(np.stack([lcx + seg[:, 0] * mir, lcy + seg[:, 1]], axis=1))

            clip = None
            if lid_y > -70 or lid2_y < 70:
                clip = lid_pts([[-300, at(-300)], [300, at(300)], [300, at2(300)], [-300, at2(-300)]])
            lid_lines = []
            if p["lidLine"].value > 0.5:
                L = p["lidLen"].value
                lid_lines.append({"pts": lid_pts([[-L, at(-L)], [L, at(L)]]), "w": p["lidLine"].value})
            if p["lid2Line"].value > 0.5:
                L = p["lid2Len"].value
                lid_lines.append({"pts": lid_pts([[-L, at2(-L)], [L, at2(L)]]), "w": p["lid2Line"].value})
            brow = None
            br = self.brows[side]
            if br["w"].value > 0.4:
                bx = cx0 + gx * 0.3
                by = cy0 + gy * 0.25 - 7 * sq - lift * 1.4
                seg = np.array([
                    [bx + br["ox"].value * mir, by + br["oy"].value],
                    [bx + br["ix"].value * mir, by + br["iy"].value],
                ])
                brow = {"pts": head(seg), "w": br["w"].value}
                brows.append(brow)
            eyes.append({
                "pts": place(rel), "stroke": lerp(e_stroke, blink_pose["stroke"], blink_amt),
                "fill": fill_hex, "strokeColor": stroke_hex, "details": details,
                "clip": clip, "lidLines": lid_lines, "brow": brow,
            })

        # ---- marks: pop in/out (scale about their centre) with small animations
        marks = []
        for k, sv in self.mark_vis.items():
            vis = sv.value
            if vis < 0.01:
                continue
            M = S["marks"][k]
            an = M.get("anim") or {}
            ox = oy = 0.0
            if M["anchor"] in ("eyeL", "eyeR"):
                side = 0 if M["anchor"] == "eyeL" else 1
                cx0, cy0 = S["eyeCenters"][side]
                mir = 1 if side == 0 else -1
                ox = cx0 + p["eox"].value * mir + gx * 0.5 - M["ref"][0]
                oy = cy0 + p["eoy"].value + gy * 0.5 - lift - M["ref"][1]
            scale, alpha, arot, ax, ay, aroot = vis, clamp(vis * 1.5), 0.0, 0.0, 0.0, None
            typ = an.get("type")
            if typ == "wiggle":
                arot, aroot = an["amp"] * math.sin(TAU * an["freq"] * t), an["root"]
            elif typ == "blink":
                alpha *= 1.0 if math.sin(TAU * an["freq"] * t) > -0.3 else 0.15
            elif typ == "twinkle":
                k2 = 0.5 + 0.5 * math.sin(TAU * (an["freq"] * t + an["phase"]))
                scale *= 0.55 + 0.6 * k2
                alpha *= 0.35 + 0.65 * k2
                arot = 0.3 * math.sin(TAU * (0.3 * t + an["phase"]))
            elif typ == "float":
                u = math.fmod(t / an["period"] + an["phase"], 1.0)
                ay, ax = -an["rise"] * u, 8 * math.sin(TAU * u)
                alpha *= math.sin(math.pi * u)
            mx, my = M["centroid"]
            rx, ry = aroot if aroot else (mx, my)
            for idx, it in enumerate(M["items"]):
                sh = an["amp"] * math.sin(TAU * an["freq"] * t + idx * 1.7) if typ == "shiver" else 0.0
                pts = _rot(it["pts_np"], rx, ry, arot) if arot else it["pts_np"]
                pts = np.stack([mx + (pts[:, 0] - mx) * scale + ax + ox + sh,
                                my + (pts[:, 1] - my) * scale + ay + oy], axis=1)
                pts = mouth_xf(pts) if M["anchor"] == "mouth" else head(pts)
                if alpha > 0.01:
                    marks.append({"key": k, "kind": it["kind"], "closed": it["closed"], "pts": pts,
                                  "width": it["width"] * max(0.0, scale), "color": it["color"], "alpha": clamp(alpha)})

        # ---- critter (in front of the face, not attached to BMO's head)
        critter = None
        c = self.critter
        if c["name"] and c["pose"] and c["vis"].value > 0.01:
            C, q = S["critters"][c["name"]], c["pose"]
            k = C["width"] / C["size"][0] * c["vis"].value
            flipx = q["facing"] * C["faces"] * q["sx"]
            ang = q["angle"] + C.get("tilt", 0) * (1 if q["facing"] > 0 else -1 if q["facing"] < 0 else 0)
            cA, sA = math.cos(ang), math.sin(ang)
            wx, wy = C.get("wingRoot", (0, 0))
            parts = []
            for pt in C["parts"]:
                v = pt["pts_np"]
                if pt["group"] == "wing":
                    v = np.stack([wx + (v[:, 0] - wx) * q["flap"], wy + (v[:, 1] - wy) * q["flap"]], axis=1)
                x = (v[:, 0] - C["size"][0] / 2) * k * flipx
                y = (v[:, 1] - C["size"][1] / 2) * k * q["sy"]
                parts.append({"pts": np.stack([q["x"] + x * cA - y * sA, q["y"] + x * sA + y * cA], axis=1),
                              "fill": pt["fill"], "stroke": pt["stroke"], "width": pt["width"] * k,
                              "alpha": pt["alpha"], "closed": pt["closed"]})
            critter = {"name": c["name"], "center": (q["x"], q["y"]), "parts": parts}

        blush = None
        if p["blush"].value > 0.01:
            blush = {"alpha": clamp(p["blush"].value),
                     "centers": head(np.array([[233.0, 393.0], [1047.0, 393.0]])),
                     "color": e["blushColor"] or S["colors"]["blush"]}

        return {"eyes": eyes, "brows": brows, "mouth": mouth, "marks": marks, "critter": critter,
                "blush": blush, "flash": self.flash if self.flash > 0.01 else 0.0, "expression": e["name"]}
