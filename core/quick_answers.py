"""Instant answers for simple factual questions: time, date, countdowns, sums, units.

qwen3:1.7b takes 5-10 s to answer "what time is it" and regularly gets "12
times 7" wrong.  These questions have exactly one right answer that a few lines
of Python can produce instantly, so — like timers (core/timers.py) — we answer
them before the LLM is ever asked.

Being wrong here is worse than being slow: a false positive hijacks a real
conversation.  So every matcher must account for the *whole* utterance (after
stripping filler like "hey BMO" or "can you tell me"); anything left over that
we don't understand means `answer()` returns None and the LLM handles it.
"""
import datetime
import math
import re

from core.briefing.holidays import holidays

# ---------------------------------------------------------------- normalising

_LEAD_FILLER_RE = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|yo)\s+bmo\b|bmo\b|please\b|so\b|um+\b|uh+\b"
    r"|(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:tell\s+me|say|work\s+out|figure\s+out)\b"
    r"|(?:can|could|would|will)\s+you\s+(?:please\s+)?(?=convert\b|calculate\b)"
    r"|do\s+you\s+know|tell\s+me\b(?!\s+about)|i\s+(?:want|need)\s+to\s+know|i\s+wonder)[\s,]*"
)
_TRAIL_FILLER_RE = re.compile(r"[\s,]+(?:please|bmo|for\s+me|buddy|friend)$")


def _normalise(text: str) -> str:
    t = (text or "").lower().replace("’", "'").strip()
    t = re.sub(r"[?!.,;:]+$", "", t).strip()
    t = re.sub(r"\bwhat'?s\b", "what is", t)
    t = re.sub(r"\bhow'?s\b", "how is", t)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)        # 1,000 -> 1000
    t = re.sub(r",(?!\d)", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    while True:
        new = _TRAIL_FILLER_RE.sub("", _LEAD_FILLER_RE.sub("", t)).strip(" ,")
        if new == t:
            return t
        t = new


# ----------------------------------------------------------------- formatting

def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _fmt(x: float) -> str:
    """Speakable number: integers without .0, else at most 2 decimals (3 sig figs if tiny)."""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    r = round(x, 2) if abs(x) >= 0.01 else float(f"{x:.3g}")
    return f"{r:.10f}".rstrip("0").rstrip(".") if r != int(r) else str(int(r))


def _is_rounded(x: float) -> bool:
    return abs(float(_fmt(x)) - x) > 1e-9


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


# ----------------------------------------------------------------- time & date

_TIME_RE = re.compile(
    r"(?:what(?: is)? (?:the )?(?:current )?time(?: is it| it is)?|(?:the )?(?:current )?time"
    r"|what time is it (?:right )?now|got the time|have you got the time)(?: (?:right )?now)?"
)
_DATE_RE = re.compile(
    r"what(?: is)? (?:the date|the date today|today's date|the date of today|date is it(?: today)?"
    r"|day is it(?: today)?|day it is(?: today)?|day is today|is today|day of the week is it(?: today)?)"
    r"|(?:the |today's )?date(?: today)?"
)
_YEAR_RE = re.compile(r"what(?: is the)? year is it(?: now)?|what year it is|what is the year")
_MONTH_RE = re.compile(r"what(?: is the)? month is it(?: now)?|what month it is|what is the month")


def _time_reply(now: datetime.datetime) -> str:
    hour = now.hour % 12 or 12
    ampm = "a.m." if now.hour < 12 else "p.m."
    return f"It's {hour}:{now.minute:02d} {ampm}" if now.minute else f"It's {hour} {ampm}"


def _date_words(d: datetime.date) -> str:
    return f"{d:%B} {_ordinal(d.day)}"


# ------------------------------------------------------------------ days until

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9

_ORDINAL_WORDS = {w: i for i, w in enumerate(
    ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
     "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
     "eighteenth", "nineteenth", "twentieth"], 1)}
for _i, _w in enumerate(["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth"], 1):
    _ORDINAL_WORDS[f"twenty {_w}"] = _ORDINAL_WORDS[f"twenty-{_w}"] = 20 + _i
_ORDINAL_WORDS.update({"thirtieth": 30, "thirty first": 31, "thirty-first": 31})

# Spoken name -> exact name in holidays().  Every holiday's own name (minus
# "the"/apostrophes) is accepted too; see _holiday_aliases().
_HOLIDAY_ALIASES = {
    "christmas": "Christmas Day", "xmas": "Christmas Day",
    "new year": "New Year's Day", "new years": "New Year's Day", "the new year": "New Year's Day",
    "easter": "Easter Sunday", "valentines": "Valentine's Day", "valentine": "Valentine's Day",
    "st patricks": "St. Patrick's Day", "saint patricks day": "St. Patrick's Day",
    "st patricks day": "St. Patrick's Day", "mothers day": "Mother's Day", "fathers day": "Father's Day",
    "labor day": "Labour Day", "thanksgiving day": "Thanksgiving",
    "truth and reconciliation day": "the National Day for Truth and Reconciliation",
}
# How BMO says them back.
_HOLIDAY_SPOKEN = {"Christmas Day": "Christmas", "Easter Sunday": "Easter"}


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"['.]", "", s.lower())).strip()


def _holiday_aliases(year: int) -> dict:
    aliases = {_key(re.sub(r"^the ", "", n)): n for n in holidays(year, "ON").values()}
    aliases.update({_key(k): v for k, v in _HOLIDAY_ALIASES.items()})
    return aliases


def _next_holiday(name: str, today: datetime.date):
    for year in (today.year, today.year + 1):
        for d, n in holidays(year, "ON").items():
            if n == name and d >= today:
                return d
    return None


def _parse_day_month(target: str):
    """(month, day) from "october 31st", "oct 31", "the 31st of october", "december twenty fifth"."""
    months = "|".join(sorted(_MONTHS, key=len, reverse=True))
    day = r"(\d{1,2})(?:st|nd|rd|th)?|(" + "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True)) + ")"
    m = re.fullmatch(rf"(?:the )?(?:{day}) (?:of )?({months})", target)
    if m:
        d, dw, mon = m.groups()
    else:
        m = re.fullmatch(rf"({months}) (?:the )?(?:{day})", target)
        if not m:
            return None
        mon, d, dw = m.groups()
    return _MONTHS[mon], int(d) if d else _ORDINAL_WORDS[dw]


def _next_date(month: int, day: int, today: datetime.date):
    for year in range(today.year, today.year + 9):      # 9 years covers Feb 29
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            if not (month == 2 and day == 29):
                return None
            continue
        if d >= today:
            return d
    return None


_UNTIL_RE = re.compile(
    r"(?:how many (?:more )?(?:days|sleeps)|how long|days|sleeps)(?: is it| are there| left| do we have| have we got)?"
    r" (?:until|till|til|to|before|'til) (?P<target>.+?)(?: is| arrives| comes)?"
)


def _until_reply(text: str, today: datetime.date):
    m = _UNTIL_RE.fullmatch(text)
    if not m:
        return None
    target = m.group("target").strip()
    md = _parse_day_month(target)
    if md:
        when = _next_date(*md, today)
        if when is None:
            return None
        spoken = _date_words(when)
    else:
        name = _holiday_aliases(today.year).get(_key(re.sub(r"^the ", "", target)))
        if name is None:
            name = _holiday_aliases(today.year).get(_key(target))
        if name is None:
            return None
        when, spoken = _next_holiday(name, today), _HOLIDAY_SPOKEN.get(name, name)
        if when is None:
            return None
    days = (when - today).days
    if days == 0:
        return f"It's {spoken} today!"
    if days == 1:
        return _cap(f"{spoken} is tomorrow!")
    return _cap(f"{spoken} is in {days} days!")


# ------------------------------------------------------------------ arithmetic

_ONES = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
     "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"])}
_TENS = {w: 10 * i for i, w in enumerate(
    ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"], 2)}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}

# Longest phrases first so "to the power of" wins over "to".
_OPERATOR_WORDS = [
    ("raised to the power of", "^"), ("to the power of", "^"), ("multiplied by", "*"),
    ("divided by", "/"), ("percent of", "%"), ("per cent of", "%"), ("% of", "%"),
    ("the square root of", "sqrt"), ("square root of", "sqrt"), ("squared", "sq"), ("cubed", "cube"),
    ("plus", "+"), ("add", "+"), ("minus", "-"), ("take away", "-"), ("times", "*"), ("x", "*"),
    ("over", "/"), ("negative", "neg"),
    ("+", "+"), ("-", "-"), ("*", "*"), ("×", "*"), ("/", "/"), ("÷", "/"), ("^", "^"),
]
_SPOKEN_OP = {"+": "plus", "-": "minus", "*": "times", "/": "divided by", "^": "to the power of",
              "%": "percent of", "sqrt": "the square root of", "sq": "squared", "cube": "cubed",
              "neg": "negative"}

_MATH_RE = re.compile(
    r"(?:what|how much) (?P<expr2>.+?) (?:is|equals|makes)"            # "(tell me) what 12 times 12 is"
    r"|(?:what is|what does|how much is|calculate|compute|work out|solve)? ?(?P<expr>.+?)"
    r"(?: equals?| equal to| make| makes)?"
)


class _MathError(Exception):
    pass


def _tokenise(expr: str):
    """[float | operator str], or None if any word isn't a number or operator."""
    expr = re.sub(r"(?<=\d)-(?=\d)", " - ", expr)                   # "7-10"
    expr = re.sub(r"([+*/^×÷()])", r" \1 ", expr)
    expr = re.sub(r"(?<![\w.])-(?=\s)", " - ", expr)
    words = expr.replace("%", " % ").split()
    ops = sorted(_OPERATOR_WORDS, key=lambda p: -len(p[0].split()))
    tokens, i = [], 0
    while i < len(words):
        for phrase, op in ops:
            parts = phrase.split()
            if words[i:i + len(parts)] == parts:
                tokens.append(op)
                i += len(parts)
                break
        else:
            n, used = _number_at(words, i)
            if used == 0:
                return None
            tokens.append(n)
            i += used
    return tokens


def _number_at(words, i):
    """Parse a number (digits or words like "one hundred and twelve") at words[i]."""
    w = words[i]
    if re.fullmatch(r"-?\d+(?:\.\d+)?|-?\.\d+", w):
        return float(w), 1
    total, current, used = 0, 0, 0
    while i + used < len(words):
        w = words[i + used]
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w in ("a", "an") and used == 0 and i + 1 < len(words) and words[i + 1] in _SCALES:
            current = 1
        elif w in _SCALES and (current or used):
            current = (current or 1) * _SCALES[w]
            if _SCALES[w] >= 1000:
                total, current = total + current, 0
        elif w == "and" and used and words[i + used - 1] in _SCALES and i + used + 1 < len(words) and (
                words[i + used + 1] in _ONES or words[i + used + 1] in _TENS):
            pass
        else:
            break
        used += 1
    return float(total + current), used


class _Parser:
    """expr := term (+|- term)* ; term := power (*|/|% power)* ; power := unary (^ power)?
    unary := (-|neg) unary | postfix ; postfix := atom (sq|cube)* ; atom := number | sqrt unary"""

    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        v = self.expr()
        if self.peek() is not None:
            raise _MathError
        return v

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            v = v + self.term() if self.take() == "+" else v - self.term()
        return v

    def term(self):
        v = self.power()
        while self.peek() in ("*", "/", "%"):
            op, rhs = self.take(), self.power()
            if op == "/" and rhs == 0:
                raise ZeroDivisionError
            v = v * rhs if op == "*" else v / rhs if op == "/" else v / 100 * rhs
        return v

    def power(self):
        base = self.unary()
        if self.peek() == "^":
            self.take()
            exp = self.power()
            if abs(exp) > 64 or abs(base) > 1e6:
                raise _MathError
            if base == 0 and exp < 0:
                raise ZeroDivisionError
            base = float(base) ** exp
            if isinstance(base, complex):
                raise _MathError
        return base

    def unary(self):
        if self.peek() in ("-", "neg"):
            self.take()
            return -self.unary()
        v = self.atom()
        while self.peek() in ("sq", "cube"):
            v = v ** (2 if self.take() == "sq" else 3)
        return v

    def atom(self):
        tok = self.take()
        if isinstance(tok, float):
            return tok
        if tok == "sqrt":
            v = self.unary()
            if v < 0:
                raise _MathError
            return math.sqrt(v)
        raise _MathError


def _spoken_expr(tokens) -> str:
    return " ".join(_fmt(t) if isinstance(t, float) else _SPOKEN_OP[t] for t in tokens)


def _math_reply(text: str):
    m = _MATH_RE.fullmatch(text)
    if not m:
        return None
    tokens = _tokenise(m.group("expr") or m.group("expr2"))
    if not tokens or not any(isinstance(t, str) and t != "neg" for t in tokens):
        return None                                   # "what is 5", "what is love"
    if sum(isinstance(t, float) for t in tokens) > 6:
        return None
    try:
        value = _Parser(tokens).parse()
    except ZeroDivisionError:
        return "Even BMO can't divide by zero!"
    except (_MathError, OverflowError):
        return None
    if math.isinf(value) or math.isnan(value) or abs(value) >= 1e15:
        return None
    return _cap(f"{_spoken_expr(tokens)} is {'about ' if _is_rounded(value) else ''}{_fmt(value)}.")


# ---------------------------------------------------------------------- units

# (dimension, size in base unit [mm, g, ml], singular, plural, aliases)
# Volumes use Canadian metric kitchen measures: cup = 250 ml, tbsp = 15 ml,
# tsp = 5 ml (what Canadian recipes and measuring cups mean).  Fluid ounces,
# pints, quarts and gallons are US customary.
_UNITS = [
    ("length", 1, "millimetre", "millimetres", "mm millimetre millimetres millimeter millimeters"),
    ("length", 10, "centimetre", "centimetres", "cm cms centimetre centimetres centimeter centimeters"),
    ("length", 1000, "metre", "metres", "m metre metres meter meters"),
    ("length", 1_000_000, "kilometre", "kilometres", "km kms kilometre kilometres kilometer kilometers klicks"),
    ("length", 25.4, "inch", "inches", "inch inches"),
    ("length", 304.8, "foot", "feet", "ft foot feet"),
    ("length", 914.4, "yard", "yards", "yd yds yard yards"),
    ("length", 1_609_344, "mile", "miles", "mi mile miles"),
    ("mass", 1, "gram", "grams", "g gram grams gramme grammes"),
    ("mass", 1000, "kilogram", "kilograms", "kg kgs kilo kilos kilogram kilograms kilogramme kilogrammes"),
    ("mass", 28.349523125, "ounce", "ounces", "oz ounce ounces"),
    ("mass", 453.59237, "pound", "pounds", "lb lbs pound pounds"),
    ("volume", 1, "millilitre", "millilitres", "ml mls millilitre millilitres milliliter milliliters"),
    ("volume", 1000, "litre", "litres", "l litre litres liter liters"),
    ("volume", 5, "teaspoon", "teaspoons", "tsp tsps teaspoon teaspoons"),
    ("volume", 15, "tablespoon", "tablespoons", "tbsp tbsps tablespoon tablespoons"),
    ("volume", 250, "cup", "cups", "cup cups"),
    ("volume", 29.5735, "fluid ounce", "fluid ounces",
     "fl oz|fluid ounce|fluid ounces|fl ounce|fl ounces|oz|ounce|ounces"),
    ("volume", 473.176, "pint", "pints", "pint pints pt"),
    ("volume", 946.353, "quart", "quarts", "quart quarts qt"),
    ("volume", 3785.41, "gallon", "gallons", "gallon gallons gal"),
    ("temp", "C", "degree Celsius", "degrees Celsius", "c celsius centigrade"),
    ("temp", "F", "degree Fahrenheit", "degrees Fahrenheit", "f fahrenheit"),
    ("temp", "K", "kelvin", "kelvin", "k kelvin kelvins"),
]
_ALIASES: dict = {}
for _u in _UNITS:
    for _a in (_u[4].split("|") if "|" in _u[4] else _u[4].split()):
        _ALIASES.setdefault(_a, []).append(_u)
_UNIT_ALT = "|".join(re.escape(a) for a in sorted(_ALIASES, key=len, reverse=True))
_QTY_WORDS = {**_ONES, **_TENS, "a": 1, "an": 1, "a hundred": 100, "a thousand": 1000}
_QTY = r"-?\d+(?:\.\d+)?|" + "|".join(sorted(_QTY_WORDS, key=len, reverse=True))
_DEG = r"(?:degrees? )?"

_CONVERT_RES = [
    re.compile(rf"(?:what is |how much is |convert |change )?(?P<q>{_QTY}) {_DEG}(?P<src>{_UNIT_ALT})"
               rf" (?:in|to|into|in to|as|is how many|equals how many) {_DEG}(?P<dst>{_UNIT_ALT})"),
    re.compile(rf"how many {_DEG}(?P<dst>{_UNIT_ALT})"
               rf" (?:are there in|are there in a|is there in|are in|is in|in|is|are|per|make|makes|make up|to)"
               rf" (?:(?P<q>{_QTY}) )?{_DEG}(?P<src>{_UNIT_ALT})"),
]


def _to_celsius(v, scale):
    return v if scale == "C" else (v - 32) * 5 / 9 if scale == "F" else v - 273.15


def _from_celsius(c, scale):
    return c if scale == "C" else c * 9 / 5 + 32 if scale == "F" else c + 273.15


def _unit_reply(text: str):
    for rx in _CONVERT_RES:
        m = rx.fullmatch(text)
        if m:
            break
    else:
        return None
    q = m.group("q") or "1"
    qty = float(q) if re.fullmatch(r"-?[\d.]+", q) else float(_QTY_WORDS[q])
    pairs = [(s, d) for s in _ALIASES[m.group("src")] for d in _ALIASES[m.group("dst")] if s[0] == d[0]]
    if not pairs:
        return None
    src, dst = pairs[0]
    if src[0] == "temp":
        value = _from_celsius(_to_celsius(qty, src[1]), dst[1])
        rounded = round(value)
        about = "about " if abs(rounded - value) > 1e-9 else ""
        dst_name = dst[2] if abs(rounded) == 1 else dst[3]
        src_name = src[2] if abs(qty) == 1 else src[3]
        return f"{_fmt(qty)} {src_name} is {about}{rounded} {dst_name}."
    if qty < 0:
        return None
    value = qty * src[1] / dst[1]
    about = "about " if _is_rounded(value) else ""
    if _fmt(value) == "0":
        return None
    src_name = src[2] if qty == 1 else src[3]
    dst_name = dst[2] if _fmt(value) == "1" else dst[3]
    return f"{_fmt(qty)} {src_name} is {about}{_fmt(value)} {dst_name}."


# ------------------------------------------------------------------------ API

def answer(text: str, now: datetime.datetime | None = None):
    """A short spoken reply if `text` is clearly a time/date/countdown/maths/units question, else None."""
    t = _normalise(text)
    if not t:
        return None
    now = now or datetime.datetime.now()
    if _TIME_RE.fullmatch(t):
        return _time_reply(now)
    if _DATE_RE.fullmatch(t):
        return f"It's {now:%A}, {_date_words(now.date())}."
    if _YEAR_RE.fullmatch(t):
        return f"It's {now.year}."
    if _MONTH_RE.fullmatch(t):
        return f"It's {now:%B}."
    return _until_reply(t, now.date()) or _unit_reply(t) or _math_reply(t)
