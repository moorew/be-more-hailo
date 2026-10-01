"""Faces must leave room for the screen edges and the footer caption.

The v2 rig's heart face put its pixel blush 10 px from the screen edges and its
mouth under the caption; capturing's shock lines hugged the top-left corner; and
confused's flat brows sat on its enlarged eyes.  These checks run every face
through a few seconds of animation and measure the drawn geometry.
"""
import numpy as np
import pytest

from bmo_face import FaceRig

K = 800 / 1280                    # art units (1280x720) -> screen px (800x480)
FOOTER_TOP = 480 * 0.97 - 32      # agent_hailo.STATUS_RELY, 32 px tall caption
FOOTER_X = (250, 550)             # caption is centred and at most ~300 px wide
SIDE_MARGIN = 40
FOOTER_CLEARANCE = 10

NAMES = list(FaceRig().presets["expressions"])


def _parts(frame):
    for e in frame["eyes"]:
        yield "eye", np.asarray(e["pts"]), e.get("stroke", 0)
        if e.get("brow"):
            yield "brow", np.asarray(e["brow"]["pts"]), e["brow"]["w"]
    for m in frame.get("marks", []):
        yield "mark:" + m["key"], np.asarray(m["pts"]), m.get("width", 0)
    yield "mouth", np.asarray(frame["mouth"]["outer"]), frame["mouth"].get("stroke", 0)


def _frames(name, seconds=4.0, every=4):
    rig = FaceRig()
    rig.blinker.next = 99
    rig.set_expression(name, instant=True)
    for i in range(int(seconds * 30)):
        rig.update(1 / 30)
        if i % every == 0:
            yield rig.frame()


@pytest.mark.parametrize("name", NAMES)
def test_face_clears_edges_and_footer(name):
    for f in _frames(name):
        for part, p, w in _parts(f):
            if not len(p):
                continue
            x0, x1 = (p[:, 0].min() - w / 2) * K, (p[:, 0].max() + w / 2) * K
            y1 = (p[:, 1].max() + w / 2) * K
            assert x0 >= SIDE_MARGIN and 800 - x1 >= SIDE_MARGIN, f"{name}: {part} at x {x0:.0f}-{x1:.0f}"
            if x1 > FOOTER_X[0] and x0 < FOOTER_X[1]:
                assert FOOTER_TOP - y1 >= FOOTER_CLEARANCE, f"{name}: {part} reaches y {y1:.0f} (caption at {FOOTER_TOP:.0f})"


def test_confused_brows_clear_the_eyes():
    for f in _frames("confused"):
        for e in f["eyes"]:
            brow, eye = np.asarray(e["brow"]["pts"]), np.asarray(e["pts"])
            d = np.sqrt(((brow[:, None] - eye[None]) ** 2).sum(-1)).min()
            assert d - e["brow"]["w"] / 2 - e["stroke"] / 2 > 10


def test_mark_offset_moves_a_mark_and_holds_while_it_fades():
    import copy

    def blush_x(presets, then=None):
        rig = FaceRig()
        rig.presets = presets
        rig.set_expression("heart", instant=True)
        if then:
            rig.set_expression(then)       # heart's marks start fading out
            rig.update(1 / 30)
        m = [m for m in rig.frame()["marks"] if m["key"] == "pixelBlushL"][0]
        return float(np.asarray(m["pts"])[:, 0].min())

    tuned = FaceRig().presets
    plain = copy.deepcopy(tuned)
    plain["expressions"]["heart"].pop("markOffset")
    dx = tuned["expressions"]["heart"]["markOffset"]["pixelBlushL"][0]
    assert blush_x(tuned) == pytest.approx(blush_x(plain) + dx, abs=0.01)
    # the fading-out blush keeps its nudge instead of jumping back
    assert blush_x(tuned, then="idle") == pytest.approx(blush_x(plain, then="idle") + dx, abs=0.01)
