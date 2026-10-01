"""One volume control: the speaker's own hardware mixer.

BMO used to scale its audio in software while the desktop slider set the
speaker's hardware level, so the two multiplied and finding a sensible level
meant juggling both.  When the playback card has a volume control (the Jieli
USB speaker has "PCM"), BMO's slider drives that mixer instead, so both
sliders move the same thing and every sound (speech, effects, music, the
morning briefing) follows it.  Speakers without a mixer fall back to the old
software gain.

Levels use amixer's mapped scale (-M), which tracks loudness rather than raw
steps, so the slider feels even across its range.
"""
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_PREFERRED = ("PCM", "Master", "Speaker", "Headphone", "Playback")
_PCT_RE = re.compile(r"\[(\d+)%\]")


def _card_of(alsa_device: str):
    """'plughw:UACDemoV10,0' -> 'UACDemoV10'; 'hw:3,0' -> '3'; None for 'default'/pipewire."""
    m = re.match(r"^(?:plug)?hw:(?:CARD=)?([^,]+)", alsa_device or "")
    return m.group(1) if m else None


class HardwareVolume:
    def __init__(self, card: str, control: str, run=subprocess.run):
        self.card, self.control, self._run = card, control, run

    @classmethod
    def for_device(cls, alsa_device: str, run=subprocess.run):
        """The mixer behind `alsa_device`, or None if it has no playback volume."""
        card = _card_of(alsa_device)
        if card is None:
            return None
        try:
            out = run(["amixer", "-c", card, "scontrols"], capture_output=True, text=True, timeout=3).stdout
        except Exception as e:
            logger.warning(f"amixer unavailable ({e}); using software volume")
            return None
        controls = re.findall(r"Simple mixer control '([^']+)',0", out)
        for name in _PREFERRED + tuple(controls):
            if name not in controls:
                continue
            try:
                caps = run(["amixer", "-c", card, "sget", name], capture_output=True, text=True, timeout=3).stdout
            except Exception:
                continue
            if "pvolume" in caps:
                return cls(card, name, run)
        return None

    def get(self):
        """Current level 0..1 (0 when switched off), or None if amixer fails."""
        try:
            out = self._run(["amixer", "-c", self.card, "-M", "sget", self.control],
                            capture_output=True, text=True, timeout=3).stdout
        except Exception as e:
            logger.warning(f"amixer get failed: {e}")
            return None
        pcts = [int(p) for p in _PCT_RE.findall(out)]
        if not pcts:
            return None
        if "[off]" in out and "[on]" not in out:
            return 0.0
        return max(pcts) / 100.0

    def set(self, level: float) -> bool:
        """Set 0..1; 0 also switches the output off so it's truly silent."""
        level = max(0.0, min(1.0, float(level)))
        pct = int(round(level * 100))
        switch = "mute" if pct == 0 else "unmute"
        try:
            self._run(["amixer", "-c", self.card, "-M", "-q", "sset", self.control, f"{pct}%", switch],
                      capture_output=True, text=True, timeout=3, check=True)
            return True
        except Exception as e:
            logger.warning(f"amixer set failed: {e}")
            return False


def scaled_wav(src: str, gain: float) -> str:
    """Path to play `src` at `gain`: `src` itself at full gain, else a scaled
    temp copy (in /dev/shm when available) that the caller deletes after
    playback.  Only used when there is no hardware mixer."""
    if gain >= 0.999:
        return src
    import os
    import tempfile
    import wave

    import numpy as np
    with wave.open(src) as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    if params.sampwidth != 2:
        return src  # only 16-bit PCM is scaled; anything else plays as is
    pcm = (np.frombuffer(frames, dtype=np.int16).astype(np.float32) * max(0.0, gain))
    tmpdir = "/dev/shm" if os.path.isdir("/dev/shm") else None
    fd, out = tempfile.mkstemp(prefix="bmo-vol-", suffix=".wav", dir=tmpdir)
    os.close(fd)
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(np.clip(pcm, -32768, 32767).astype(np.int16).tobytes())
    return out
