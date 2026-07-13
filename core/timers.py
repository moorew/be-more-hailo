"""Deterministic parsing of timer / reminder requests.

qwen3:1.7b cannot be trusted to emit timer JSON: asked to "remind me in 30
seconds to stir the soup" it produced `{"minutes": 30}` (wrong unit) and copied
the reminder text verbatim from the prompt's example.  Timers are exactly the
kind of thing that must not be probabilistic, so we parse them here — the same
pre-LLM routing already used for photos, music and image display.
"""
import re

# Clamp: 3 seconds … 12 hours.  Matches the bounds the GUI timer thread expects.
MIN_MINUTES = 0.05
MAX_MINUTES = 720.0

_UNIT_TO_MINUTES = {
    "second": 1 / 60, "seconds": 1 / 60, "sec": 1 / 60, "secs": 1 / 60, "s": 1 / 60,
    "minute": 1.0, "minutes": 1.0, "min": 1.0, "mins": 1.0, "m": 1.0,
    "hour": 60.0, "hours": 60.0, "hr": 60.0, "hrs": 60.0, "h": 60.0,
}

_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "fifty": 50, "sixty": 60, "half": 0.5,
}

# "timer for 10 minutes", "remind me in 30 seconds", "set an alarm for 2 hours"
_TRIGGER_RE = re.compile(
    r"\b(?:set\s+(?:a|an)?\s*)?(?:timer|alarm|reminder)\b|\bremind\s+me\b",
    re.IGNORECASE,
)

_DURATION_RE = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?|" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")"
    r"\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])\b",
    re.IGNORECASE,
)

# The bit after "to …" / "for …" that says what the reminder is about.
_SUBJECT_RE = re.compile(
    r"\bto\s+(?P<subject>.+?)\s*$|\babout\s+(?P<subject2>.+?)\s*$",
    re.IGNORECASE,
)


def _qty_to_float(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return float(_WORD_NUMBERS[raw.lower()])


def parse_timer_request(text: str):
    """Return {"minutes": float, "message": str} if `text` asks for a timer, else None.

    Only fires when both a trigger word and a duration are present, so "set the
    mood" or "how many minutes until dinner" don't create phantom timers.
    """
    if not text or not _TRIGGER_RE.search(text):
        return None

    duration = _DURATION_RE.search(text)
    if not duration:
        return None

    minutes = _qty_to_float(duration.group("qty")) * _UNIT_TO_MINUTES[duration.group("unit").lower()]
    if minutes <= 0:
        return None
    minutes = max(MIN_MINUTES, min(MAX_MINUTES, minutes))

    # Reminder subject: prefer text after the duration ("...in 5 minutes to stir the soup"),
    # falling back to the whole utterance so we never invent an unrelated message.
    tail = text[duration.end():]
    subject_match = _SUBJECT_RE.search(tail) or _SUBJECT_RE.search(text)
    message = "Timer is up!"
    if subject_match:
        subject = subject_match.group("subject") or subject_match.group("subject2")
        if subject:
            subject = subject.strip().rstrip("?.!").strip()
            # Guard against the model's placeholder and against swallowing the duration.
            if subject and subject not in {"...", "…"} and not _DURATION_RE.fullmatch(subject):
                message = subject[0].upper() + subject[1:] + "!"

    return {"minutes": round(minutes, 4), "message": message}


def describe_duration(minutes: float) -> str:
    """Human phrasing for BMO's spoken confirmation ('30 seconds', '1 hour')."""
    if minutes < 1:
        secs = int(round(minutes * 60))
        return f"{secs} second{'s' if secs != 1 else ''}"
    if minutes < 60:
        mins = int(minutes) if float(minutes).is_integer() else round(minutes, 1)
        return f"{mins} minute{'s' if mins != 1 else ''}"
    hours = minutes / 60
    hours = int(hours) if float(hours).is_integer() else round(hours, 1)
    return f"{hours} hour{'s' if hours != 1 else ''}"
