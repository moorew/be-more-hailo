"""One volume control: BMO's slider drives the speaker's hardware mixer (the
same control as the desktop slider) instead of scaling audio on top of it."""
import struct
import wave

from core.volume import HardwareVolume, _card_of, scaled_wav

SCONTROLS = "Simple mixer control 'PCM',0\n"
SGET = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch pswitch-joined
  Front Left: Playback 103 [70%] [-9.00dB] [on]
  Front Right: Playback 103 [70%] [-9.00dB] [on]
"""


class FakeAmixer:
    def __init__(self, scontrols=SCONTROLS, sget=SGET):
        self.scontrols, self.sget, self.calls = scontrols, sget, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = self.scontrols if "scontrols" in cmd else self.sget
        return type("R", (), {"stdout": out})()


def test_card_from_alsa_device():
    assert _card_of("plughw:UACDemoV10,0") == "UACDemoV10"
    assert _card_of("hw:3,0") == "3"
    assert _card_of("plughw:CARD=Device,DEV=0") == "Device"
    assert _card_of("default") is None and _card_of("pipewire") is None


def test_finds_the_speaker_mixer_and_reads_mapped_level():
    run = FakeAmixer()
    hw = HardwareVolume.for_device("plughw:UACDemoV10,0", run=run)
    assert (hw.card, hw.control) == ("UACDemoV10", "PCM")
    assert hw.get() == 0.7
    assert "-M" in run.calls[-1]


def test_no_playback_volume_means_software_fallback():
    run = FakeAmixer(scontrols="Simple mixer control 'Mic',0\n", sget="Capabilities: cvolume\n")
    assert HardwareVolume.for_device("plughw:Device,0", run=run) is None
    assert HardwareVolume.for_device("default", run=run) is None


def test_set_maps_to_percent_and_zero_switches_off():
    run = FakeAmixer()
    hw = HardwareVolume("UACDemoV10", "PCM", run=run)
    hw.set(0.42)
    assert run.calls[-1][-2:] == ["42%", "unmute"]
    hw.set(0)
    assert run.calls[-1][-2:] == ["0%", "mute"]
    hw.set(7)
    assert run.calls[-1][-2:] == ["100%", "unmute"]


def test_switched_off_reads_as_zero():
    run = FakeAmixer(sget=SGET.replace("[on]", "[off]"))
    assert HardwareVolume("c", "PCM", run=run).get() == 0.0


def _wav(path, value=10000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(22050)
        w.writeframes(struct.pack("<h", value) * 100)


def test_scaled_wav_only_copies_below_full_gain(tmp_path):
    src = tmp_path / "a.wav"
    _wav(src)
    assert scaled_wav(str(src), 1.0) == str(src)
    out = scaled_wav(str(src), 0.5)
    try:
        with wave.open(out) as w:
            assert struct.unpack("<h", w.readframes(1))[0] == 5000
    finally:
        import os
        os.remove(out)
