"""End-of-utterance detection for BMO's recorder.

The old check compared np.linalg.norm(block) against a fixed 500.  A block's
L2 norm grows with sqrt(block size), and the C-Media mic's auto-gain lifts the
room floor to ~470 RMS — so the "volume" never dropped under 500 and every
recording ran to the 15 s cap.  This detector works on per-sample RMS, tracks
the noise floor as it drifts, and times silence in seconds, not callbacks.
"""

from collections import deque

import numpy as np

# Speech must beat the floor by this factor to count (measured: floor ~470,
# speech 1300-1800 RMS in 250 ms windows with AGC on).
SPEECH_RATIO = 2.2
# Absolute minimum for "speech".  With the mic's AGC off the room floor is ~100
# RMS but clatter bursts to ~450; speech close up is 1000-2800.  With AGC on
# (the default: distant speech was too quiet for the wake word) the floor is
# ~470 and SPEECH_RATIO sets the bar instead.
MIN_SPEECH_RMS = 600.0
# How long without speech-level audio ends the utterance.
END_SILENCE_S = 0.9
# Give up if nobody starts talking within this long.
NO_SPEECH_TIMEOUT_S = 4.0


def block_rms(block) -> float:
    """Per-sample RMS of an int16 block, independent of block size."""
    a = np.asarray(block, dtype=np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


FRAME_S = 0.05          # analyse in fixed 50 ms frames whatever the block size
CALIBRATE_S = 0.2       # first frames only seed the noise floor
FLOOR_WINDOW_S = 3.0    # noise floor = quietest frame in this trailing window
MIN_SPEECH_S = 0.15     # this much speech-level audio before we believe it


class EndpointDetector:
    """Feed audio blocks; `done` turns True once the user has stopped talking.

    Silence is measured by *absence of speech-level frames* rather than
    presence of quiet ones: AGC makes the floor pump up just after speech, and
    those noisy-but-not-speech frames must still count towards the pause.
    """

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self.frame_len = max(1, int(sample_rate * FRAME_S))
        self._pending = np.empty(0, dtype=np.float32)
        self._recent = deque(maxlen=max(1, int(round(FLOOR_WINDOW_S / FRAME_S))))
        self.floor = None
        self.speech_s = 0.0
        self.has_spoken = False
        self.elapsed_s = 0.0
        self.since_speech_s = 0.0

    def speech_threshold(self) -> float:
        return max(MIN_SPEECH_RMS, (self.floor or 0.0) * SPEECH_RATIO)

    def feed(self, block) -> float:
        """Process one block; returns its RMS (handy for lip sync)."""
        a = np.asarray(block, dtype=np.float32).ravel()
        self._pending = np.concatenate([self._pending, a])
        while len(self._pending) >= self.frame_len:
            frame, self._pending = self._pending[:self.frame_len], self._pending[self.frame_len:]
            self._frame(float(np.sqrt(np.mean(frame * frame))))
        return block_rms(a)

    def _frame(self, rms: float):
        self.elapsed_s += FRAME_S
        # Trailing minimum: the gaps between words reach the floor even while
        # talking, and a mis-seeded floor corrects itself within the window.
        self._recent.append(rms)
        self.floor = min(self._recent)
        if self.elapsed_s + 1e-9 < CALIBRATE_S:
            return

        if rms >= self.speech_threshold():
            self.speech_s += FRAME_S
            if self.speech_s >= MIN_SPEECH_S:
                self.has_spoken = True
            self.since_speech_s = 0.0
        else:
            self.since_speech_s += FRAME_S

    @property
    def done(self) -> bool:
        if self.has_spoken:
            return self.since_speech_s >= END_SILENCE_S
        return self.elapsed_s >= NO_SPEECH_TIMEOUT_S
