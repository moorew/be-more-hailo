"""Hardware-free checks for the bmo_face rig (numpy + Pillow only)."""

import os
import wave

import numpy as np
import pytest
from PIL import ImageChops

from bmo_face import FaceRig, LipSync, PillowRenderer, analyse_wav
from bmo_face.tk_face import SpeechSchedule

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GREETING = os.path.join(REPO, "sounds", "greeting_sounds", "greeting_10.wav")
needs_greeting = pytest.mark.skipif(not os.path.exists(GREETING), reason="sounds/ not present")


def test_every_expression_renders():
    rig = FaceRig()
    renderer = PillowRenderer(rig.shapes, (800, 480))
    for name in rig.presets["expressions"]:
        rig.set_expression(name)
        for _ in range(15):
            rig.update(1 / 30)
        img = renderer.render(rig.frame())
        assert img.size == (800, 480)
        assert ImageChops.difference(img, renderer.base).getbbox() is not None, name


@pytest.mark.parametrize("supersample", [1, 2, 4])
def test_line_mouth_has_no_stray_fill(supersample):
    # Regression: Pillow's polygon fill used to paint chords across zero-area
    # (line-only) mouths like the idle smile.
    rig = FaceRig()
    rig.p["breathe"].snap(0)
    img = PillowRenderer(rig.shapes, (800, 480), supersample=supersample).render(rig.frame())
    cavity = tuple(int(rig.shapes["colors"]["cavity"][i:i + 2], 16) for i in (1, 3, 5))
    assert cavity not in {c for _, c in img.getcolors(1 << 20)}


def test_rig_follows_the_viseme():
    rig = FaceRig()
    rig.set_speech({"viseme": "D", "intensity": 0.8, "active": True, "onset": True})
    for _ in range(20):
        rig.update(1 / 30)
    assert rig.mouth_w["D"].value > 0.95
    assert rig.mouth_w["smile"].value < 0.05


def test_silence_stays_at_rest():
    ls = LipSync(22050)
    out = [ls.push(np.zeros(512, dtype=np.int16)) for _ in range(30)]
    assert all(o["viseme"] == "X" and not o["active"] for o in out)


@needs_greeting
def test_real_voice_uses_the_whole_mouth_chart():
    items, duration = analyse_wav(GREETING)
    talking = [s["viseme"] for _, _, s in items if s["active"]]
    assert set("BCDEF") <= set(talking)
    changes = sum(1 for a, b in zip(talking, talking[1:]) if a != b)
    assert 3 <= changes / duration <= 14  # readable, not flickering
    assert not items[-1][2]["active"] or items[-1][2]["viseme"] in "AX"


@needs_greeting
def test_schedule_replays_in_time():
    items, duration = analyse_wav(GREETING)
    expected = [s["viseme"] for _, _, s in items]
    sched = SpeechSchedule()
    sched.load_wav(GREETING, start=100.0)
    # Poll mid-chunk so each poll lands on exactly one new entry.
    got = [sched.poll(100.0 + (k + 0.5) * 512 / 22050)["viseme"] for k in range(len(expected))]
    assert got == expected
    assert not sched.poll(100.0 + duration + 1.0)["active"]


def test_wav_lipsync_handles_stereo(tmp_path):
    path = tmp_path / "stereo.wav"
    t = np.arange(22050) / 22050
    tone = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(np.column_stack([tone, tone]).tobytes())
    items, duration = analyse_wav(str(path))
    assert abs(duration - 1.0) < 0.01
    assert any(s["active"] for _, _, s in items)


# ---- every face (rig v2: glyph eyes, marks, critters)

def _run(rig, seconds, speech=None):
    for _ in range(int(seconds * 30)):
        if speech is not None:
            rig.set_speech(speech)
        rig.update(1 / 30)


def test_every_preset_draws_its_extras():
    rig = FaceRig()
    renderer = PillowRenderer(rig.shapes, (800, 480), supersample=2)
    for name, e in rig.presets["expressions"].items():
        rig.set_expression(name, instant=True)
        _run(rig, 0.8)
        f = rig.frame()
        missing = set(e.get("marks", [])) - {m["key"] for m in f["marks"]}
        # floating/twinkling marks can be momentarily see-through
        missing = {k for k in missing if rig.shapes["marks"][k].get("anim", {}).get("type") not in ("float", "twinkle", "blink")}
        assert not missing, (name, missing)
        if e.get("critter"):
            assert f["critter"] and f["critter"]["name"] == e["critter"], name
        renderer.render(f)


def test_glyph_eyes_swap_with_a_pop_not_a_morph():
    rig = FaceRig()
    rig.set_expression("dizzy", instant=True)
    rig.set_expression("heart")
    widths = []
    for _ in range(12):
        rig.update(1 / 30)
        pts = rig.frame()["eyes"][0]["pts"]
        widths.append(float(pts[:, 0].max() - pts[:, 0].min()))
    assert min(widths) < 40  # the spirals shrink right down before the hearts pop in
    assert rig.eye_w["heart"].value == 1.0 and rig.eye_w["spiral"].value == 0.0


def test_eyes_follow_the_bee():
    rig = FaceRig()
    rig.set_expression("bee", instant=True)
    agree = 0
    for _ in range(240):
        rig.update(1 / 30)
        dx = rig.critter["pose"]["x"] - 640
        if abs(dx) > 200 and np.sign(rig.gaze.x.value) == np.sign(dx):
            agree += 1
    assert agree > 60


def test_mouth_extras_tuck_away_while_talking():
    rig = FaceRig()
    rig.set_expression("cheeky", instant=True)
    assert rig.mark_vis["tongueOut"].value > 0.9
    _run(rig, 1.0, {"viseme": "C", "intensity": 0.7, "active": True, "onset": False})
    assert rig.mark_vis["tongueOut"].value < 0.05
    assert rig.mark_vis["cheekyLidL"].value > 0.9  # eye extras stay


def test_camera_flash_fades():
    rig = FaceRig()
    rig.set_expression("capturing")
    rig.update(1 / 30)
    assert rig.frame()["flash"] > 0.5
    _run(rig, 1.0)
    assert rig.frame()["flash"] == 0.0
