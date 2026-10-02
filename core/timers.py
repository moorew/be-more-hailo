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

# Digits take any unit ("5m", "30 secs"); word numbers need a whole unit word,
# or "set an alarm for 7am" reads "am" as "a" + "m" = one minute.
_DURATION_RE = re.compile(
    r"\b(?:(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])"
    r"|(?P<wqty>" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")"
    r"\s+(?P<wunit>seconds?|secs?|minutes?|mins?|hours?|hrs?))\b",
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

    qty = duration.group("qty") or duration.group("wqty")
    unit = duration.group("unit") or duration.group("wunit")
    minutes = _qty_to_float(qty) * _UNIT_TO_MINUTES[unit.lower()]
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

    name = timer_name(text)
    if name and message == "Timer is up!":
        message = f"The {name} timer is done!"
    out = {"minutes": round(minutes, 4), "message": message}
    if name:
        out["name"] = name
    return out


# "set a pasta timer", "an egg timer for 6 minutes", "the laundry timer"
_NAME_RE = re.compile(r"\b(?:a|an|the|my)\s+(?P<name>[a-z][a-z'-]*(?:\s+[a-z][a-z'-]*)?)\s+timers?\b", re.I)
_NOT_NAMES = set(_WORD_NUMBERS) | set(_UNIT_TO_MINUTES) | {
    "new", "quick", "short", "long", "another", "kitchen timer", "countdown", "little", "few", "couple"}


def timer_name(text: str):
    """'set a pasta timer for 10 minutes' -> 'pasta'; None for plain timers."""
    m = _NAME_RE.search(text or "")
    if not m:
        return None
    name = m.group("name").lower()
    if any(w in _NOT_NAMES for w in name.split()) or name in _NOT_NAMES:
        return None
    return name


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


# --- Reminders for a clock time or a day --------------------------------------
# "remind me tomorrow at 9 to put the bins out", "remind me at 3:30pm to call
# mum", "remind me on Friday to call the dentist", "set an alarm for 7am".
# Durations ("in 10 minutes") stay with parse_timer_request, which runs first.

import datetime as _dt

DAY_ONLY_HOUR = 9          # "remind me on Friday ..." with no time: 9 a.m.
MAX_AHEAD_DAYS = 30

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_HOUR_WORDS = {w: n for w, n in _WORD_NUMBERS.items() if isinstance(n, int) and 1 <= n <= 12}
_HOUR_RE = r"(?:\d{1,2}|" + "|".join(sorted(_HOUR_WORDS, key=len, reverse=True)) + r")"

_REMINDER_TRIGGER_RE = re.compile(r"\bremind\s+me\b|\breminder\b|\b(?:set\s+(?:an?\s+)?)?alarm\b", re.IGNORECASE)
_MINUTE_WORDS = {"oh five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
                 "forty five": 45, "forty-five": 45, "forty": 40, "fifty": 50}
_CLOCK_RE = re.compile(
    rf"\b(?:at|for|by)\s+(?P<h>{_HOUR_RE})(?:[:.](?P<m>\d{{2}})|\s+(?P<m2>[0-5]\d|"
    + "|".join(sorted(_MINUTE_WORDS, key=len, reverse=True)) + r")(?!\s*(?:minutes?|mins?)))?"
    r"\s*(?P<ampm>a\.?\s?m\.?|p\.?\s?m\.?|o'?clock)?(?![\w:])"
    r"|\b(?:at\s+)?(?P<word>noon|midday|midnight)\b",
    re.IGNORECASE)
_DAY_RE = re.compile(
    r"\b(?P<rel>today|tonight|tomorrow|this\s+(?:morning|afternoon|evening))"
    r"(?:\s+(?P<part>morning|afternoon|evening|night))?\b"
    rf"|\b(?:on\s+|next\s+|this\s+)?(?P<wd>{'|'.join(_WEEKDAYS)})s?"
    r"(?:\s+(?P<wdpart>morning|afternoon|evening|night))?\b",
    re.IGNORECASE)
_PART_HOURS = {"morning": 9, "afternoon": 15, "evening": 18, "night": 20}


def _to_hour(raw: str) -> int:
    return int(raw) if raw.isdigit() else _HOUR_WORDS[raw.lower()]


def parse_reminder_request(text: str, now: _dt.datetime = None):
    """{"due": epoch seconds, "message": str} for a dated/timed reminder, else None.

    Needs a trigger ("remind me", "reminder", "alarm") plus a clock time or a
    day.  Without am/pm the next sensible time is used ("at 9" said at 5 p.m.
    means 9 p.m.; "tonight"/"evening" mean p.m.).  Limited to 30 days ahead."""
    if not text or not _REMINDER_TRIGGER_RE.search(text):
        return None
    if _DURATION_RE.search(text) and re.search(r"\bin\s+(?:an?\s+|\d|" + "|".join(_WORD_NUMBERS) + ")", text, re.I):
        return None                                   # "in 10 minutes": a timer
    now = now or _dt.datetime.now()
    clock = _CLOCK_RE.search(text)
    day = _DAY_RE.search(text)
    if not clock and not day:
        return None

    # Which day?
    part = None
    date = now.date()
    explicit_day = False
    if day:
        explicit_day = True
        if day.group("rel"):
            rel = day.group("rel").lower()
            part = day.group("part")
            if rel == "tomorrow":
                date += _dt.timedelta(days=1)
            elif rel == "tonight":
                part = part or "night"
            elif rel.startswith("this"):
                part = rel.split()[1]
        else:
            target = _WEEKDAYS.index(day.group("wd").lower())
            ahead = (target - now.weekday()) % 7
            if day.group(0).lower().startswith("next") and ahead == 0:
                ahead = 7
            date += _dt.timedelta(days=ahead)
            part = day.group("wdpart")
    part = part.lower() if part else None

    # What time?
    if clock and clock.group("word"):
        word = clock.group("word").lower()
        hour, minute = (0, 0) if word == "midnight" else (12, 0)
        if word == "midnight" and not explicit_day:
            date += _dt.timedelta(days=1)
        candidates = [(hour, minute)]
    elif clock:
        hour = _to_hour(clock.group("h"))
        m2 = (clock.group("m2") or "").lower()
        minute = int(clock.group("m") or (_MINUTE_WORDS.get(m2) if m2 in _MINUTE_WORDS else m2) or 0)
        if hour > 23 or minute > 59:
            return None
        ampm = (clock.group("ampm") or "").lower().replace(".", "").replace(" ", "")
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        if ampm in ("am", "pm") or hour > 12 or hour == 0:
            candidates = [(hour, minute)]
        elif part in ("afternoon", "evening", "night"):
            candidates = [(hour % 12 + 12, minute)]
        elif part == "morning":
            candidates = [(hour % 12, minute)]
        elif 1 <= hour % 12 <= 6:
            candidates = [(hour % 12 + 12, minute), (hour % 12, minute)]   # "at 5": 5 p.m.
        else:
            candidates = [(hour % 12, minute), (hour % 12 + 12, minute)]
    else:
        candidates = [(_PART_HOURS.get(part, DAY_ONLY_HOUR), 0)]

    due = None
    for d in (date, date + _dt.timedelta(days=1)):
        for h, m in candidates:
            t = _dt.datetime.combine(d, _dt.time(h, m))
            if t > now + _dt.timedelta(seconds=30):
                due = t
                break
        if due or explicit_day:
            break
    if due is None or due > now + _dt.timedelta(days=MAX_AHEAD_DAYS):
        return None

    # What about?  Remove the time and day words first, so "to call mum
    # tomorrow at 5" doesn't become "Call mum tomorrow at 5!".
    rest = text
    for m in sorted([x for x in (clock, day) if x], key=lambda x: -x.start()):
        rest = rest[:m.start()] + " " + rest[m.end():]
    rest = re.sub(r"\s+", " ", rest)
    message = "Alarm!" if re.search(r"\balarm\b", text, re.I) and not re.search(r"\bremind", text, re.I) \
        else "Reminder!"
    subject = _SUBJECT_RE.search(rest)
    if subject:
        s = (subject.group("subject") or subject.group("subject2") or "").strip().rstrip("?.!,").strip()
        s = re.sub(r"\s+(?:on|at|for|by)$", "", s)
        if s and s not in {"...", "…"}:
            message = s[0].upper() + s[1:] + "!"
    return {"due": due.timestamp(), "message": message}


def _clock_words(t: _dt.datetime) -> str:
    h12 = t.hour % 12 or 12
    suffix = "a.m." if t.hour < 12 else "p.m."
    if t.hour == 12 and t.minute == 0:
        return "noon"
    if t.hour == 0 and t.minute == 0:
        return "midnight"
    return f"{h12}{':%02d' % t.minute if t.minute else ''} {suffix}"


def describe_when(due: float, now: _dt.datetime = None, message: str = None) -> str:
    """'tomorrow at 9 a.m.', 'today at 3:30 p.m.', 'on Friday at 9 a.m.'."""
    now = now or _dt.datetime.now()
    t = _dt.datetime.fromtimestamp(due)
    days = (t.date() - now.date()).days
    clock = _clock_words(t)
    at = f"at {clock}"
    if days == 0:
        when = f"tonight {at}" if t.hour >= 18 else f"today {at}"
    elif days == 1:
        when = f"tomorrow {at}"
    elif days < 7:
        when = f"on {t:%A} {at}"
    else:
        when = f"on {t:%A}, {t:%B} {t.day} {at}"
    return when


# --- Asking about timers and reminders --------------------------------------------
# "what reminders do I have?", "cancel the pasta timer", "how long left?"

_KIND_WORDS = r"(?:timers?|reminders?|alarms?)"
_LIST_RE = re.compile(
    rf"^(?:what|which)\s+(?:{_KIND_WORDS}|(?:{_KIND_WORDS}\s+and\s+{_KIND_WORDS}))\s+(?:do i have|are (?:set|running|on|there))"
    rf"|^(?:do i have|have i got|are there)\s+any\s+{_KIND_WORDS}"
    rf"|^(?:list|show|tell me)\s+(?:all\s+)?(?:my|the)\s+{_KIND_WORDS}"
    rf"|^what(?:'s| is| are)\s+(?:my|the)\s+{_KIND_WORDS}(?:\s+(?:set|for today))?$", re.I)
_CANCEL_RE = re.compile(
    r"^(?:please\s+)?(?:cancel|delete|remove|stop|clear|turn off|never mind|forget)\s+(?P<rest>.+)$", re.I)
_LEFT_RE = re.compile(
    r"^how (?:long|much time)(?: is)?(?: (?:is )?left)?(?: on| for)?(?P<rest>.*?)(?: left)?$"
    r"|^when (?:is|does|will)(?P<rest2>.+?)(?: go off| due| finish| done| ring)?$", re.I)


def _clean(text):
    t = re.sub(r"[^\w\s']", " ", (text or "").lower())
    t = re.sub(r"\b(?:hey|bmo|beemo|please|okay|ok|friend)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_reminder_query(text: str):
    """{"action": "list"} | {"action": "cancel", "target": str|None, "all": bool}
    | {"action": "left", "target": str|None} | None."""
    t = _clean(text)
    if not t or not re.search(_KIND_WORDS, t):
        return None
    if _LIST_RE.search(t):
        return {"action": "list"}
    m = _CANCEL_RE.match(t)
    if m:
        rest = m.group("rest")
        if not re.search(_KIND_WORDS, rest):
            return None
        every = bool(re.search(r"\b(?:all|every|everything)\b", rest))
        return {"action": "cancel", "target": _target(rest), "all": every}
    m = _LEFT_RE.match(t)
    if m:
        rest = m.group("rest") if m.group("rest") is not None else m.group("rest2")
        return {"action": "left", "target": _target(rest or "")}
    return None


def _target(rest):
    """The words that pick a timer/reminder: 'the pasta timer' -> 'pasta',
    'my reminder about the bins' -> 'bins'; None when it's just 'the timer'."""
    words = re.sub(rf"\b(?:the|my|a|an|all|every|that|this|of|about|to|for|on|{_KIND_WORDS})\b", " ", rest)
    words = re.sub(r"\s+", " ", words).strip()
    return words or None


def match_reminders(items: list, target):
    """Registry entries matching `target` words (name first, then message)."""
    if not target:
        return list(items)
    want = set(target.lower().split())
    by_name = [r for r in items if r.get("name") and want <= set(r["name"].lower().split())]
    if by_name:
        return by_name
    return [r for r in items if want <= set(re.findall(r"[\w']+", r.get("message", "").lower()))]
