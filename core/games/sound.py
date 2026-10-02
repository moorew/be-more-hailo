"""Game sounds: chiptune tones mixed into one low-latency aplay stream.

The speaker takes one aplay at a time, so a separate aplay per tap would
fail with "Device or resource busy" as soon as two sounds overlap.  Instead
one aplay reads raw PCM for the whole game and a thread feeds it 20 ms
chunks: silence, or whatever sounds are playing, mixed.  The pipe is shrunk
to one page so the backlog (and the tap-to-sound delay) stays ~0.15 s.
"""
import fcntl
import subprocess
import threading

import numpy as np

SR = 22050
CHUNK = SR // 50                      # 20 ms
# Pads in order red, blue, green, yellow: the classic Simon pitches.
PAD_HZ = [415.3, 311.1, 252.0, 209.0]


def _square(hz, seconds, volume=0.22, duty=0.5, decay=None):
    t = np.arange(int(SR * seconds)) / SR
    wave = np.where((t * hz) % 1.0 < duty, 1.0, -1.0) * volume
    env = np.minimum(1.0, t / 0.004) * np.minimum(1.0, (seconds - t) / 0.02)
    if decay:
        env *= np.exp(-t / decay)
    return (wave * env).astype(np.float32)


def _seq(*notes):
    return np.concatenate([_square(hz, s, decay=d) if hz else np.zeros(int(SR * s), np.float32)
                           for hz, s, d in notes])


SOUNDS = {
    **{f"tone:{i}": _square(hz, 0.42, volume=0.2, duty=0.25) for i, hz in enumerate(PAD_HZ)},
    "win": _seq((523.3, 0.09, None), (659.3, 0.09, None), (784.0, 0.09, None), (1046.5, 0.25, 0.15)),
    "lose": _seq((311.1, 0.18, None), (233.1, 0.18, None), (155.6, 0.45, 0.3)),
    "flip": _square(880.0, 0.05, volume=0.12, duty=0.25),
    "match": _seq((784.0, 0.08, None), (1174.7, 0.22, 0.12)),
}


class GameSound:
    def __init__(self, device: str, gain: float = 1.0, popen=subprocess.Popen):
        self.device, self.gain, self._popen = device, gain, popen
        self._proc = None
        self._playing = []            # [array, position]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        try:
            self._proc = self._popen(
                ["aplay", "-D", self.device, "-q", "-t", "raw", "-f", "S16_LE", "-r", str(SR), "-c", "1",
                 "--buffer-time=60000"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                fcntl.fcntl(self._proc.stdin.fileno(), fcntl.F_SETPIPE_SZ, 4096)
            except (OSError, AttributeError, ValueError):
                pass
        except Exception as e:
            print(f"[GAME] No game sound: {e}")
            self._proc = None
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def play(self, name: str):
        snd = SOUNDS.get(name)
        if snd is None or self._proc is None:
            return
        with self._lock:
            if name.startswith("tone:"):          # a new pad note cuts the previous one
                self._playing = [p for p in self._playing if p[2] != "tone"]
            self._playing.append([snd, 0, "tone" if name.startswith("tone:") else name])

    def mix(self) -> np.ndarray:
        """The next 20 ms (float32), advancing every playing sound."""
        out = np.zeros(CHUNK, dtype=np.float32)
        with self._lock:
            keep = []
            for p in self._playing:
                snd, pos, _ = p
                piece = snd[pos:pos + CHUNK]
                out[:len(piece)] += piece
                p[1] = pos + CHUNK
                if p[1] < len(snd):
                    keep.append(p)
            self._playing = keep
        return out

    def _run(self):
        try:
            while not self._stop.is_set():
                pcm = np.clip(self.mix() * self.gain * 32767, -32768, 32767).astype(np.int16)
                self._proc.stdin.write(pcm.tobytes())     # blocks: paces us to real time
        except (BrokenPipeError, OSError, ValueError):
            pass

    def stop(self):
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=1)
            except Exception:
                self._proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=1)
