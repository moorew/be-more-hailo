"""Notice someone walking up to BMO, from cheap camera frames.

No AI chip and no face recognition: a few tiny greyscale frames a second
(the camera's ISP does the scaling) compared against a slowly-adapting
background.  Enough changed pixels for a couple of frames in a row means
"someone's there".  An *arrival* is motion after the room has been still for
a while, which is what BMO reacts to (waking from the screensaver, offering
the morning briefing); constant motion doesn't keep re-triggering it.
"""
import numpy as np

PIXEL_DELTA = 18            # grey levels a pixel must change by to count
MOTION_FRACTION = 0.03      # share of changed pixels that counts as motion
CONFIRM_FRAMES = 2          # consecutive motion frames before we believe it
AWAY_S = 10 * 60            # stillness that turns the next motion into an arrival
BACKGROUND_RATE = 0.05      # how fast the background adapts (lights, sun moving)


class MotionDetector:
    def __init__(self, pixel_delta=PIXEL_DELTA, fraction=MOTION_FRACTION, confirm=CONFIRM_FRAMES):
        self.pixel_delta, self.fraction, self.confirm = pixel_delta, fraction, confirm
        self._bg = None
        self._streak = 0
        self.score = 0.0

    def feed(self, frame) -> bool:
        """frame: 2-D uint8 greyscale.  True once motion is confirmed."""
        f = np.asarray(frame, dtype=np.float32)
        if self._bg is None or self._bg.shape != f.shape:
            self._bg = f
            return False
        # A sudden global change (lights switched on, camera exposure jump)
        # moves every pixel together: compensate with the median shift.
        diff = f - self._bg
        diff -= np.median(diff)
        changed = np.abs(diff) > self.pixel_delta
        self.score = float(changed.mean())
        self._bg += BACKGROUND_RATE * (f - self._bg)
        self._streak = self._streak + 1 if self.score >= self.fraction else 0
        return self._streak >= self.confirm


class Presence:
    """Turns motion into "arrived" events (feed it frames with timestamps)."""

    def __init__(self, away_s=AWAY_S, detector=None):
        self.away_s = away_s
        self.detector = detector or MotionDetector()
        self.last_motion = None

    def feed(self, frame, now: float) -> bool:
        """True when this frame is an arrival (motion after `away_s` of stillness,
        or the first motion seen)."""
        if not self.detector.feed(frame):
            return False
        arrived = self.last_motion is None or now - self.last_motion >= self.away_s
        self.last_motion = now
        return arrived

    def seen_within(self, seconds: float, now: float) -> bool:
        return self.last_motion is not None and now - self.last_motion <= seconds
