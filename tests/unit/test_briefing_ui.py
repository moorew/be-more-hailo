"""The briefing on screen, drawn headless: cards, the sun icon and the
playing layout.  (Tap routing and playback run in tests/face_rig_harness.py.)"""
import datetime
import struct
import types
import wave

import pytest
from PIL import Image

from core.briefing import audio, cards, script, sources, ui
from tests.unit.test_weather import J1

NOW = datetime.datetime(2026, 9, 30, 7, 0)
HEADLINES = [{"title": f"Headline number {i} about something that happened overnight in town",
              "source": "CBC News", "published": NOW.timestamp() - 3600 * i} for i in range(5)]


def briefing_parts():
    weather = sources._select_days(sources._parse_j1(J1, "Brantford", 0), NOW.date())
    extras = {"sun": {"sunrise": "07:19", "sunset": "19:02"},
              "reminders": [{"time": "09:30", "message": "Stir the soup!", "kind": "timer"},
                            {"time": "14:00", "message": "Timer is up!", "kind": "timer"}],
              "countdowns": [{"name": "Mum's birthday", "days": 12}]}
    return script.build_script({"weather": weather, "headlines": HEADLINES, "extras": extras}, NOW)


@pytest.mark.parametrize("highlight", [None, 0, 4])
def test_every_card_draws_at_card_size(highlight):
    parts = briefing_parts()
    keys = [p["key"] for p in parts if p.get("card")]
    size = (cards.CARD_BOX[2] - cards.CARD_BOX[0], cards.CARD_BOX[3] - cards.CARD_BOX[1])
    for i, p in enumerate(parts):
        img = cards.draw_card(p, keys, min(i, 2), size, highlight=highlight, now_ts=NOW.timestamp())
        if p["key"] == "signoff":
            assert img is None
        else:
            assert img.size == size and img.mode == "RGBA"
            assert img.getpixel((size[0] // 2, size[1] // 2))[3] == 255     # opaque card
            assert img.getpixel((0, 0))[3] == 0                             # rounded corner


def test_cards_still_draw_when_fonts_are_missing(monkeypatch):
    monkeypatch.setattr(cards, "FONT_DIR", "/nonexistent")
    monkeypatch.setattr(cards, "_font_cache", {})
    part = briefing_parts()[0]
    assert cards.draw_card(part, ["weather"], 0, (498, 440)).size == (498, 440)


def test_rich_text_keeps_punctuation_on_bold_words():
    [line] = cards.wrap("Now: overcast, **19°C**, feels like 17°C", 20, 1000)
    assert line[2] == [("19°C", True), (",", False)]


def test_long_text_is_cut_with_an_ellipsis():
    lines = cards.wrap("word " * 50, 18, 200, max_lines=2)
    assert len(lines) == 2 and lines[-1][-1][-1][0].endswith("…")


@pytest.mark.parametrize("mins,label", [(2, "just now"), (35, "35 min ago"), (130, "2 h ago"), (1600, "yesterday")])
def test_age_label(mins, label):
    assert cards.age_label(1000 - mins * 60, 1000) == label


def test_icon_hit_box_scales_with_the_window():
    assert ui.icon_hit(700, 100, 800, 480) and not ui.icon_hit(680, 100, 800, 480)
    assert not ui.icon_hit(700, 120, 800, 480)
    assert ui.icon_hit(1400, 200, 1600, 960) and not ui.icon_hit(1360, 200, 1600, 960)


def test_icon_overlay_pops_bobs_and_fades():
    ov = ui.IconOverlay()
    frame = Image.new("RGB", (800, 480), cards.C["screen"])
    assert ov.apply(frame.copy(), now=0).getpixel(cards.ICON_CENTER) == frame.getpixel(cards.ICON_CENTER)
    ov.show(now=10)
    assert ov.visible
    small, _, _ = ov.sprite(10.05)
    assert small.width < cards.ICON_SPRITE                        # popping in
    _, _, dy1 = ov.sprite(10.5)                                   # bob peak (t = 0.5 s)
    _, _, dy2 = ov.sprite(11.5)                                   # and trough
    assert abs(dy1 - dy2) > 3                                     # bobbing ~4 px
    drawn = ov.apply(frame.copy(), now=12)
    assert drawn.getpixel(cards.ICON_CENTER) != frame.getpixel(cards.ICON_CENTER)
    ov.wiggle(now=13)
    assert ov.sprite(13.2)[0] is not ov._ready
    ov.hide(now=20)
    assert not ov.visible and ov.sprite(20.3) is not None         # fading
    assert ov.sprite(20 + ui.FADE_S + 0.01) is None


def test_icon_overlay_is_cheap_per_frame():
    import time
    ov = ui.IconOverlay()
    ov.show(now=0)
    frame = Image.new("RGB", (800, 480))
    t0 = time.perf_counter()
    for i in range(100):
        ov.apply(frame, now=1 + i / 30)
    assert (time.perf_counter() - t0) / 100 < 0.005


def _fake_face_view():
    from bmo_face import FaceRig, PillowRenderer
    rig = FaceRig()
    return types.SimpleNamespace(rig=rig, renderer=PillowRenderer(rig.shapes, (800, 480), "stretch", 2), _last=None)


def test_briefing_view_layout_and_part_changes():
    parts = briefing_parts()
    v = ui.BriefingView(_fake_face_view())
    v.start({"parts": parts}, now=100)
    v.show_part(0, now=100)
    start = v.tick(now=100.01)                                   # face still full screen
    assert start.size == (800, 480)
    steady = v.tick(now=102)
    assert steady.getpixel((500, 240)) != start.getpixel((500, 240))   # card has slid in
    assert v._face_rect(102) == cards.FACE_BOX
    v.show_part(1, now=103)
    v.set_highlight(2)
    v.tick(now=103.1)                                            # cross-fading
    v.show_part(3, now=104)                                      # sign-off keeps the last card
    assert v.index == 1
    v.finish(now=105)
    assert not v.finished(now=105.1) and v.finished(now=105 + ui.EXIT_S)
    assert v._face_rect(105 + ui.EXIT_S) == (0, 0, 800, 480)


def test_briefing_view_without_a_face_uses_full_width():
    v = ui.BriefingView(None)
    assert v.card_box == cards.CARD_BOX_FULL
    v.start({"parts": briefing_parts()}, now=0)
    v.show_part(0, caption="Good morning!", now=0)
    assert v.compose(None, now=5).getpixel((60, 240)) != Image.new("RGB", (1, 1), cards.C["screen"]).getpixel((0, 0))


def _tone(text, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(22050)
        w.writeframes(struct.pack("<h", 500) * 2205 * (1 + len(text) % 3))   # 0.1-0.3 s


def test_headline_segments_render_into_one_wav_with_marks(tmp_path):
    parts = briefing_parts()
    headlines = parts[1]
    assert [sg["mark"] for sg in headlines["segments"]] == [None, 0, 1, 2, 3, 4]
    saved = audio.render_briefing(parts, NOW.date(), cache_root=str(tmp_path), to_wav=_tone)
    h = saved["parts"][1]
    seg_durs = [0.1 * (1 + len(sg["speech"]) % 3) for sg in headlines["segments"]]
    assert [m["mark"] for m in h["marks"]] == [0, 1, 2, 3, 4]
    assert h["marks"][0]["at"] == pytest.approx(seg_durs[0], abs=1e-3)
    assert h["marks"][4]["at"] == pytest.approx(sum(seg_durs[:5]), abs=1e-3)
    assert h["duration"] == pytest.approx(sum(seg_durs), abs=0.01)
    assert sorted(p.name for p in (tmp_path / "2026-09-30").iterdir()) == \
        ["0.wav", "1.wav", "2.wav", "3.wav", "script.json"]               # no segment leftovers


def test_a_reset_view_still_draws():
    """The Tk thread can draw one more frame after playback resets the view."""
    v = ui.BriefingView(_fake_face_view())
    v.start({"parts": briefing_parts()}, now=0)
    v.show_part(0, now=0)
    v.reset()
    assert v.tick(now=1).size == (800, 480)
