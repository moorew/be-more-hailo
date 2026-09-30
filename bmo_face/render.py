"""Draw FaceRig frames with Pillow.

Only the small regions around the eyes and mouth are redrawn each frame, at
`supersample`x resolution and then box-filtered down, which gives smooth
anti-aliased edges without paying for a full-screen supersample on the Pi.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class PillowRenderer:
    """fit: 'stretch' (matches generate_faces.py on the 800x480 panel), 'cover' or 'contain'."""

    def __init__(self, shapes: dict, size: tuple[int, int] = (800, 480), fit: str = "stretch", supersample: int = 2):
        self.W, self.H = size
        self.ss = max(1, int(supersample))
        sx, sy = self.W / 1280, self.H / 720
        if fit == "cover":
            sx = sy = max(sx, sy)
        elif fit == "contain":
            sx = sy = min(sx, sy)
        self.sx, self.sy = sx, sy
        self.ox, self.oy = (self.W - 1280 * sx) / 2, (self.H - 720 * sy) / 2
        self.k = math.sqrt(sx * sy)  # stroke-width scale
        self.c = {k: _rgb(v) for k, v in shapes["colors"].items()}
        self.base = Image.new("RGB", size, self.c["bg"])
        self._blush = self._make_blush()

    # ------------------------------------------------------------- helpers
    def _px(self, pts: np.ndarray) -> np.ndarray:
        return np.column_stack([pts[:, 0] * self.sx + self.ox, pts[:, 1] * self.sy + self.oy])

    def _make_blush(self) -> Image.Image:
        rx, ry, blur = 63 * self.sx, 42 * self.sy, 10 * self.k
        pad = int(math.ceil(blur * 3))
        w, h = int(2 * rx + 2 * pad), int(2 * ry + 2 * pad)
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).ellipse([pad, pad, pad + 2 * rx, pad + 2 * ry], fill=int(255 * 0.69))
        return m.filter(ImageFilter.GaussianBlur(blur))

    @staticmethod
    def _has_area(pts_px: np.ndarray) -> bool:
        """False for line-only shapes (smile, blink, ∩ eyes) whose outline has no inside.

        Their top and bottom edges coincide, and Pillow's scanline fill can pair
        the wrong edges on such polygons and paint stray chords, so skip filling.
        """
        x, y = pts_px[:, 0], pts_px[:, 1]
        area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
        perimeter = float(np.hypot(np.diff(x, append=x[0]), np.diff(y, append=y[0])).sum())
        return perimeter > 0 and area / (perimeter / 2) > 0.35  # mean thickness in px

    @staticmethod
    def _stroke(d: ImageDraw.ImageDraw, pts: list, width: float, color, closed: bool) -> None:
        """Polyline with round joins and round caps."""
        if width < 0.5 or len(pts) < 2:
            return
        seq = pts + [pts[0]] if closed else pts
        d.line(seq, fill=color, width=max(1, int(round(width))), joint="curve")
        r = width / 2
        ends = (pts[0], pts[len(pts) // 2]) if closed else (pts[0], pts[-1])
        for x, y in ends:  # anchors are where line-only shapes turn back on themselves
            d.ellipse([x - r, y - r, x + r, y + r], fill=color)

    def _tile(self, img: Image.Image, pts_px: np.ndarray, margin: float, draw_fn) -> None:
        x0 = max(0, int(math.floor(pts_px[:, 0].min() - margin)))
        y0 = max(0, int(math.floor(pts_px[:, 1].min() - margin)))
        x1 = min(self.W, int(math.ceil(pts_px[:, 0].max() + margin)))
        y1 = min(self.H, int(math.ceil(pts_px[:, 1].max() + margin)))
        if x1 <= x0 or y1 <= y0:
            return
        ss = self.ss
        tile = img.crop((x0, y0, x1, y1))
        if ss > 1:
            tile = tile.resize(((x1 - x0) * ss, (y1 - y0) * ss), Image.NEAREST)
        off = np.array([x0, y0], dtype=np.float64)

        def to(pts: np.ndarray) -> list:
            return [tuple(p) for p in ((pts - off) * ss).tolist()]

        draw_fn(tile, to)
        if ss > 1:
            tile = tile.reduce(ss)
        img.paste(tile, (x0, y0))

    # -------------------------------------------------------------- render
    def render(self, f: dict) -> Image.Image:
        img = self.base.copy()
        c, k, ss = self.c, self.k, self.ss

        if f.get("blush"):
            a = f["blush"]["alpha"]
            mask = self._blush if a >= 0.999 else self._blush.point(lambda v: int(v * a))
            for x, y in self._px(f["blush"]["centers"]):
                img.paste(c["blush"], (int(round(x - mask.width / 2)), int(round(y - mask.height / 2))), mask)

        for e in f["eyes"]:
            eye = self._px(e["pts"])
            parts = [eye]
            lid = self._px(e["lidLine"]["pts"]) if e.get("lidLine") else None
            brow = self._px(e["brow"]["pts"]) if e.get("brow") else None
            if lid is not None:
                parts.append(lid)
            if brow is not None:
                parts.append(brow)
            widest = max([e["stroke"]] + [x["w"] for x in (e.get("lidLine"), e.get("brow")) if x])
            clip = self._px(e["clip"]) if e.get("clip") is not None else None
            filled = self._has_area(eye)

            def draw_eye(tile, to, e=e, eye=eye, lid=lid, brow=brow, clip=clip, filled=filled):
                d = ImageDraw.Draw(tile)
                layer = tile.copy() if clip is not None else tile
                dl = ImageDraw.Draw(layer)
                pts = to(eye)
                if filled:
                    dl.polygon(pts, fill=c["line"])
                if e["stroke"] > 0.3:
                    self._stroke(dl, pts, e["stroke"] * k * ss, c["line"], closed=True)
                if clip is not None:
                    mask = Image.new("L", tile.size, 0)
                    ImageDraw.Draw(mask).polygon(to(clip), fill=255)
                    tile.paste(layer, (0, 0), mask)
                if lid is not None:
                    self._stroke(d, to(lid), e["lidLine"]["w"] * k * ss, c["line"], closed=False)
                if brow is not None:
                    self._stroke(d, to(brow), e["brow"]["w"] * k * ss, c["line"], closed=False)

            self._tile(img, np.vstack(parts), widest * k / 2 + 3, draw_eye)

        m = f["mouth"]
        outer = self._px(m["outer"])
        tongue = self._px(m["tongue"])
        teeth = [(self._px(line), sign) for line, sign in ((m["teethTop"], -1), (m["teethBot"], 1)) if line is not None]
        open_mouth = self._has_area(outer)

        def draw_mouth(tile, to):
            d = ImageDraw.Draw(tile)
            o = to(outer)
            if not open_mouth:  # a line-only mouth: nothing inside to fill
                self._stroke(d, o, m["stroke"] * k * ss, c["line"], closed=True)
                return
            d.polygon(o, fill=c["cavity"])
            mask = Image.new("L", tile.size, 0)
            ImageDraw.Draw(mask).polygon(o, fill=255)
            layer = tile.copy()
            dl = ImageDraw.Draw(layer)
            dl.polygon(to(tongue), fill=c["tongue"])
            for line, sign in teeth:
                pts = to(line)
                (ax, ay), (zx, zy) = pts[0], pts[-1]
                far = 400 * ss * sign
                dl.polygon(pts + [(zx, zy + far), (ax, ay + far)], fill=c["teeth"])
                self._stroke(dl, pts, 9 * k * ss, c["line"], closed=False)
            tile.paste(layer, (0, 0), mask)
            self._stroke(d, o, m["stroke"] * k * ss, c["line"], closed=True)

        self._tile(img, outer, m["stroke"] * k / 2 + 3, draw_mouth)
        return img
