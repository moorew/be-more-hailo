"""Digits -> words for the briefing's Piper text.

Cards show digits; Piper is handed words so numbers are always read whole
("nineteen degrees", "minus five", "seven twelve a.m.").  Compound numbers use
spaces, not hyphens: clean_text_for_speech strips every "-", which would turn
"seventy-six" into "seventysix".
"""
import re

_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
          "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
          "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = [(10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"), (100, "hundred")]

_ORDINAL_IRREGULAR = {"one": "first", "two": "second", "three": "third", "five": "fifth",
                      "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def number_to_words(n: int) -> str:
    """5 -> 'five', -5 -> 'minus five', 76 -> 'seventy six', 1200 -> 'one thousand two hundred'."""
    n = int(n)
    if n < 0:
        return "minus " + number_to_words(-n)
    if n < 20:
        return _UNITS[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _UNITS[n % 10])
    for value, name in _SCALES:
        if n >= value:
            head, rest = divmod(n, value)
            words = f"{number_to_words(head)} {name}"
            if rest:
                words += (" and " if rest < 100 and value > 100 else " ") + number_to_words(rest)
            return words
    return str(n)  # unreachable


def ordinal_words(n: int) -> str:
    """30 -> 'thirtieth', 21 -> 'twenty first', 2 -> 'second'."""
    words = number_to_words(n).split(" ")
    last = words[-1]
    if last in _ORDINAL_IRREGULAR:
        last = _ORDINAL_IRREGULAR[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return " ".join(words[:-1] + [last])


def ordinal_suffix(n: int) -> str:
    """30 -> '30th' (card text)."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def time_digits(hour: int, minute: int) -> str:
    """(7, 12) -> '7:12 a.m.' (card text)."""
    h12 = hour % 12 or 12
    return f"{h12}:{minute:02d} {'a.m.' if hour < 12 else 'p.m.'}"


def _time_words(h: int, m: int, ampm: str) -> str:
    if m == 0:
        mins = ""
    elif m < 10:
        mins = " oh " + number_to_words(m)
    else:
        mins = " " + number_to_words(m)
    return f"{number_to_words(h)}{mins} {ampm.lower()}"


_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([ap]\.m\.)", re.IGNORECASE)
_ORDINAL_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b")
_PERCENT_RE = re.compile(r"(?<![\w.])(-?\d+)\s*%")
_DEGREE_RE = re.compile(r"(-?\d+)\s*°C?")
_MONEY_RE = re.compile(r"\$(\d[\d,]*)(?:\.(\d{2}))?")
_DECIMAL_RE = re.compile(r"(?<![\w.])(-?)(\d+)\.(\d+)\b")
# A leading minus only counts at a word start ("-5", " -5"), not in "Crew-13".
_INT_RE = re.compile(r"(?<![\w.,])(-?)(\d{1,3}(?:,\d{3})+|\d+)\b(?![.,]\d)")


def _int_words(sign: str, digits: str) -> str:
    n = int(digits.replace(",", ""))
    return number_to_words(-n if sign else n)


def _int_sub(m: re.Match) -> str:
    sign, digits = m.group(1), m.group(2)
    # Leave plain 4-digit years for clean_text_for_speech's year reader
    # ("2026" -> "twenty twenty six", not "two thousand and twenty six").
    if not sign and "," not in digits and len(digits) == 4 and 1000 <= int(digits) <= 2099:
        return digits
    return _int_words(sign, digits)


def speakable(text: str) -> str:
    """Spell out every number in `text` the way BMO should say it."""
    # clean_text_for_speech deletes every "-" and every non-Latin dash, so
    # "Kitchener-Waterloo" / "Crew-13" would run together and "a — b" lose its pause.
    text = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z\d])", " ", text)
    text = re.sub(r"\s*[–—]\s*", ", ", text)
    text = _TIME_RE.sub(lambda m: _time_words(int(m.group(1)), int(m.group(2)), m.group(3)), text)
    text = _ORDINAL_RE.sub(lambda m: ordinal_words(int(m.group(1))), text)
    text = _MONEY_RE.sub(lambda m: _int_words("", m.group(1)) + " dollars"
                         + (f" {number_to_words(int(m.group(2)))} cents" if m.group(2) and int(m.group(2)) else ""), text)
    text = _PERCENT_RE.sub(lambda m: number_to_words(int(m.group(1))) + " percent", text)
    text = _DEGREE_RE.sub(lambda m: number_to_words(int(m.group(1))) + " degrees", text)
    text = _DECIMAL_RE.sub(lambda m: ("minus " if m.group(1) else "") + number_to_words(int(m.group(2)))
                           + " point " + " ".join(_UNITS[int(c)] for c in m.group(3)), text)
    text = _INT_RE.sub(_int_sub, text)
    return text
