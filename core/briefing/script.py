"""Turn gathered data into the briefing's parts, by fixed templates.

No LLM here: qwen3:1.7b invents details when asked for structure, and a
briefing that misreads the forecast is worse than none.  Each part is
{"key", "card", "text", "speech"}: `text` uses digits (captions, the muted
path), `speech` is what Piper reads, numbers spelled out and passed through
clean_text_for_speech like live speech.
"""
import datetime
import random

from core.briefing.speech import ordinal_words, speakable, time_digits

SIGNOFFS = [
    "That's your morning! Have a great day!",
    "That's your morning! Go have an adventure!",
    "That's your morning! BMO believes in you!",
    "That's your morning! Make it a mathematical day!",
]
UMBRELLA_RAIN = 50

# wttr.in weatherCode -> the card's condition icon.
_ICONS = {
    "sun": {113},
    "partly": {116},
    "cloud": {119, 122},
    "fog": {143, 248, 260},
    "storm": {200, 386, 389, 392, 395},
    "snow": {179, 182, 185, 227, 230, 281, 284, 311, 314, 317, 320, 323, 326, 329, 332,
             335, 338, 350, 362, 365, 368, 371, 374, 377},
}


def condition_icon(code) -> str:
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "cloud"
    for icon, codes in _ICONS.items():
        if code in codes:
            return icon
    return "rain"  # 176, 263-308, 353-359: every remaining wttr.in code is wet


def _hhmm_to_display(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return time_digits(h, m)


def _sentence(s: str) -> str:
    s = s.strip()
    return s if s[-1:] in ".!?" else s + "."


# wttr.in descriptions that are things ("light rain", "patchy snow nearby")
# rather than states ("overcast", "partly cloudy"): "there's light rain".
_NOUNY = ("rain", "drizzle", "snow", "sleet", "shower", "thunder", "fog", "mist",
          "hail", "pellets", "blizzard", "storm")


def _is_nouny(desc: str) -> bool:
    return any(w in desc.lower() for w in _NOUNY)


def _weather_part(w: dict, umbrella_min: int = UMBRELLA_RAIN):
    now, today, tomorrow = w["now"], w["today"], w.get("tomorrow")
    desc = now["desc"].lower()
    lines = [f"Right now there's {desc} and it's {now['temp']} degrees." if _is_nouny(desc)
             else f"Right now it's {desc} and {now['temp']} degrees.",
             f"Today: high of {today['high']}, low of {today['low']}, {today['rain']} percent chance of rain."]
    if tomorrow:
        tdesc = tomorrow["desc"].lower()
        verb = "brings" if _is_nouny(tdesc) else "will be"
        lines.append(f"Tomorrow {verb} {tdesc}, high of {tomorrow['high']}.")
    wet = [label for label, d in (("today", today), ("tomorrow", tomorrow))
           if d and d["rain"] >= umbrella_min]
    if wet:
        lines.append(f"Take an umbrella {' and '.join(wet)}!")

    def day_card(d):
        return d and {"desc": d["desc"], "icon": condition_icon(d.get("code")),
                      "high": d["high"], "low": d["low"], "rain": d["rain"]}

    card = {"type": "weather", "location": w["location"].title(),
            "now": {"desc": now["desc"], "temp": now["temp"], "feels": now.get("feels"),
                    "icon": condition_icon(now.get("code"))},
            "today": day_card(today), "tomorrow": day_card(tomorrow),
            "umbrella": " and ".join(wet) or None,
            "sunrise": w.get("sunrise") and _hhmm_to_display(w["sunrise"]),
            "sunset": w.get("sunset") and _hhmm_to_display(w["sunset"])}
    return {"key": "weather", "card": card, "text": " ".join(lines)}


def _headlines_part(items: list):
    lines = ["Here are today's headlines."]
    lines += [f"From {h['source']}: {_sentence(h['title'])}" for h in items]
    card = {"type": "headlines",
            "items": [{"title": h["title"] + ("…" if h.get("truncated") else ""),
                       "source": h["source"], "published": h.get("published")} for h in items]}
    return {"key": "headlines", "card": card, "text": " ".join(lines)}


def _your_day_part(extras: dict, now: datetime.datetime):
    lines, rows = [], []
    sun = extras.get("sun")
    if sun:
        rise, sets = _hhmm_to_display(sun["sunrise"]), _hhmm_to_display(sun["sunset"])
        risen = now.strftime("%H:%M") >= sun["sunrise"]
        lines.append(_sentence(f"the sun {'rose' if risen else 'rises'} at {rise} and sets at {sets}"))
        rows.append({"kind": "sun", "text": f"Sunrise {rise} · Sunset {sets}"})
    for r in extras.get("reminders", []):
        t = _hhmm_to_display(r["time"])
        lines.append(f"You have a reminder at {t}: {_sentence(r['message'])}")
        rows.append({"kind": "reminder", "time": t, "text": r["message"].rstrip("!.")})
    for c in extras.get("countdowns", []):
        if c["days"] == 0:
            said = f"{c['name']} is today!"
        elif c["days"] == 1:
            said = f"{c['name']} is tomorrow!"
        else:
            said = f"{c['days']} days until {c['name']}!"
        lines.append(said)
        rows.append({"kind": "countdown", "days": c["days"], "text": c["name"]})
    if not lines:
        return None
    text = "Your day: " + " ".join(lines)
    card = {"type": "your_day", "date": f"{now:%A}, {now.day} {now:%B}", "rows": rows}
    return {"key": "your_day", "card": card, "text": text}


def intro_line(now: datetime.datetime) -> str:
    return (f"Good morning! It's {now:%A}, the {ordinal_words(now.day)} of {now:%B}. "
            f"BMO has your morning briefing!")


def signoff_line(day: datetime.date) -> str:
    return random.Random(day.toordinal()).choice(SIGNOFFS)


def to_speech(text: str) -> str:
    from core.tts import clean_text_for_speech
    return clean_text_for_speech(speakable(text))


def build_script(data: dict, now: datetime.datetime) -> list:
    """Parts in play order; [] when there is nothing to brief on.

    A part with no data is dropped; a missing weather or news part gets one
    line in the intro so BMO doesn't just skip it silently."""
    parts, missing = [], []
    if data.get("weather"):
        parts.append(_weather_part(data["weather"]))
    else:
        missing.append("BMO couldn't get the weather today.")
    if data.get("headlines"):
        parts.append(_headlines_part(data["headlines"]))
    else:
        missing.append("BMO couldn't find the news today.")
    your_day = _your_day_part(data.get("extras") or {}, now)
    if your_day:
        parts.append(your_day)
    if not parts:
        return []
    parts[0]["text"] = " ".join([intro_line(now)] + missing + [parts[0]["text"]])
    parts.append({"key": "signoff", "card": None, "text": signoff_line(now.date())})
    for p in parts:
        p["speech"] = to_speech(p["text"])
    return parts
