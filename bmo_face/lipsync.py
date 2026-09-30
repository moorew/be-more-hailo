"""Audio -> Rhubarb mouth shapes, in real time.

The current build maps loudness to a frame. This reads the spectrum as well:
  hiss (s, sh, t)            -> B  clenched teeth
  open vowels (high F1)      -> C / D  jaw open
  rounded vowels (low F2)    -> E / F  lips rounded / puckered
  short gaps between sounds  -> A  lips closed
  silence                    -> X  rest
Feature ratios normalise themselves as speech goes by, so it adapts to BMO's
Piper voice and to other voices alike.

Mirrors LipSyncAnalyser / VisemeSelector in web/bmo-face.js.
"""

from __future__ import annotations

import math
import wave

import numpy as np

# Frequency bands (Hz) used to read the mouth shape off the spectrum.
BANDS = {
    "low": (150, 600),     # F0 + first formant of closed vowels (ee, oo)
    "mid": (600, 1500),    # first formant of open vowels (ah)
    "f2lo": (700, 1700),   # second formant of rounded vowels (oo, oh)
    "f2hi": (1800, 3800),  # second formant of spread vowels (ee, eh)
    "sib": (4000, 10000),  # hiss: s, sh, f, t
    "all": (150, 10000),
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


class LipSyncAnalyser:
    """Turns audio into loud / open / round / sib features (all 0..1)."""

    def __init__(self, sample_rate: int = 22050):
        self.sr = sample_rate
        self.n = 2048 if sample_rate > 32000 else 1024
        self.hop = round(0.023 * sample_rate)
        self.win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(self.n) / (self.n - 1))
        self.bins = {
            k: (max(1, round(lo * self.n / sample_rate)), min(self.n // 2 - 1, round(hi * self.n / sample_rate)))
            for k, (lo, hi) in BANDS.items()
        }
        self.peak = 0.03
        # Running [mean, mean-abs-deviation] of the formant features in dB,
        # seeded from BMO's Piper voice so the first syllable is already sane.
        self.stats = {"open": [-4.0, 6.8], "spread": [-5.0, 10.0]}
        self._ring = np.zeros(self.n, dtype=np.float64)

    def _norm(self, key: str, x: float, learn: bool, dt: float) -> float:
        st = self.stats[key]
        if learn:
            a = 1 - math.exp(-dt / 2.5)
            st[0] += (x - st[0]) * a
            st[1] += (abs(x - st[0]) - st[1]) * a
            st[1] = max(st[1], 2.0)
        return _clamp(0.5 + (x - st[0]) / (3 * st[1]))

    def process(self, window: np.ndarray, rms: float, dt: float) -> dict:
        """window: the latest self.n samples (float, -1..1); rms of the newest hop."""
        spec = np.fft.rfft(window * self.win)
        power = spec.real ** 2 + spec.imag ** 2

        def band(k):
            a, b = self.bins[k]
            return float(power[a:b + 1].sum())

        eps = 1e-12
        low, mid, f2lo, f2hi = band("low"), band("mid"), band("f2lo"), band("f2hi")
        sib, total = band("sib"), band("all") + eps

        self.peak = max(rms, self.peak * math.exp(-dt / 1.8), 0.02)
        voiced = rms > max(0.006, self.peak * 0.09)
        loud = _clamp(rms / self.peak)
        sib_ratio = sib / total
        open_db = 10 * math.log10((mid + eps) / (low + eps))       # high F1 -> jaw open
        spread_db = 10 * math.log10((f2hi + eps) / (f2lo + eps))   # low F2 -> lips rounded
        learn = voiced and sib_ratio < 0.3
        open_n = self._norm("open", open_db, learn, dt)
        spread_n = self._norm("spread", spread_db, learn, dt)
        return {
            "rms": rms,
            "voiced": voiced,
            "loud": loud,
            "open": _clamp(math.sqrt(loud) * (0.35 + 0.8 * open_n)),
            "round": _clamp(1 - spread_n),
            "sib": _clamp((sib_ratio - 0.12) / 0.3),
        }

    def feed(self, chunk: np.ndarray) -> dict:
        """Streaming: push the next chunk of samples (int16 or float) and analyse.

        Designed for the ~512-sample chunks agent_hailo.py already reads from Piper.
        """
        x = chunk.astype(np.float64)
        if chunk.dtype == np.int16:
            x /= 32768.0
        n = len(x)
        if n >= self.n:
            self._ring[:] = x[-self.n:]
        else:
            self._ring = np.roll(self._ring, -n)
            self._ring[-n:] = x
        rms = float(np.sqrt(np.mean(x * x))) if n else 0.0
        return self.process(self._ring, rms, n / self.sr if n else 0.0)


class VisemeSelector:
    """Picks a Rhubarb mouth shape with a minimum hold (like animating on 2s)."""

    MIN_HOLD = 0.075

    def __init__(self):
        self.viseme = "X"
        self.hold = 0.0
        self.since_voice = 9.0
        self.loud_slow = 0.0
        self.cool = 0.0

    @staticmethod
    def classify(f: dict) -> str:
        if f["sib"] > 0.55 and f["open"] < 0.75:
            return "B"
        if f["round"] > 0.66:
            return "E" if f["open"] > 0.55 else "F"
        if f["open"] > 0.72:
            return "D"
        if f["open"] > 0.4:
            return "C"
        return "B"

    def update(self, f: dict, dt: float) -> dict:
        if not f["voiced"]:
            self.since_voice += dt
            want = "A" if self.since_voice < 0.16 else "X"
        else:
            self.since_voice = 0.0
            want = self.classify(f)
        self.hold -= dt
        if want != self.viseme and self.hold <= 0:
            self.viseme = want
            self.hold = self.MIN_HOLD
        # Onsets (stressed syllables) drive head bob.
        self.cool -= dt
        onset = f["voiced"] and f["loud"] - self.loud_slow > 0.3 and self.cool <= 0
        if onset:
            self.cool = 0.2
        self.loud_slow += (f["loud"] - self.loud_slow) * (1 - math.exp(-dt / 0.12))
        return {"viseme": self.viseme, "intensity": f["loud"], "active": self.since_voice < 0.45, "onset": onset}


class LipSync:
    """Analyser + selector for one stream. `push(chunk)` -> speech dict."""

    def __init__(self, sample_rate: int = 22050):
        self.analyser = LipSyncAnalyser(sample_rate)
        self.selector = VisemeSelector()
        self.sr = sample_rate

    def reset(self) -> None:
        self.selector = VisemeSelector()

    def push(self, chunk: np.ndarray) -> dict:
        f = self.analyser.feed(chunk)
        return self.selector.update(f, len(chunk) / self.sr)


def analyse_wav(path: str, chunk: int = 512) -> tuple[list[tuple[float, float, dict]], float]:
    """Pre-analyse a WAV file for playback-synced lip-sync.

    Returns ([(play_offset_s, mouth_open, speech), ...], duration_s), the same
    schedule format agent_hailo.py uses for Piper audio. mouth_open keeps the
    legacy 0..60 loudness value so the PNG fallback still works.
    """
    with wave.open(path, "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: only 16-bit WAV is supported")
    pcm = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1).astype(np.int16)
    ls = LipSync(sr)
    sched = []
    for i in range(0, len(pcm), chunk):
        c = pcm[i:i + chunk]
        speech = ls.push(c)
        vol = float(np.sqrt(np.mean(c.astype(np.float32) ** 2))) if len(c) else 0.0
        sched.append((i / sr, min(60.0, vol / 25), speech))
    return sched, len(pcm) / sr
