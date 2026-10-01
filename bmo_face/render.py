"""Draw FaceRig frames with Pillow.

Only the small regions around the eyes, mouth, marks and critter are redrawn
each frame, at `supersample`x resolution and then Lanczos-filtered down, which
gives smooth anti-aliased edges without paying for a full-screen supersample
on the Pi. 4x + Lanczos matches the PNG faces (generate_faces.py renders the
SVGs large and downsizes with Lanczos); 2x + box filter left visible
stair-steps. Very large tiles (heart/star eyes) step down to 3x to stay
within `tile_budget` pixels.
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

    def __init__(self, shapes: dict, size: tuple[int, int] = (800, 480), fit: str = "stretch",
                 supersample: int = 4, tile_budget: int = 300_000):
        self.W, self.H = size
        self.ss = max(1, int(supersample))
        self.tile_budget = tile_budget
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
        self._white = Image.new("RGB", size, (255, 255, 255))

    # ------------------------------------------------------------- helpers
    def _px(self, pts) -> np.ndarray:
        pts = np.asarray(pts, dtype=np.float64)
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
    def _simplify(pts: np.ndarray, step: float, closed: bool) -> np.ndarray:
        """Drop points closer than `step` apart (keeping real corners).

        The shapes carry up to 256 points so pixel hearts keep sharp steps, but
        Pillow pays for every vertex (round joins especially), so thin smooth
        runs down to roughly one point per `step` pixels before drawing.
        """
        n = len(pts)
        if n < 8:
            return pts
        p = np.vstack([pts, pts[:1]]) if closed else pts
        d = np.diff(p, axis=0)
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(d[:, 0], d[:, 1]))])
        keep = np.searchsorted(cum, np.arange(0.0, cum[-1], step))
        ang = np.arctan2(d[:, 1], d[:, 0])
        turn = np.abs((np.diff(ang) + np.pi) % (2 * np.pi) - np.pi)
        corners = np.nonzero(turn > 0.35)[0] + 1
        idx = np.unique(np.concatenate([[0], keep, corners, [len(p) - 1]]))
        if closed:
            idx = idx[idx < n]
        return pts[idx] if len(idx) >= (3 if closed else 2) else pts  # collapsed shapes stay as-is

    @staticmethod
    def _stroke(d: ImageDraw.ImageDraw, pts: list, width: float, color, closed: bool) -> None:
        """Polyline with round joins (and round caps when open)."""
        if width < 0.5 or len(pts) < 2:
            return
        # Closed: wrap one segment past the start so that vertex gets a round
        # joint too (Pillow only joins inside a polyline); otherwise thick
        # rings showed a hairline seam where the outline began.
        seq = pts + pts[:2] if closed else pts
        d.line(seq, fill=color, width=max(1, int(round(width))), joint="curve")
        if not closed:
            r = width / 2
            for x, y in (pts[0], pts[-1]):
                d.ellipse([x - r, y - r, x + r, y + r], fill=color)

    def _outline(self, d, pts_px: np.ndarray, filled: bool, width: float, color, to, ss) -> None:
        """Stroke a contour. Line-only shapes repeat their top edge backwards as
        the bottom edge, so stroke just the top edge once, with round caps."""
        step = self._stroke_step(width, ss)
        if filled:
            self._stroke(d, to(self._simplify(pts_px, step, True)), width, color, closed=True)
        else:
            half = pts_px[: len(pts_px) // 2 + 1]
            self._stroke(d, to(self._simplify(half, step, False)), width, color, closed=False)

    @staticmethod
    def _stroke_step(width: float, ss: int) -> float:
        """Point spacing (output px) for stroking a smooth curve: wide strokes
        hide the facets, and every vertex costs a round joint."""
        return max(2.0, 0.3 * width / ss)

    def _paint(self, target: Image.Image, color, alpha: float, draw) -> None:
        """Draw opaque straight onto target, or translucent through a mask."""
        if alpha >= 0.995:
            draw(ImageDraw.Draw(target), color)
        elif alpha > 0.01:
            mask = Image.new("L", target.size, 0)
            draw(ImageDraw.Draw(mask), int(255 * alpha))
            target.paste(color, (0, 0), mask)

    def _tile(self, img: Image.Image, pts_px: np.ndarray, margin: float, draw_fn) -> None:
        x0 = max(0, int(math.floor(pts_px[:, 0].min() - margin)))
        y0 = max(0, int(math.floor(pts_px[:, 1].min() - margin)))
        x1 = min(self.W, int(math.ceil(pts_px[:, 0].max() + margin)))
        y1 = min(self.H, int(math.ceil(pts_px[:, 1].max() + margin)))
        if x1 <= x0 or y1 <= y0:
            return
        ss = self.ss
        while ss > 2 and (x1 - x0) * (y1 - y0) * ss * ss > self.tile_budget:
            ss -= 1
        tile = img.crop((x0, y0, x1, y1))
        if ss > 1:
            tile = tile.resize(((x1 - x0) * ss, (y1 - y0) * ss), Image.NEAREST)
        off = np.array([x0, y0], dtype=np.float64)

        def to(pts: np.ndarray) -> list:
            return [tuple(p) for p in ((pts - off) * ss).tolist()]

        draw_fn(tile, to, ss)
        if ss > 1:
            tile = tile.resize((x1 - x0, y1 - y0), Image.LANCZOS)
        img.paste(tile, (x0, y0))

    # -------------------------------------------------------------- render
    def render(self, f: dict) -> Image.Image:
        img = self.base.copy()
        c, k, simp = self.c, self.k, self._simplify

        if f.get("blush"):
            a = f["blush"]["alpha"]
            mask = self._blush if a >= 0.999 else self._blush.point(lambda v: int(v * a))
            col = _rgb(f["blush"].get("color") or "#548B51")
            for x, y in self._px(f["blush"]["centers"]):
                img.paste(col, (int(round(x - mask.width / 2)), int(round(y - mask.height / 2))), mask)

        for e in f["eyes"]:
            eye = self._px(e["pts"])
            parts = [eye]
            lids = [(self._px(lid["pts"]), lid["w"]) for lid in e.get("lidLines", [])]
            brow = self._px(e["brow"]["pts"]) if e.get("brow") else None
            details = [(simp(self._px(d["pts"]), 2.0, True), _rgb(d["fill"]), d["alpha"]) for d in e.get("details", [])]
            parts += [p for p, _ in lids] + ([brow] if brow is not None else []) + [p for p, _, _ in details]
            widest = max([e["stroke"]] + [w for _, w in lids] + ([e["brow"]["w"]] if brow is not None else []))
            clip = self._px(e["clip"]) if e.get("clip") is not None else None
            filled = self._has_area(eye)
            fill, scol = _rgb(e.get("fill", "#000000")), _rgb(e.get("strokeColor", "#000000"))

            def draw_eye(tile, to, ss, e=e, eye=eye, lids=lids, brow=brow, clip=clip, filled=filled,
                         details=details, fill=fill, scol=scol):
                d = ImageDraw.Draw(tile)
                layer = tile.copy() if clip is not None else tile
                dl = ImageDraw.Draw(layer)
                if filled:
                    dl.polygon(to(simp(eye, 2.0, True)), fill=fill)
                if e["stroke"] > 0.3:
                    self._outline(dl, eye, filled, e["stroke"] * k * ss, scol, to, ss)
                for dp, dcol, da in details:
                    q = to(dp)
                    self._paint(layer, dcol, da, lambda dd, col, q=q: dd.polygon(q, fill=col))
                if clip is not None:
                    mask = Image.new("L", tile.size, 0)
                    ImageDraw.Draw(mask).polygon(to(clip), fill=255)
                    tile.paste(layer, (0, 0), mask)
                for lp, lw in lids:
                    self._stroke(d, to(lp), lw * k * ss, c["line"], closed=False)
                if brow is not None:
                    self._stroke(d, to(brow), e["brow"]["w"] * k * ss, c["line"], closed=False)

            self._tile(img, np.vstack(parts), widest * k / 2 + 3, draw_eye)

        m = f["mouth"]
        outer = self._px(m["outer"])
        tongue = simp(self._px(m["tongue"]), 2.0, True)
        teeth = [(self._px(line), sign) for line, sign in ((m["teethTop"], -1), (m["teethBot"], 1)) if line is not None]
        open_mouth = self._has_area(outer)

        def draw_mouth(tile, to, ss):
            d = ImageDraw.Draw(tile)
            if not open_mouth:  # a line-only mouth: nothing inside to fill
                self._outline(d, outer, False, m["stroke"] * k * ss, c["line"], to, ss)
                return
            o = to(simp(outer, 2.0, True))
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

        # Marks: one tile per mark (all of its pieces together).
        groups: dict = {}
        for mk in f.get("marks", []):
            groups.setdefault(mk.get("key"), []).append(mk)
        for items in groups.values():
            prepared = [(simp(self._px(mk["pts"]), 2.0 if mk["kind"] == "fill" else max(2.0, 0.3 * mk["width"] * k),
                              mk["closed"]), mk) for mk in items]

            def draw_marks(tile, to, ss, prepared=prepared):
                for pts, mk in prepared:
                    q, col = to(pts), _rgb(mk["color"])
                    if mk["kind"] == "fill":
                        self._paint(tile, col, mk["alpha"], lambda dd, cc, q=q: dd.polygon(q, fill=cc))
                    else:
                        w = mk["width"] * k * ss
                        self._paint(tile, col, mk["alpha"],
                                    lambda dd, cc, q=q, w=w, mk=mk: self._stroke(dd, q, w, cc, closed=mk["closed"]))

            widest = max(mk["width"] for _, mk in prepared)
            self._tile(img, np.vstack([p for p, _ in prepared]), widest * k / 2 + 3, draw_marks)

        cr = f.get("critter")
        if cr:
            parts = [(simp(self._px(pt["pts"]), 2.0 if pt["fill"] else max(2.0, 0.3 * pt["width"] * k),
                           pt["closed"]), pt) for pt in cr["parts"]]
            widest = max(pt["width"] for pt in cr["parts"])

            def draw_critter(tile, to, ss):
                for pp, pt in parts:
                    q = to(pp)
                    if pt["fill"] and pt["closed"]:
                        self._paint(tile, _rgb(pt["fill"]), pt["alpha"], lambda dd, cc, q=q: dd.polygon(q, fill=cc))
                    if pt["stroke"] and pt["width"] > 0.3:
                        w = pt["width"] * k * ss
                        self._paint(tile, _rgb(pt["stroke"]), pt["alpha"],
                                    lambda dd, cc, q=q, w=w, pt=pt: self._stroke(dd, q, w, cc, closed=pt["closed"]))

            self._tile(img, np.vstack([p for p, _ in parts]), widest * k / 2 + 3, draw_critter)

        if f.get("flash", 0) > 0.01:
            img = Image.blend(img, self._white, min(1.0, f["flash"]))
        return img