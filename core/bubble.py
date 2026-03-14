# core/bubble.py — Thought bubble overlay for transcribed user input
import tkinter as tk
import tkinter.font as tkFont


class ThoughtBubble:
    """Animated comic-style thought bubble with trailing dots and slide animation."""

    # Face background is #bdffcb — canvas must match so it's invisible
    FACE_BG    = '#bdffcb'

    # White bubble with dark green outline — pops against the green face
    FILL       = '#ffffff'
    OUTLINE    = '#2a6b3a'
    TEXT_CLR   = '#1a4a28'
    OUTLINE_W  = 2

    # Typography
    FONT_FAMILY = 'Courier New'
    FONT_SIZE   = 11
    PAD_X       = 18
    PAD_Y       = 12
    CORNER_R    = 16
    MAX_TEXT_W  = 560       # pixel width before wrapping

    # Screen
    SCREEN_W    = 800
    TARGET_Y    = 10        # resting position (px from top)

    # Trailing thought dots (radius, x-offset from bubble center, y-offset below bubble)
    DOTS = [(6, -20, 10), (4, -34, 22), (3, -42, 30)]
    DOT_SPACE   = 38        # vertical space reserved below bubble for dots

    # Animation
    HOLD_MS     = 8000
    ANIM_STEPS  = 8
    ANIM_MS     = 28        # ~35 FPS slide

    def __init__(self, master):
        self._master = master
        self._canvas = None
        self._hide_job = None
        self._anim_jobs = []

    # -- public API ------------------------------------------------------------

    def show(self, text, duration_ms=None):
        """Show a thought bubble with *text*, auto-hide after *duration_ms*."""
        if not text or len(text.strip()) < 2:
            return
        duration_ms = duration_ms or self.HOLD_MS
        self._master.after(0, lambda: self._build_and_show(text.strip(), duration_ms))

    def hide(self):
        """Immediately tear down the bubble."""
        self._cancel_jobs()
        if self._canvas:
            self._canvas.place_forget()
            self._canvas.destroy()
            self._canvas = None

    # -- internals -------------------------------------------------------------

    def _cancel_jobs(self):
        if self._hide_job:
            try:
                self._master.after_cancel(self._hide_job)
            except ValueError:
                pass
            self._hide_job = None
        for j in self._anim_jobs:
            try:
                self._master.after_cancel(j)
            except ValueError:
                pass
        self._anim_jobs = []

    def _build_and_show(self, text, duration_ms):
        self._cancel_jobs()

        # Destroy previous canvas
        if self._canvas:
            self._canvas.destroy()
            self._canvas = None

        # --- Measure text dimensions with a throwaway canvas ------------------
        font = tkFont.Font(family=self.FONT_FAMILY, size=self.FONT_SIZE)
        tmp = tk.Canvas(self._master, width=1, height=1)
        tid = tmp.create_text(0, 0, text=text, font=font,
                              width=self.MAX_TEXT_W, anchor='nw')
        bbox = tmp.bbox(tid)
        tmp.destroy()
        if not bbox:
            return
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        # --- Bubble geometry --------------------------------------------------
        bw = tw + self.PAD_X * 2
        bh = th + self.PAD_Y * 2
        cw = bw + 6                         # slight canvas margin
        ch = bh + self.DOT_SPACE + 6

        cx = (self.SCREEN_W - cw) // 2      # center horizontally

        self._canvas = tk.Canvas(
            self._master, width=cw, height=ch,
            bg=self.FACE_BG, highlightthickness=0, bd=0)

        # Rounded rectangle body
        self._rounded_rect(
            3, 3, bw + 3, bh + 3, self.CORNER_R,
            fill=self.FILL, outline=self.OUTLINE, width=self.OUTLINE_W)

        # Text
        self._canvas.create_text(
            3 + self.PAD_X, 3 + self.PAD_Y,
            text=text, font=font, fill=self.TEXT_CLR,
            width=self.MAX_TEXT_W, anchor='nw')

        # Trailing thought dots
        dot_cx = cw // 2
        dot_y0 = bh + 5
        for r, dx, dy in self.DOTS:
            x, y = dot_cx + dx, dot_y0 + dy
            self._canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill=self.FILL, outline=self.OUTLINE, width=1)

        # --- Slide in from above ----------------------------------------------
        start_y = -ch - 5
        self._canvas.place(x=cx, y=start_y)
        self._slide(start_y, self.TARGET_Y, ease_out=True, on_done=None)

        # Schedule slide-out after hold
        total_in_ms = self.ANIM_STEPS * self.ANIM_MS
        self._hide_job = self._master.after(
            total_in_ms + duration_ms, self._slide_out)

    def _slide_out(self):
        if not self._canvas:
            return
        try:
            cur_y = self._canvas.winfo_y()
        except tk.TclError:
            return
        target = -(self._canvas.winfo_height() + 10)
        self._slide(cur_y, target, ease_out=False, on_done=self.hide)

    def _slide(self, from_y, to_y, ease_out, on_done):
        """Animate Y position over ANIM_STEPS frames with easing."""
        for i in range(1, self.ANIM_STEPS + 1):
            t = i / self.ANIM_STEPS
            if ease_out:
                eased = 1.0 - (1.0 - t) ** 3      # cubic ease-out
            else:
                eased = t ** 3                      # cubic ease-in
            y = int(from_y + (to_y - from_y) * eased)
            final = (i == self.ANIM_STEPS)

            def _move(yy=y, is_final=final):
                if self._canvas:
                    try:
                        self._canvas.place_configure(y=yy)
                    except tk.TclError:
                        pass
                if is_final and on_done:
                    on_done()

            job = self._master.after(i * self.ANIM_MS, _move)
            self._anim_jobs.append(job)

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        """Draw a rounded rectangle using a smooth polygon."""
        pts = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self._canvas.create_polygon(pts, smooth=True, **kw)
