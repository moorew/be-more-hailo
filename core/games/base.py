"""The Game base class: tap in, frames and sound events out, on a given clock."""
import random

from core.games import art


class Game:
    """A full-screen, tap-only mini game on the 800 x 480 screen.

    Time only comes in through `now` (seconds, any monotonic origin) and
    randomness only from `rng`, so a test can drive a game on a fake clock.

    tap(x, y, now)  -- a touch at screen coordinates
    frame(now)      -- the 800 x 480 RGB frame to show (the same Image object
                       is returned while nothing changes: don't draw on it)
    sounds()        -- sound event names emitted since the last call
    finished        -- True once the player tapped the exit X / Done
    status          -- a short caption ("Round 3", "Your turn!")
    """

    name = "Game"
    key = ""

    def __init__(self, rng=None, now=0.0):
        self.rng = rng if rng is not None else random.Random()
        self.finished = False
        self.status = ""
        self._events = []
        self._frame_key = None
        self._frame_img = None

    # --- public API ----------------------------------------------------------

    def tap(self, x: int, y: int, now: float) -> None:
        self.update(now)
        if self.finished:
            return
        if art.inside(art.EXIT_HIT, x, y):
            self.finished = True
            return
        self._tap(x, y, now)

    def frame(self, now: float):
        self.update(now)
        key = self._state_key(now)
        if key != self._frame_key or self._frame_img is None:
            self._frame_img = self._render(now)
            self._frame_key = key
        return self._frame_img

    def sounds(self) -> list[str]:
        out, self._events = self._events, []
        return out

    def update(self, now: float) -> None:
        """Advance timers up to `now` (called by tap and frame)."""

    def quit(self) -> None:
        self.finished = True

    # --- for subclasses ------------------------------------------------------

    def _emit(self, event):
        self._events.append(event)

    def _tap(self, x, y, now):
        raise NotImplementedError

    def _state_key(self, now):
        """Everything the frame depends on; an unchanged key reuses the last frame."""
        return None

    def _render(self, now):
        raise NotImplementedError
