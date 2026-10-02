"""Starting games by voice, and the game sound mixer."""
import numpy as np
import pytest

from core.games import sound
from core.games.voice import match
from core.llm import Brain


@pytest.mark.parametrize("text,key", [
    ("play BMO says", "bmo_says"), ("Can we play memory?", "memory"), ("play Simon says", "bmo_says"),
    ("let's play the matching game", "memory"),
])
def test_named_games(text, key):
    assert match(text) == key


def test_play_a_game_picks_one():
    assert match("Let's play a game!") in ("bmo_says", "memory")


@pytest.mark.parametrize("text", ["who won the game last night", "play some music", "what's the score of the game",
                                  "tell me about video games", "play a song", "Let's go", "what time is it",
                                  "Let's play trivia", "let's play a guessing game", "can we play I spy",
                                  "let's play twenty questions"])
def test_not_games(text):
    assert match(text) is None


def test_brain_starts_games_without_the_llm():
    out = Brain(persist=False).think("let's play memory")
    assert out == 'Yay! Let\'s play Memory Match! {"action": "play_game", "game": "memory"}'


def test_mixer_overlaps_sounds_and_new_notes_cut_old_ones():
    gs = sound.GameSound("default")
    gs._proc = object()                 # pretend aplay is running
    gs.play("win")
    gs.play("tone:0")
    a = gs.mix()
    assert len(a) == sound.CHUNK and np.abs(a).max() > 0
    gs.play("tone:1")                   # replaces tone:0, win keeps going
    assert sorted(p[2] for p in gs._playing) == ["tone", "win"]
    for _ in range(200):
        gs.mix()
    assert gs._playing == [] and np.abs(gs.mix()).max() == 0


def test_unknown_or_no_stream_is_silent():
    gs = sound.GameSound("default")
    gs.play("tone:0")                   # no aplay: ignored
    gs._proc = object()
    gs.play("nope")
    assert gs._playing == []
