"""BMO's mini games on a fake clock: BMO Says (Simon) and Memory Match."""
import random
import time

import pytest

from core.games import GAMES, BMOSays, MemoryMatch, art, bmo_says, by_name, memory


def center(box):
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


EXIT = center(art.EXIT_BOX)


def tap_pad(g, pad, now):
    g.tap(*center(bmo_says.PADS[pad]), now)


def sequence_end(g):
    on, gap = g.timing()
    return g.t0 + len(g.seq) * (on + gap) + 0.01


def play_round(g, now):
    """Wait out BMO's turn, then repeat the sequence; returns the time after."""
    now = max(now, sequence_end(g))
    g.update(now)
    assert g.state == "input"
    for p in g.seq:
        tap_pad(g, p, now)
        now += 0.4
    return now


def overlay_button(game_module, key, game):
    _, boxes = game_module._overlay(*((game.round, game.best, game.new_best) if game_module is bmo_says
                                      else (game.moves, game.best, game.new_best)))
    x, y = center(boxes[key])
    ox, oy = game_module.OVERLAY_POS
    return x + ox, y + oy


# --- BMO Says ------------------------------------------------------------------

def test_says_plays_sequence_with_tones_and_ignores_taps():
    g = BMOSays(rng=random.Random(7), now=0.0)
    assert g.state == "show" and g.round == 1 and g.status == "Watch BMO!"
    on, gap = g.timing()
    assert (on, gap) == pytest.approx((0.45, 0.15))
    assert g.lit_pad(0.1) is None                        # lead-in pause
    mid = g.t0 + on / 2
    g.frame(mid)
    assert g.lit_pad(mid) == g.seq[0]
    assert g.sounds() == [f"tone:{g.seq[0]}"]
    assert g.lit_pad(g.t0 + on + gap / 2) is None        # the gap between notes
    tap_pad(g, g.seq[0], mid)                            # BMO's turn: ignored
    assert g.sounds() == [] and g.pos == 0 and g.state == "show"
    g.update(sequence_end(g))
    assert g.state == "input" and g.status == "Your turn!"


def test_says_tone_backlog_is_not_replayed():
    g = BMOSays(rng=random.Random(1), now=0.0)
    g.seq = [0, 1, 2, 3]
    g._start_show(1.0)
    on, gap = g.timing()
    g.update(1.0 + 2 * (on + gap) + 0.05)                # skipped notes 0 and 1
    assert g.sounds() == ["tone:2"]


def test_says_correct_repeat_advances_round_and_speeds_up():
    g = BMOSays(rng=random.Random(3), now=0.0)
    first = list(g.seq)
    now = play_round(g, 0.0)
    assert g.sounds()[-2:] == [f"tone:{first[0]}", "win"]
    assert g.state == "won"
    g.update(now + 0.2)
    assert g.state == "won" and g.round == 1              # short pause
    tap_pad(g, 0, now + 0.2)                             # ignored while celebrating
    assert g.sounds() == []
    g.update(now + bmo_says.WIN_PAUSE + 0.01)
    assert g.state == "show" and g.round == 2 and g.seq[:1] == first
    for _ in range(4):
        now = play_round(g, now + 3)
        g.update(now + bmo_says.WIN_PAUSE + 0.01)
    assert g.round == 6
    on, gap = g.timing()
    assert on < 0.45 and gap < 0.15 and on >= 0.45 * bmo_says.MIN_SPEED


def test_says_player_tap_lights_pad_and_emits_tone():
    g = BMOSays(rng=random.Random(4), now=0.0)
    g.seq = [2, 2]
    g._start_show(0.0)
    g.update(sequence_end(g))
    g.sounds()
    tap_pad(g, 2, 5.0)
    assert g.sounds() == ["tone:2"]
    assert g.lit_pad(5.1) == 2 and g.lit_pad(5.0 + bmo_says.TAP_FLASH + 0.01) is None
    assert g.state == "input" and g.pos == 1


def test_says_wrong_tap_loses_and_play_again_resets():
    g = BMOSays(rng=random.Random(5), now=0.0)
    now = play_round(g, 0.0)
    g.update(now + 2)
    g.update(sequence_end(g))
    g.sounds()
    wrong = (g.seq[0] + 1) % 4
    tap_pad(g, wrong, 20.0)
    assert g.sounds() == [f"tone:{wrong}", "lose"]
    assert g.state == "lost" and g.status == "Oops! You got to round 2"
    assert g.best == 2 and g.new_best
    tap_pad(g, g.seq[0], 20.5)                           # pads are under the card now
    assert g.sounds() == []
    g.tap(*overlay_button(bmo_says, "again", g), 21.0)
    assert g.state == "show" and g.round == 1 and g.best == 2 and not g.finished


def test_says_done_and_exit_finish():
    g = BMOSays(rng=random.Random(5), now=0.0)
    g.tap(*EXIT, 0.1)                                    # exit works even during BMO's turn
    assert g.finished
    g = BMOSays(rng=random.Random(5), now=0.0)
    g.update(sequence_end(g))
    tap_pad(g, (g.seq[0] + 1) % 4, 3.0)
    g.tap(*overlay_button(bmo_says, "done", g), 3.5)
    assert g.finished


# --- Memory Match ----------------------------------------------------------------

def pairs_of(m):
    out = {}
    for i, k in enumerate(m.deck):
        out.setdefault(k, []).append(i)
    return list(out.values())


def tap_card(m, i, now):
    m.tap(*center(memory.CARDS[i]), now)


def test_memory_deal_is_deterministic():
    a, b = MemoryMatch(rng=random.Random(42)), MemoryMatch(rng=random.Random(42))
    assert a.deck == b.deck
    assert sorted(a.deck) == sorted(memory.ICONS * 2) and len(a.deck) == 12
    assert MemoryMatch(rng=random.Random(43)).deck != a.deck
    assert all(a.kind(i) == "back" for i in range(12)) and a.moves == 0


def test_memory_match_and_mismatch_timing():
    m = MemoryMatch(rng=random.Random(1), now=0.0)
    p = pairs_of(m)
    tap_card(m, p[0][0], 1.0)
    tap_card(m, p[0][1], 1.5)
    assert m.sounds() == ["flip", "flip", "match"]
    assert m.moves == 1 and m.matched == set(p[0]) and m.up == []
    tap_card(m, p[0][0], 2.0)                            # matched cards stay put
    assert m.sounds() == []
    a, b, c = p[1][0], p[2][0], p[3][0]
    tap_card(m, a, 3.0)
    tap_card(m, b, 3.2)
    assert m.moves == 2 and m.up == [a, b]
    assert m.sounds() == ["flip", "flip"]
    tap_card(m, c, 3.5)                                  # no third card while two are up
    tap_card(m, a, 3.5)
    assert m.up == [a, b] and m.sounds() == [] and m.moves == 2
    m.update(3.2 + memory.MISMATCH_DELAY - 0.05)
    assert m.up == [a, b]
    m.frame(3.2 + memory.MISMATCH_DELAY + 0.01)
    assert m.up == [] and m.kind(a) == m.kind(b) == "back"
    assert m.sounds() == ["flip"]
    tap_card(m, c, 4.5)
    assert m.up == [c]


def test_memory_win_counts_moves_and_play_again():
    m = MemoryMatch(rng=random.Random(9), now=0.0)
    p = pairs_of(m)
    tap_card(m, p[0][0], 0.5)                            # one miss first
    tap_card(m, p[1][0], 0.6)
    now = 2.0
    for a, b in p:
        tap_card(m, a, now)
        tap_card(m, b, now + 0.3)
        now += 1
    ev = m.sounds()
    assert ev[-2:] == ["match", "win"] and ev.count("match") == 6 and ev.count("win") == 1
    assert m.moves == 7 and m.state == "won"
    assert m.status == "You did it in 7 moves!" and m.best == 7
    tap_card(m, 0, now)                                  # card not up yet
    assert not m.overlay_shown
    m.update(now + memory.WIN_DELAY)
    assert m.overlay_shown
    m.tap(*overlay_button(memory, "again", m), now + 1)
    assert m.state == "play" and m.moves == 0 and not m.matched and m.best == 7
    assert m.status == "Find the pairs!"


def test_memory_exit_and_done():
    m = MemoryMatch(rng=random.Random(9), now=0.0)
    m.tap(*EXIT, 1.0)
    assert m.finished
    m = MemoryMatch(rng=random.Random(9), now=0.0)
    now = 1.0
    for a, b in pairs_of(m):
        tap_card(m, a, now)
        tap_card(m, b, now)
    m.update(now + 5)
    m.tap(*overlay_button(memory, "done", m), now + 5)
    assert m.finished


# --- frames ------------------------------------------------------------------------

def _says_states():
    g = BMOSays(rng=random.Random(2), now=0.0)
    yield g, g.t0 + 0.1                                    # BMO playing, pad lit
    yield g, 0.2                                           # lead-in
    end = sequence_end(g)
    yield g, end                                           # your turn
    tap_pad(g, g.seq[0], end)
    yield g, end + 0.1                                     # won pause, pad lit
    g.update(end + 5)
    g.update(sequence_end(g))
    tap_pad(g, (g.seq[0] + 1) % 4, end + 9)
    yield g, end + 9.1                                     # lost card


def _memory_states():
    m = MemoryMatch(rng=random.Random(2), now=0.0)
    yield m, 0.0
    p = pairs_of(m)
    tap_card(m, p[0][0], 1.0)
    yield m, 1.05                                          # mid flip
    tap_card(m, p[1][0], 1.3)
    yield m, 1.8                                           # two up
    now = 3.0
    for a, b in p:
        tap_card(m, a, now)
        tap_card(m, b, now)
        now += 0.5
    yield m, now - 0.4                                     # pop
    yield m, now + 2                                       # win card


@pytest.mark.parametrize("states", [_says_states, _memory_states])
def test_frames_are_full_screen_rgb_and_fast(states):
    for g, now in states():
        img = g.frame(now)
        assert img.size == (800, 480) and img.mode == "RGB"
    g = GAMES["bmo_says" if states is _says_states else "memory"](rng=random.Random(8), now=0.0)
    g.frame(0.0)                                           # warm the sprite caches
    times = []
    for k in range(60):
        now = k / 30
        if k % 9 == 0 and isinstance(g, MemoryMatch):
            tap_card(g, k % 12, now)
        t = time.perf_counter()
        g.frame(now)
        times.append(time.perf_counter() - t)
    assert sum(times) / len(times) < 0.060


def test_lit_pad_changes_the_frame():
    g = BMOSays(rng=random.Random(2), now=0.0)
    a = g.frame(0.1).tobytes()
    b = g.frame(g.t0 + 0.1).tobytes()
    assert a != b
    assert g.frame(0.1) is g.frame(0.2)                    # nothing changed: same image reused


# --- names -----------------------------------------------------------------------------

@pytest.mark.parametrize("text,key", [
    ("simon", "bmo_says"), ("Simon says", "bmo_says"), ("let's play BMO says!", "bmo_says"),
    ("Beemo says", "bmo_says"), ("bmo_says", "bmo_says"), ("memory", "memory"),
    ("the matching game", "memory"), ("Pairs", "memory"), ("memory match please", "memory"),
    ("play a game", None), ("", None), ("what's the weather", None),
])
def test_by_name(text, key):
    assert by_name(text) == key


def test_games_registry():
    assert GAMES == {"bmo_says": BMOSays, "memory": MemoryMatch}
    assert BMOSays.name == "BMO Says" and MemoryMatch.name == "Memory Match"
    g = BMOSays()
    assert g.finished is False and isinstance(g.status, str) and g.sounds() == []
