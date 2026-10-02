"""Turn gathered data into the briefing's parts, by fixed templates.

No LLM here: qwen3:1.7b invents details when asked for structure, and a
briefing that misreads the forecast is worse than none.  Each part is
{"key", "card", "text", "speech"}: `text` uses digits (captions, the muted
path), `speech` is what Piper reads, numbers spelled out and passed through
clean_text_for_speech like live speech.
"""
import datetime
import random
import re

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


def _warning_line(a: dict, place: str) -> str:
    title = a["title"][:1].lower() + a["title"][1:]
    article = "an" if title[:1] in "aeiou" else "a"
    return f"Heads up! Environment Canada has {article} {title} for {place}."


def _weather_part(w: dict, umbrella_min: int = UMBRELLA_RAIN, warnings=()):
    now, today, tomorrow = w["now"], w["today"], w.get("tomorrow")
    desc = now["desc"].lower()
    lines = [_warning_line(a, w["location"].title()) for a in warnings[:2]] + [f"Right now there's {desc} and it's {now['temp']} degrees." if _is_nouny(desc)
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
            "warnings": [a["title"] for a in warnings[:2]],
            "sunrise": w.get("sunrise") and _hhmm_to_display(w["sunrise"]),
            "sunset": w.get("sunset") and _hhmm_to_display(w["sunset"])}
    return {"key": "weather", "card": card, "text": " ".join(lines)}


def _headlines_part(items: list):
    # One segment per headline: audio.py renders them separately and records
    # where each starts, so the card highlights exactly the one being read.
    segments = [{"text": "Here are today's headlines.", "mark": None}]
    segments += [{"text": f"From {h['source']}: {_sentence(h['title'])}", "mark": i}
                 for i, h in enumerate(items)]
    card = {"type": "headlines",
            "items": [{"title": h["title"] + ("…" if h.get("truncated") else ""),
                       "source": h["source"], "published": h.get("published")} for h in items]}
    return {"key": "headlines", "card": card, "text": " ".join(sg["text"] for sg in segments),
            "segments": segments}


_SOLEMN = ("Remembrance Day", "Good Friday", "the National Day for Truth and Reconciliation")
UV_HIGH = 6
MAX_SPOKEN_EVENTS = 4


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _holiday_line(h: dict, now: datetime.datetime) -> str:
    name, days = h["name"], h["days"]
    solemn = name in _SOLEMN
    if days == 0:
        return f"Today is {name}." if solemn or name.startswith("the ") else f"Happy {name}!"
    when = "tomorrow" if days == 1 else f"on {(now + datetime.timedelta(days=days)):%A}"
    return f"{_cap(name)} is {when}{'.' if solemn else '!'}"


def _your_day_part(extras: dict, now: datetime.datetime):
    lines, rows = [], []
    # Sun first (the spec's order), so "Your day: the sun rose at ..." reads on.
    sun = extras.get("sun")
    if sun:
        rise, sets = _hhmm_to_display(sun["sunrise"]), _hhmm_to_display(sun["sunset"])
        hhmm = now.strftime("%H:%M")
        risen, set_ = hhmm >= sun["sunrise"], hhmm >= sun["sunset"]
        lines.append(_sentence(f"the sun {'rose' if risen else 'rises'} at {rise} "
                               f"and {'set' if set_ else 'sets'} at {sets}"))
        rows.append({"kind": "sun", "text": f"Sunrise {rise} · Sunset {sets}"})
    dl = extras.get("daylight")
    if dl and dl.get("change"):
        n = abs(dl["change"])
        lines.append(f"Days are getting {'longer' if dl['change'] > 0 else 'shorter'}: "
                     f"about {n} minute{'s' if n != 1 else ''} {'more' if dl['change'] > 0 else 'less'} "
                     f"daylight each day.")
        rows.append({"kind": "daylight", "minutes": dl["minutes"], "change": dl["change"]})
    events = extras.get("events", [])
    for i, e in enumerate(events):
        t = e.get("time") and _hhmm_to_display(e["time"])
        rows.append({"kind": "event", "time": t, "text": e["title"]})
        if i < MAX_SPOKEN_EVENTS:            # a packed work day would take minutes to read
            lines.append(f"At {t}: {_sentence(e['title'])}" if t else f"Today: {_sentence(e['title'])}")
    if len(events) > MAX_SPOKEN_EVENTS:
        n = len(events) - MAX_SPOKEN_EVENTS
        lines.append(f"And {n} more {'thing' if n == 1 else 'things'} on your calendar.")
    for r in extras.get("reminders", []):
        t = _hhmm_to_display(r["time"])
        lines.append(f"You have a reminder at {t}: {_sentence(r['message'])}")
        rows.append({"kind": "reminder", "time": t, "text": r["message"].rstrip("!.")})
    for r in extras.get("recurring", []):
        t = r.get("time") and _hhmm_to_display(r["time"])
        if r["when"] == "today":
            lines.append(f"{r['name']} at {t}." if t else f"{r['name']} today.")
        else:
            lines.append(f"{r['name']} tomorrow{f' at {t}' if t else ''}.")
        rows.append({"kind": "recurring", "when": r["when"], "time": t, "text": r["name"]})
    for c in extras.get("countdowns", []):
        if c["days"] == 0:
            said = f"{c['name']} is today!"
        elif c["days"] == 1:
            said = f"{c['name']} is tomorrow!"
        else:
            said = f"{c['days']} days until {c['name']}!"
        lines.append(said)
        rows.append({"kind": "countdown", "days": c["days"], "text": c["name"]})
    for h in extras.get("holidays", []):
        lines.append(_holiday_line(h, now))
        rows.append({"kind": "holiday", "days": h["days"], "text": _cap(h["name"]),
                     "weekday": f"{(now + datetime.timedelta(days=h['days'])):%A}"})
    uv = extras.get("uv")
    if uv is not None and uv >= UV_HIGH:
        level = "very high" if uv >= 8 else "high"
        lines.append(f"The UV index is {level} today, {uv}. Wear sunscreen!")
        rows.append({"kind": "uv", "uv": uv, "text": level})
    if extras.get("full_moon"):
        lines.append("There's a full moon tonight!")
        rows.append({"kind": "moon", "text": "Full moon tonight"})
    if not lines:
        return None
    text = "Your day: " + " ".join(lines)
    card = {"type": "your_day", "date": f"{now:%A}, {now.day} {now:%B}", "rows": rows}
    return {"key": "your_day", "card": card, "text": text}


def intro_line(now: datetime.datetime) -> str:
    """Greets by the time of day: the briefing can be asked for any time."""
    if now.hour < 12:
        hello, what = "Good morning!", "your morning briefing"
    elif now.hour < 18:
        hello, what = "Good afternoon!", "your briefing"
    else:
        hello, what = "Good evening!", "your briefing"
    return f"{hello} It's {now:%A}, the {ordinal_words(now.day)} of {now:%B}. BMO has {what}!"


def signoff_line(day: datetime.date) -> str:
    return random.Random(day.toordinal()).choice(SIGNOFFS)


def clean_fun_fact(fact):
    """The LLM's fun fact if it's usable, else None (the plain sign-off is used).

    Same spirit as pondering's checks: one or two plain sentences, no
    questions, no JSON, no markup, nothing long enough to ramble."""
    if not fact:
        return None
    fact = re.sub(r"\{.*?\}", "", fact, flags=re.S)          # stray actions
    fact = re.sub(r"[\[\]<>*_#`]", "", fact)
    fact = re.sub(r"\s+", " ", fact).strip()
    if not 20 <= len(fact) <= 240 or "?" in fact or "http" in fact.lower():
        return None
    return _sentence(fact)


def to_speech(text: str) -> str:
    from core.tts import clean_text_for_speech
    return clean_text_for_speech(speakable(text))


def build_script(data: dict, now: datetime.datetime) -> list:
    """Parts in play order; [] when there is nothing to brief on.

    A part with no data is dropped; a missing weather or news part gets one
    line in the intro so BMO doesn't just skip it silently."""
    parts, missing = [], []
    if data.get("weather"):
        parts.append(_weather_part(data["weather"], warnings=data.get("warnings") or []))
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
    lead = " ".join([intro_line(now)] + missing)
    parts[0]["text"] = f"{lead} {parts[0]['text']}"
    if parts[0].get("segments"):
        first = parts[0]["segments"][0]
        first["text"] = f"{lead} {first['text']}"
    signoff = signoff_line(now.date())
    if now.hour >= 12:
        signoff = signoff.replace("That's your morning!", "That's your briefing!")
    if data.get("fun_fact"):
        signoff = f"Here's a fun fact: {data['fun_fact']} {signoff}"
    parts.append({"key": "signoff", "card": None, "text": signoff})
    for p in parts:
        if p.get("segments"):
            for sg in p["segments"]:
                sg["speech"] = to_speech(sg["text"])
            p["speech"] = " ".join(sg["speech"] for sg in p["segments"])
        else:
            p["speech"] = to_speech(p["text"])
    return parts
