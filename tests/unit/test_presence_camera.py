"""Presence (camera motion) and the camera's plain-words diagnosis.

No camera needed: frames are synthetic, the kernel log and config.txt are
strings (the -5 case is the real message from this Pi's IMX519)."""
import numpy as np

from core import camera
from core.presence import MotionDetector, Presence

H, W = 60, 80


def room(level=100, person=None, seed=0):
    rng = np.random.default_rng(seed)
    f = np.clip(rng.normal(level, 2, (H, W)), 0, 255).astype(np.uint8)   # sensor noise
    if person:
        x, y = person
        f[y:y + 25, x:x + 12] = 30
    return f


def test_still_room_and_noise_are_not_motion():
    d = MotionDetector()
    assert not any(d.feed(room(seed=i)) for i in range(30))


def test_someone_walking_in_is_motion_after_two_frames():
    d = MotionDetector()
    for i in range(5):
        d.feed(room(seed=i))
    assert d.feed(room(person=(10, 20), seed=10)) is False      # one frame isn't enough
    assert d.feed(room(person=(14, 20), seed=11)) is True


def test_lights_switching_on_is_not_motion():
    d = MotionDetector()
    for i in range(5):
        d.feed(room(100, seed=i))
    assert not d.feed(room(160, seed=7)) and not d.feed(room(160, seed=8))


def test_arrival_only_after_the_room_was_still():
    p = Presence(away_s=600)
    t = 0.0
    for i in range(5):
        p.feed(room(seed=i), t)
        t += 0.25
    arrivals = []
    for i in range(20):                       # someone moving about for 5 s
        arrivals.append(p.feed(room(person=(5 + 3 * i, 20), seed=100 + i), t))
        t += 0.25
    assert arrivals.count(True) == 1          # one arrival, not one per frame
    assert p.seen_within(10, t)
    t += 120                                  # back 2 minutes later: same visit
    assert not any(p.feed(room(person=(5 + 3 * i, 20), seed=200 + i), t + i * 0.25) for i in range(8))
    t += 900                                  # 15 minutes of nothing, then again
    assert any(p.feed(room(person=(40 - 3 * i, 20), seed=300 + i), t + i * 0.25) for i in range(8))


REAL_LOG = """[    6.377099] imx519 10-001a: failed to read chip id 519, with error -5
[    6.377360] imx519 10-001a: probe with driver imx519 failed with error -5"""


def test_diagnosis_of_a_camera_that_does_not_answer():
    out = camera.diagnose(kernel_log=REAL_LOG, config_txt="camera_auto_detect=0\ndtoverlay=imx519,cam0\n", cams=[])
    assert out[0] == "No camera is visible to libcamera."
    assert "IMX519" in out[1] and "error -5" in out[1] and "ribbon cable" in out[1]


def test_diagnosis_other_cases():
    assert camera.diagnose(cams=[{"Model": "imx519"}]) == ["OK: libcamera sees imx519."]
    out = camera.diagnose(kernel_log="", config_txt="camera_auto_detect=0\n", cams=[])
    assert "camera_auto_detect is off" in out[1]
    out = camera.diagnose(kernel_log="", config_txt="dtoverlay=imx708,cam1\n", cams=[])
    assert "forces imx708,cam1" in out[1]


def test_photo_without_a_camera_says_why(monkeypatch, tmp_path):
    class R:
        returncode, stderr = 255, "ERROR: *** no cameras available ***\nNo cameras available!"
    monkeypatch.setattr(camera.shutil, "which", lambda name: "/usr/bin/rpicam-still")
    monkeypatch.setattr(camera.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(camera, "cameras", lambda: [])
    try:
        camera.Camera().photo(str(tmp_path / "x.jpg"))
    except camera.CameraError as e:
        assert "can't find my camera" in str(e) and "ribbon cable" in str(e)
    else:
        raise AssertionError("expected CameraError")
