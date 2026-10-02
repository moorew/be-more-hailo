"""BMO's mini games: tap-only, full screen, drawn with Pillow (no Tk).

    game = GAMES[by_name("let's play simon")](rng=random.Random(), now=t)
    game.tap(x, y, now); img = game.frame(now); game.sounds(); game.finished

Sound events: "tone:0".."tone:3" (BMO Says pads: red, blue, green, yellow),
"win", "lose", "flip", "match".
"""
import re

from core.games.base import Game
from core.games.bmo_says import BMOSays
from core.games.memory import MemoryMatch

GAMES = {"bmo_says": BMOSays, "memory": MemoryMatch}

# Checked in order; "memory" alone comes last so "memory sequence" stays BMO Says.
_NAMES = (
    ("bmo_says", ("bmo says", "b m o says", "simon says", "simon", "copy me", "copycat", "copy cat",
                  "repeat after me", "follow the leader", "colou?r game", "button game", "music game",
                  "sequence game", "memory sequence")),
    ("memory", ("memory match", "memory game", "matching game", "match game", "match the cards",
                "matching cards", "match pairs", "pairs", "pair game", "concentration", "card game",
                "flip cards", "card flip", "memory")),
)


def by_name(text: str) -> str | None:
    """Map a spoken game name to a GAMES key, or None.  "Let's play Simon says!" -> "bmo_says"."""
    t = (text or "").lower().replace("_", " ")
    t = re.sub(r"\b(beemo|beemoe|bimo|bmo's)\b", "bmo", t)
    t = " " + " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split()) + " "
    for key, names in _NAMES:
        for n in names:
            if re.search(" " + n + " ", t):
                return key
    return None


__all__ = ["Game", "GAMES", "BMOSays", "MemoryMatch", "by_name"]
