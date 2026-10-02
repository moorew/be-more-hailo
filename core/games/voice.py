"""Does an utterance ask to play one of BMO's games?  A pure matcher.

"Let's play a game", "play BMO says", "can we play memory?" -> a GAMES key.
Needs a play word ("play", "let's", "wanna"...) together with a game name
or the word "game", and isn't a question about a sports game ("who won the
game?") or a request for music.
"""
import itertools
import re

from core.games import GAMES, by_name

_PLAY = re.compile(r"\b(?:play|let'?s|wanna|want to|can we|could we|shall we)\b")
_GAME = re.compile(r"\bgames?\b")
_NOT = re.compile(r"\b(?:who|score|won|win|lost|hockey|football|soccer|baseball|basketball|"
                  r"video ?games?|on tv|watch|tonight'?s game|music|song)\b")
# Talking games the LLM hosts ("let's play trivia", "a guessing game"): not touch games.
_TALKING = re.compile(r"\b(?:trivia|guess(?:ing)?|quiz|riddles?|twenty questions|20 questions|i spy|"
                      r"word|would you rather|story|rhym\w*|knock knock|tag|hide and seek)\b")
_turns = itertools.cycle(sorted(GAMES))          # "play a game" alternates between them


def match(text: str):
    t = " ".join(re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower()).split())
    if not t or not _PLAY.search(t) or _NOT.search(t) or _TALKING.search(t) or len(t.split()) > 10:
        return None
    key = by_name(t)
    if key:
        return key
    if _GAME.search(t):
        return next(_turns)
    return None
