"""Does an utterance ask for the morning briefing?  A pure matcher.

Matches only when the whole utterance is essentially the request, after
stripping "BMO", "hey", "please" and the like, so "good morning, what's the
weather?" still goes to the normal weather answer.

    GOOD_MORNING  "good morning", "morning BMO!"         -> plays only if a
                  briefing is ready and unplayed; otherwise BMO just chats
    BRIEFING      "morning briefing", "show me my briefing", "brief me",
                  "what's my day look like?"             -> plays any time,
                  preparing a fresh one if needed
"""
import re

GOOD_MORNING = "good_morning"
BRIEFING = "briefing"

# Dropped from either end, repeatedly ("hey bmo ... please friend").
_EDGE_WORDS = {"bmo", "beemo", "bemo", "bimo", "b", "m", "o", "hey", "hi", "hello", "oh", "ok", "okay", "so", "well", "um", "uh",
               "friend", "buddy", "pal", "please", "thanks", "thank", "you", "now", "again", "there"}
# Dropped from the front: polite wrappers around the request itself.
_LEADS = ("can you", "could you", "would you", "will you", "can i", "could i", "can we", "i want to",
          "i'd like to", "i would like to", "i wanna", "let's", "lets", "go ahead and", "time for",
          "it's time for", "i want", "i'd like")

_REQUEST_VERB = r"(?:show|play|give|read|start|do|run|tell|get|bring up|pull up|open|replay|repeat|hear|have)"
_BRIEFING_NOUN = (r"(?:(?:my|the|our|your|a|today's|todays|this morning's|this mornings)\s+)?"
                  r"(?:(?:morning|daily|day's|days|news)\s+)?"
                  r"(?:briefing|brief|rundown|round ?up|news update)")
_BRIEFING_PATTERNS = [re.compile(p) for p in (
    rf"(?:{_REQUEST_VERB}(?:\s+(?:me|us))?\s+)?{_BRIEFING_NOUN}(?:\s+(?:today|please))?",
    r"brief me",
    r"(?:catch|fill) me (?:up|in)",
    r"what(?:'s| is| does)? (?:on |in )?(?:my|the) (?:day|agenda)(?: today)?(?: look(?:ing)?(?: like)?)?",
    r"what does (?:my|the) day look like(?: today)?",
    r"how(?:'s| is| does) (?:my|the) day look(?:ing)?(?: like)?",
    r"tell me about (?:my|the) day",
)]
# Whisper mishears the verb ("share me my briefing", "sure me the briefing"),
# so any short utterance about *the briefing* counts, unless it's asking what
# a briefing is.  "briefing" is rare enough in chat that this is safe.
_BRIEFING_WORD = re.compile(r"\b(?:morning |daily |my |the |today'?s )?briefing\b|\bbrief me\b")
_ABOUT_THE_WORD = re.compile(r"\b(?:mean|means|meaning|definition|spell|what is a|what's a|picture|image|photo|draw)\b")
MAX_LOOSE_WORDS = 7
_GOOD_MORNING = re.compile(r"(?:good )?morning(?: to)?")  # "to you": "you" is an edge word


def _normalise(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^\w\s']", " ", text)
    words = text.split()
    changed = True
    while changed and words:
        changed = False
        while words and words[0].strip("'") in _EDGE_WORDS:
            words.pop(0)
            changed = True
        while words and words[-1].strip("'") in _EDGE_WORDS:
            words.pop()
            changed = True
        joined = " ".join(words)
        for lead in _LEADS:
            if joined == lead or joined.startswith(lead + " "):
                words = words[len(lead.split()):]
                changed = True
                break
    return " ".join(words)


def match(text: str):
    """GOOD_MORNING, BRIEFING, or None."""
    t = _normalise(text)
    if not t:
        return None
    if _GOOD_MORNING.fullmatch(t):
        return GOOD_MORNING
    if any(p.fullmatch(t) for p in _BRIEFING_PATTERNS):
        return BRIEFING
    if (_BRIEFING_WORD.search(t) and len(t.split()) <= MAX_LOOSE_WORDS
            and not _ABOUT_THE_WORD.search(t)):
        return BRIEFING
    return None
