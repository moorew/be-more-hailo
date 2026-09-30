"""The recorder must stop shortly after speech ends, even with a noisy AGC mic."""

import numpy as np
import pytest

from core.endpoint import EndpointDetector

SR = 48000
rng = np.random.default_rng(0)


def noise(seconds, rms=470):
    return (rng.standard_normal(int(SR * seconds)) * rms).astype(np.int16)


def run(audio, block):
    d = EndpointDetector(SR)
    i = 0
    while i < len(audio) and not d.done:
        d.feed(audio[i:i + block])
        i += block
    return d, i / SR


@pytest.mark.parametrize("block", [256, 512, 1024, 4096])
def test_stops_about_a_second_after_speech(block):
    audio = np.concatenate([noise(0.5), noise(1.5, rms=1500), noise(10)])
    d, stopped = run(audio, block)
    assert d.has_spoken
    assert 2.7 <= stopped <= 3.2


@pytest.mark.parametrize("block", [256, 1024])
def test_room_noise_alone_times_out_without_speech(block):
    d, stopped = run(noise(10), block)
    assert not d.has_spoken
    assert stopped < 4.5


def test_short_pause_between_words_does_not_end_utterance():
    audio = np.concatenate([noise(0.5), noise(1.0, 1500), noise(0.5), noise(1.0, 1500), noise(10)])
    d, stopped = run(audio, 512)
    assert stopped > 3.5


def syllables(seconds):
    """Real speech: loud syllables separated by short near-floor gaps."""
    parts = []
    for _ in range(int(seconds / 0.28)):
        parts += [noise(0.2, 1500), noise(0.08)]
    return np.concatenate(parts)


def test_speaking_immediately_still_ends():
    audio = np.concatenate([syllables(1.5), noise(10)])
    d, stopped = run(audio, 512)
    assert d.has_spoken
    assert stopped < 4.0


def test_recovers_from_a_digital_silence_glitch():
    audio = np.concatenate([noise(1.5, 1500), np.zeros(int(SR * 0.3), np.int16), noise(10)])
    d, stopped = run(audio, 512)
    assert stopped < 6.5


def test_quiet_mic_does_not_trigger_on_hiss():
    d, _ = run(noise(5, rms=40), 512)
    assert not d.has_spoken
