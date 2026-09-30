"""Procedural face rig for BMO.

Every mouth and eye pose from the artwork lives in shapes.json as a contour
with the same number of points, so poses can be blended freely. The rig
drives those blends with springs and layers behaviour on top: blinks,
glances, breathing, and a nod on stressed syllables while talking.

Mirrors web/bmo-face.js (FaceRig) - keep the two in step.
"""

from __future__ import annotations

import json
import math
import os
import random

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def load_shapes(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, "shapes.json"), encoding="utf-8") as f:
        shapes = json.load(f)
    # Pre-convert contours to numpy once; blending is then a weighted sum.
    for m in shapes["mouths"].values():
        m["outer_np"] = np.asarray(m["outer"], dtype=np.float64)
        m["tongue_np"] = np.asarray(m["tongue"], dtype=np.float64)
    for e in shapes["eyes"].values():
        e["pts_np"] = np.asarray(e["pts"], dtype=np.float64)
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
        "lid": {**d["lid"], **e.get("lid", {})},
        "brows": pick("brows"),
        "blush": pick("blush"),
        "gaze": pick("gaze"),
        "blink": pick("blink"),
        "motion": pick("motion"),
        "head": {**d["head"], **e.get("head", {})},
        "breathe": pick("breathe"),
        "enter": pick("enter"),
    }


# ------------------------------------------------------------------ behaviours
BLINK_MODES = {
    #            interval range   close   hold  open   double-blink chance
    "normal":    {"every": (2.2, 5.5), "c": 0.06, "h": 0.04, "o": 0.12, "dbl": 0.18},
    "attentive": {"every": (3.0, 6.5), "c": 0.055, "h": 0.03, "o": 0.11, "dbl": 0.10},
    "slow":      {"every": (3.0, 6.0), "c": 0.10, "h": 0.08, "o": 0.22, "dbl": 0.05},
    "sleepy":    {"every": (1.4, 3.2), "c": 0.16, "h": 0.25, "o": 0.45, "dbl": 0.25},
}


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

    def update(self, dt: float, mode: str) -> float:
        self.cfg = BLINK_MODES.get(mode, BLINK_MODES["normal"])
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
        else:
            self.next -= dt
            if self.next <= 0:
                self.trigger(random.random() < self.cfg["dbl"])
        return self.value


class Gaze:
    def __init__(self):
        self.x = Spring(0, 7, 0.72)  # saccades: quick with a tiny overshoot
        self.y = Spring(0, 7, 0.72)
        self.hold = 0.5
        self.mode = "wander"
        self.think_side = 1

    def pick(self, mode: str) -> None:
        r = random.uniform
        x = y = 0.0
        hold = 1.5
        side = lambda: -1 if random.random() < 0.5 else 1  # noqa: E731
        if mode == "wander":
            if random.random() < 0.3:
                x, y, hold = r(14, 24) * side(), r(-12, 10), r(0.5, 1.3)
            else:
                x, y, hold = r(-5, 5), r(-3, 3), r(1.0, 3.2)
        elif mode == "attentive":
            x, y, hold = r(-3, 3), r(-2, 2), r(1.2, 3.5)
        elif mode == "think":
            q = random.random()
            if q < 0.75:
                self.think_side = -self.think_side
            x = 20 * self.think_side + r(-4, 4) if q < 0.85 else r(-4, 4)
            y, hold = r(-20, -13), r(0.9, 2.2)
        elif mode == "talk":
            if random.random() < 0.2:
                x, y, hold = r(9, 15) * side(), r(-6, 4), r(0.4, 0.9)
            else:
                x, y, hold = r(-4, 4), r(-3, 2), r(0.8, 2.2)
        elif mode == "down":
            x, y, hold = r(-9, 9), r(9, 14), r(1.5, 3.5)
        else:  # fixed
            hold = 1.0
        self.x.target, self.y.target, self.hold = x, y, hold

    def update(self, dt: float, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.hold = 0
        self.hold -= dt
        if self.hold <= 0:
            self.pick(mode)
        self.x.step(dt)
        self.y.step(dt)


JAW_VISEMES = {"C", "D", "E"}


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
        self.p = {
            "smile": S(0, 5, 0.85), "jaw": S(1, 9, 0.55), "width": S(1, 5, 0.8),
            "mdx": S(0, 4, 0.85), "mdy": S(0, 4, 0.85), "mtilt": S(0, 4, 0.85),
            "esx": S(1, 4.5, 0.55), "esy": S(1, 4.5, 0.55), "eox": S(0, 4, 0.85), "eoy": S(0, 4, 0.85),
            "lidY": S(NO_LID_Y, 4, 0.9), "lidSlope": S(0, 4, 0.9), "lidLine": S(0, 4, 0.9),
            "blush": S(0, 1.5, 1), "tilt": S(0, 2.5, 0.8), "headDy": S(0, 2.5, 0.8),
            "bob": S(0, 5, 0.38), "squash": S(0, 6, 0.4), "talkMix": S(0, 5, 1),
            "motion": S(0, 1.5, 1), "breathe": S(1, 1, 1),
        }
        self.brows = [
            {"ox": S(0, 5, 0.8), "oy": S(-100, 5, 0.8), "ix": S(0, 5, 0.8), "iy": S(-100, 5, 0.8), "w": S(0, 5, 0.9)}
            for _ in range(2)
        ]
        self.blinker = Blinker()
        self.gaze = Gaze()
        self.speech = dict(SILENT)
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
        for k, s in self.eye_w.items():
            s.target = e["eye"].get(k, 0.0)
        mm = e["mouthMods"]
        p["smile"].target, p["jaw"].target, p["width"].target = mm["smile"], mm["jaw"], mm["width"]
        p["mdx"].target, p["mdy"].target, p["mtilt"].target = mm["dx"], mm["dy"], mm["tilt"]
        p["esx"].target, p["esy"].target = e["eyeScale"]
        p["eox"].target, p["eoy"].target = e["eyeOffset"]
        p["lidY"].target, p["lidSlope"].target, p["lidLine"].target = e["lid"]["y"], e["lid"]["slope"], e["lid"]["line"]
        p["blush"].target = e["blush"]
        p["tilt"].target = math.radians(e["head"]["tilt"])
        p["headDy"].target = e["head"]["dy"]
        p["motion"].target = 1.0 if e["motion"] else 0.0
        p["breathe"].target = e["breathe"]
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

        for k, s in self.mouth_w.items():
            if talking:
                s.target = 1.0 if k == vis else 0.0
                s.freq, s.damping = 11, 0.92
            else:
                s.target = e["mouth"].get(k, 0.0)
                s.freq, s.damping = 5, 0.88
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
        self.gaze.update(dt, "talk" if talking else e["gaze"])
        for s in self.springs:
            s.step(dt)

    # ------------------------------------------------------------ geometry
    def frame(self) -> dict:
        """Current face as plain geometry in art space (1280x720)."""
        S, p, t = self.shapes, self.p, self.t

        hx = 0.0
        hy = p["headDy"].value + p["bob"].value
        tilt = p["tilt"].value
        hy += math.sin(2 * math.pi * t / 4.2) * 2.2 * p["breathe"].value
        tilt += math.sin(2 * math.pi * t / 7.3) * 0.006 * p["breathe"].value
        m = p["motion"].value
        kind = self._motion_kind
        if kind == "bounce":
            hy -= abs(math.sin(math.pi * t * 1.5)) * 9 * m
        elif kind == "hop":
            hy -= abs(math.sin(math.pi * t * 2.3)) * 15 * m
        elif kind == "tremble":
            hx += math.sin(2 * math.pi * t * 13) * 2.2 * m
        elif kind == "droop":
            hy += (1 - math.cos(2 * math.pi * t / 6)) * 5 * m
            tilt += math.sin(2 * math.pi * t / 6) * 0.01 * m
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

        # ---- eyes
        blink_pose = S["eyes"]["closed"]
        ews = [(k, max(0.0, s.value)) for k, s in self.eye_w.items()]
        ews = [(k, w) for k, w in ews if w > 1e-4] or [("open", 1.0)]
        esum = sum(w for _, w in ews)
        base = None
        e_stroke = open_like = 0.0
        for k, w0 in ews:
            w, E = w0 / esum, S["eyes"][k]
            base = E["pts_np"] * w if base is None else base + E["pts_np"] * w
            e_stroke += E["stroke"] * w
            if k in ("open", "wide"):
                open_like += w
        b = self.blink * open_like  # arcs (happy/relax) don't blink
        rel = base + (blink_pose["pts_np"] - base) * b
        sq = p["squash"].value
        sx = p["esx"].value * (1 + 0.035 * sq)
        sy = p["esy"].value * (1 - 0.07 * sq) * (1 + 0.04 * openness)
        lift = 5 * openness * p["talkMix"].value
        lid_y, lid_slope, lid_line = p["lidY"].value, p["lidSlope"].value, p["lidLine"].value
        eyes, brows = [], []
        for side in (0, 1):
            mir = 1 if side == 0 else -1
            cx0, cy0 = S["eyeCenters"][side]
            cx = cx0 + self.gaze.x.value + p["eox"].value * mir
            cy = cy0 + self.gaze.y.value + p["eoy"].value - lift
            pts = head(np.stack([cx + rel[:, 0] * sx * mir, cy + rel[:, 1] * sy], axis=1))
            clip = lid = None
            if lid_y > -70:
                at = lambda xi: lid_y + lid_slope * xi  # noqa: E731
                quad = np.array([[-140, at(-140)], [140, at(140)], [140, 220], [-140, 220]])
                clip = head(np.stack([cx + quad[:, 0] * mir, cy + quad[:, 1]], axis=1))
                if lid_line > 0.5:
                    seg = np.array([[-46, at(-46)], [46, at(46)]])
                    lid = {"pts": head(np.stack([cx + seg[:, 0] * mir, cy + seg[:, 1]], axis=1)), "w": lid_line}
            brow = None
            br = self.brows[side]
            if br["w"].value > 0.4:
                bx = cx0 + self.gaze.x.value * 0.3
                by = cy0 + self.gaze.y.value * 0.25 - 7 * sq - lift * 1.4
                seg = np.array([
                    [bx + br["ox"].value * mir, by + br["oy"].value],
                    [bx + br["ix"].value * mir, by + br["iy"].value],
                ])
                brow = {"pts": head(seg), "w": br["w"].value}
                brows.append(brow)
            eyes.append({
                "pts": pts, "stroke": lerp(e_stroke, blink_pose["stroke"], b),
                "clip": clip, "lidLine": lid, "brow": brow,
            })

        blush = None
        if p["blush"].value > 0.01:
            blush = {"alpha": clamp(p["blush"].value), "centers": head(np.array([[233.0, 393.0], [1047.0, 393.0]]))}

        return {"eyes": eyes, "brows": brows, "mouth": mouth, "blush": blush, "expression": self.expr["name"]}
