"""Generate BMO's morning-briefing "ready" chime.

Same pure-Python square/triangle approach as scripts/generate_chiptunes.py:
a quick rising C-major arpeggio that lands on a bright held note with a
twinkle on top, about 1.4 s long.

    python scripts/make_ready_chime.py            # -> sounds/briefing_sounds/ready.wav
    python scripts/make_ready_chime.py out.wav

Output: 44100 Hz, 16-bit mono, like the other generated sounds.
"""
import math
import os
import struct
import sys
import wave

SAMPLE_RATE = 44100
LENGTH_S = 1.4
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO, "sounds", "briefing_sounds", "ready.wav")

# (note, start s, length s, wave, volume, decay time constant s)
EVENTS = [
    ("C5", 0.00, 0.13, "square", 0.20, 0.10),
    ("E5", 0.10, 0.13, "square", 0.20, 0.10),
    ("G5", 0.20, 0.13, "square", 0.20, 0.10),
    ("C6", 0.30, 1.05, "square", 0.22, 0.38),   # the held note
    ("E6", 0.44, 0.90, "triangle", 0.16, 0.30),  # twinkle on top
    ("G6", 0.58, 0.75, "triangle", 0.10, 0.25),
    ("C4", 0.30, 1.05, "triangle", 0.20, 0.45),  # bass
]


def note_freq(name: str) -> float:
    notes = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
             "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    n, octave = name[:-1], int(name[-1])
    semitone = notes[n] + (octave - 4) * 12
    return 440.0 * 2.0 ** ((semitone - 9) / 12.0)


def square(freq: float, t: float, duty: float = 0.25) -> float:
    return 1.0 if (t * freq) % 1.0 < duty else -1.0


def triangle(freq: float, t: float) -> float:
    return 4.0 * abs((t * freq) % 1.0 - 0.5) - 1.0


WAVES = {"square": square, "triangle": triangle}


def render() -> list:
    out = [0.0] * int(LENGTH_S * SAMPLE_RATE)
    for name, start, length, kind, volume, tau in EVENTS:
        freq, fn = note_freq(name), WAVES[kind]
        first = int(start * SAMPLE_RATE)
        for i in range(int(length * SAMPLE_RATE)):
            if first + i >= len(out):
                break
            t = i / SAMPLE_RATE
            vib = 1.0 + 0.004 * math.sin(2 * math.pi * 6 * t) if t > 0.15 else 1.0  # a little shimmer
            env = min(1.0, t / 0.005) * math.exp(-t / tau)
            env *= min(1.0, (length - t) / 0.03)  # 30 ms release, no clicks
            out[first + i] += fn(freq * vib, t) * volume * env
    return out


def save(path: str, samples: list) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    pcm = render()
    save(target, pcm)
    print(f"Saved {target} ({len(pcm) / SAMPLE_RATE:.1f} s, peak {max(abs(s) for s in pcm):.2f})")
