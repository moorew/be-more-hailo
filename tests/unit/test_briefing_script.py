"""The briefing script: fixed templates, numbers read whole, nothing invented.

The golden text is the example script in SPEC.md, built from the weather
fixture in test_weather.py.
"""
import datetime

import pytest

from core.briefing import script, sources
from core.briefing.speech import number_to_words, ordinal_words, speakable
from core.search import _day_stats
from tests.unit.test_weather import J1

NOW = datetime.datetime(2026, 9, 30, 7, 0)   # a Wednesday, before the 07:19 sunrise


def weather(j1=J1, location="Brantford"):
    fc = sources._parse_j1(j1, location, NOW.timestamp())
    return sources._select_days(fc, NOW.date())


HEADLINES = [
    {"title": "Ontario minimum wage just increased by 35 cents", "source": "CBC News", "published": None},
    {"title": "Is the bridge reopening?", "source": "Brantford Expositor", "published": None},
    {"title": "Crew-13 astronauts on their way to the ISS", "source": "CBC News", "published": None},
]
EXTRAS = {"sun": {"sunrise": "07:19", "sunset": "19:02"},
          "reminders": [{"time": "09:30", "message": "Stir the soup!", "kind": "timer"}],
          "countdowns": []}


def test_golden_script():
    data = {"weather": weather(), "headlines": HEADLINES, "extras": EXTRAS}
    parts = script.build_script(data, NOW)
    assert [p["key"] for p in parts] == ["weather", "headlines", "your_day", "signoff"]
    assert "\n".join(p["text"] for p in parts) == (
        "Good morning! It's Wednesday, the thirtieth of September. BMO has your morning briefing! "
        "Right now it's overcast and 19 degrees. Today: high of 23, low of 13, 23 percent chance of rain. "
        "Tomorrow brings light rain, high of 20. Take an umbrella tomorrow!\n"
        "Here are today's headlines. From CBC News: Ontario minimum wage just increased by 35 cents. "
        "From Brantford Expositor: Is the bridge reopening? "
        "From CBC News: Crew-13 astronauts on their way to the ISS.\n"
        "Your day: the sun rises at 7:19 a.m. and sets at 7:02 p.m. You have a reminder at 9:30 a.m.: Stir the soup!\n"
        "That's your morning! Have a great day!")


def test_speech_spells_numbers_out_and_is_cleaned_for_piper():
    parts = script.build_script({"weather": weather(), "headlines": HEADLINES, "extras": EXTRAS}, NOW)
    w, h, day = (p["speech"] for p in parts[:3])
    assert "beemo has your morning briefing" in w                       # pronunciations applied
    assert "nineteen degrees" in w and "twenty three percent chance of rain" in w
    assert "high of twenty, " in w or "high of twenty." in w
    assert "thirty five cents" in h and "Crew thirteen" in h
    assert "seven nineteen a.m." in day and "seven oh two p.m." in day and "nine thirty a.m." in day
    assert not any(c.isdigit() for p in parts for c in p["speech"])
    assert not any("-" in p["speech"] for p in parts)


def test_card_data_uses_digits():
    card = script.build_script({"weather": weather(), "headlines": [], "extras": {}}, NOW)[0]["card"]
    assert card["now"]["temp"] == 19 and card["today"]["high"] == 23 and card["tomorrow"]["rain"] == 76
    assert card["umbrella"] == "tomorrow" and card["location"] == "Brantford"


def _j1_with_rain(today_rain, tomorrow_rain):
    j = {**J1, "weather": [dict(d) for d in J1["weather"]]}
    for day, rain in zip(j["weather"], (today_rain, tomorrow_rain)):
        day["hourly"] = [dict(h, chanceofrain=str(rain)) for h in day["hourly"]]
    return j


@pytest.mark.parametrize("today,tomorrow,line", [
    (49, 49, None),
    (50, 10, "Take an umbrella today!"),
    (10, 50, "Take an umbrella tomorrow!"),
    (80, 90, "Take an umbrella today and tomorrow!"),
])
def test_umbrella_line_at_50_percent(today, tomorrow, line):
    text = script.build_script({"weather": weather(_j1_with_rain(today, tomorrow))}, NOW)[0]["text"]
    if line:
        assert text.endswith(line)
    else:
        assert "umbrella" not in text


def test_nouny_conditions_read_naturally():
    j = {**J1, "current_condition": [{"weatherDesc": [{"value": "Patchy rain nearby"}], "temp_C": "-5",
                                      "FeelsLikeC": "-9"}]}
    j["weather"] = [J1["weather"][0], {**J1["weather"][2], "date": "2026-10-01"}]
    w = script.build_script({"weather": weather(j)}, NOW)[0]
    assert "Right now there's patchy rain nearby and it's -5 degrees." in w["text"]
    assert "Tomorrow will be sunny, high of 18." in w["text"]
    assert "minus five degrees" in w["speech"]


def test_missing_parts_are_dropped_with_one_line():
    parts = script.build_script({"weather": weather(), "headlines": [], "extras": {}}, NOW)
    assert [p["key"] for p in parts] == ["weather", "signoff"]
    assert "BMO couldn't find the news today." in parts[0]["text"]

    parts = script.build_script({"weather": None, "headlines": HEADLINES, "extras": {}}, NOW)
    assert [p["key"] for p in parts] == ["headlines", "signoff"]
    assert parts[0]["text"].startswith("Good morning! It's Wednesday")
    assert "BMO couldn't get the weather today." in parts[0]["text"]


def test_nothing_to_say_gives_no_parts():
    assert script.build_script({"weather": None, "headlines": [], "extras": {}}, NOW) == []


def test_sun_tense_follows_the_clock():
    later = NOW.replace(hour=8)
    text = script.build_script({"extras": {"sun": EXTRAS["sun"]}, "headlines": HEADLINES}, later)[1]["text"]
    assert "the sun rose at 7:19 a.m." in text


# --- countdowns ---------------------------------------------------------------

def test_countdowns_yearly_dates_and_14_day_limit():
    today = datetime.date(2026, 12, 25)
    specs = [{"name": "New Year", "date": "01-01", "yearly": True},          # wraps into next year
             {"name": "Trip", "date": "2027-01-08"},                         # exactly 14 days
             {"name": "Too far", "date": "2027-01-09"},
             {"name": "Christmas", "date": "12-25", "yearly": True},
             {"name": "Past one-off", "date": "2026-12-20"}]
    got = [(c["name"], c["days"]) for c in sources.get_countdowns(specs, today)]
    assert got == [("Christmas", 0), ("New Year", 7), ("Trip", 14)]


def test_countdown_lines():
    extras = {"countdowns": [{"name": "Mum's birthday", "days": 0}, {"name": "The trip", "days": 1},
                             {"name": "Halloween", "days": 12}]}
    text = script.build_script({"extras": extras}, NOW)[0]["text"]
    assert "Mum's birthday is today! The trip is tomorrow! 12 days until Halloween!" in text


# --- speech helpers -----------------------------------------------------------

@pytest.mark.parametrize("n,words", [(0, "zero"), (13, "thirteen"), (76, "seventy six"), (100, "one hundred"),
                                     (105, "one hundred five"), (2005, "two thousand and five"), (-12, "minus twelve")])
def test_number_to_words(n, words):
    assert number_to_words(n) == words


@pytest.mark.parametrize("n,words", [(1, "first"), (2, "second"), (3, "third"), (12, "twelfth"),
                                     (20, "twentieth"), (22, "twenty second"), (30, "thirtieth")])
def test_ordinals(n, words):
    assert ordinal_words(n) == words


@pytest.mark.parametrize("text,said", [
    ("7:12 a.m.", "seven twelve a.m."), ("7:05 p.m.", "seven oh five p.m."), ("11:00 a.m.", "eleven a.m."),
    ("76%", "seventy six percent"), ("$10B pledge", "ten billion dollars pledge"), ("$5.50", "five dollars fifty cents"), ("-5 degrees", "minus five degrees"), ("1,200 jobs", "one thousand two hundred jobs"),
    ("in 2026", "in 2026"),     # left for clean_text_for_speech's year reader
    ("Kitchener-Waterloo", "Kitchener Waterloo"), ("Leafs win — again", "Leafs win, again"),
])
def test_speakable(text, said):
    assert speakable(text) == said


def test_day_stats_shared_with_chat_weather():
    assert _day_stats(J1["weather"][1])["rain"] == 76
