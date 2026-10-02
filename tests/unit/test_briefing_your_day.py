""""Your day" without a calendar: repeating items, holidays, daylight, UV and
the full moon, all from settings, the date, or the forecast BMO already fetches."""
import datetime
import json
import os

import pytest

from core.briefing import holidays, script, sources

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "wttr_brantford_j1.json")


@pytest.mark.parametrize("year,name,date", [
    (2026, "Easter Sunday", "2026-04-05"), (2027, "Easter Sunday", "2027-03-28"),
    (2026, "Good Friday", "2026-04-03"), (2026, "Family Day", "2026-02-16"),
    (2026, "Victoria Day", "2026-05-18"), (2025, "Victoria Day", "2025-05-19"),
    (2026, "Civic Holiday", "2026-08-03"), (2026, "Labour Day", "2026-09-07"),
    (2026, "Thanksgiving", "2026-10-12"), (2026, "Mother's Day", "2026-05-10"),
    (2026, "Father's Day", "2026-06-21"),
])
def test_holiday_dates(year, name, date):
    assert holidays.holidays(year, "ON")[datetime.date.fromisoformat(date)] == name


def test_province_names_the_february_holiday():
    assert holidays.holidays(2026, "MB")[datetime.date(2026, 2, 16)] == "Louis Riel Day"
    assert datetime.date(2026, 2, 16) not in holidays.holidays(2026, "QC")


def test_upcoming_holidays_within_three_days():
    got = holidays.upcoming(datetime.date(2026, 10, 10), "ON")
    assert got == [{"name": "Thanksgiving", "date": "2026-10-12", "days": 2}]
    assert holidays.upcoming(datetime.date(2026, 12, 30), "ON")[-1]["name"] == "New Year's Day"


@pytest.mark.parametrize("spec,day,expected", [
    ({"days": ["tue"]}, "2026-10-06", True),
    ({"days": ["tue"]}, "2026-10-07", False),
    ({"days": ["tue"], "every_weeks": 2, "start": "2026-10-06"}, "2026-10-20", True),
    ({"days": ["tue"], "every_weeks": 2, "start": "2026-10-06"}, "2026-10-13", False),
    ({"days": ["tue"], "every_weeks": 2, "start": "2026-10-08"}, "2026-10-06", True),   # same week as start
    ({"day_of_month": 1}, "2026-11-01", True),
    ({"day_of_month": 31}, "2026-02-28", True),        # last day of a short month
    ({"day_of_month": 31}, "2026-02-27", False),
])
def test_recurs_on(spec, day, expected):
    assert sources.recurs_on(spec, datetime.date.fromisoformat(day)) is expected


def test_recurring_today_and_heads_up_tomorrow():
    specs = [{"name": "Garbage day", "days": ["tue"], "heads_up": True},
             {"name": "Piano", "days": ["mon"], "time": "16:00"}]
    assert sources.get_recurring(specs, datetime.date(2026, 10, 5)) == [   # a Monday
        {"name": "Piano", "time": "16:00", "when": "today"},
        {"name": "Garbage day", "time": None, "when": "tomorrow"}]


def test_forecast_extras_from_real_data(tmp_path):
    now = datetime.datetime(2026, 10, 1, 6, 30)
    with open(FIXTURE) as f:
        j1 = json.load(f)
    fc = sources.get_forecast("Brantford", today=now.date(), clock=lambda: now.timestamp(),
                              cache_dir=str(tmp_path), fetch=lambda loc: j1)
    assert fc["daylight"] == {"minutes": 703, "change": -3}     # 07:19-19:02, then 07:20-19:00
    assert fc["today"]["uv"] == 1 and fc["today"]["moon"] == "Waning Gibbous"
    extras = sources.get_extras({"extras": {}}, now, None, fc)
    assert extras["daylight"]["change"] == -3 and extras["uv"] == 1 and extras["full_moon"] is False


NOW = datetime.datetime(2026, 10, 10, 7, 0)    # Saturday


def your_day(**extras):
    parts = script.build_script({"extras": extras, "headlines": [{"title": "x", "source": "y"}]}, NOW)
    return parts[1] if len(parts) > 2 else None


def test_your_day_lines():
    p = your_day(sun={"sunrise": "07:29", "sunset": "18:49"}, daylight={"minutes": 680, "change": -3},
                 recurring=[{"name": "Garbage day", "time": None, "when": "today"},
                            {"name": "Recycling", "time": None, "when": "tomorrow"}],
                 holidays=[{"name": "Thanksgiving", "days": 2, "date": "2026-10-12"}],
                 uv=7, full_moon=True)
    assert p["text"] == (
        "Your day: the sun rises at 7:29 a.m. and sets at 6:49 p.m. "
        "Days are getting shorter: about 3 minutes less daylight each day. "
        "Garbage day today. Recycling tomorrow. Thanksgiving is on Monday! "
        "The UV index is high today, 7. Wear sunscreen! There's a full moon tonight!")
    assert [r["kind"] for r in p["card"]["rows"]] == ["sun", "daylight", "recurring", "recurring",
                                                       "holiday", "uv", "moon"]


@pytest.mark.parametrize("h,line", [
    ({"name": "Thanksgiving", "days": 0}, "Happy Thanksgiving!"),
    ({"name": "Halloween", "days": 1}, "Halloween is tomorrow!"),
    ({"name": "Remembrance Day", "days": 0}, "Today is Remembrance Day."),
    ({"name": "the National Day for Truth and Reconciliation", "days": 1},
     "The National Day for Truth and Reconciliation is tomorrow."),
])
def test_holiday_lines(h, line):
    assert script._holiday_line(h, NOW) == line


def test_quiet_extras_say_nothing():
    assert your_day(uv=5, daylight={"minutes": 900, "change": 0}, full_moon=False) is None


def test_greeting_follows_the_time_of_day():
    assert script.intro_line(NOW).startswith("Good morning!") and "your morning briefing" in script.intro_line(NOW)
    assert script.intro_line(NOW.replace(hour=14)).startswith("Good afternoon!")
    assert script.intro_line(NOW.replace(hour=20)) == \
        "Good evening! It's Saturday, the tenth of October. BMO has your briefing!"


def test_sun_has_set_in_the_evening():
    p = script.build_script({"extras": {"sun": {"sunrise": "07:29", "sunset": "18:49"}},
                             "headlines": [{"title": "x", "source": "y"}]}, NOW.replace(hour=20))
    assert "the sun rose at 7:29 a.m. and set at 6:49 p.m." in p[1]["text"]


def test_afternoon_sign_off_does_not_say_morning():
    p = script.build_script({"headlines": [{"title": "x", "source": "y"}]}, NOW.replace(hour=15))
    assert p[-1]["text"].startswith("That's your briefing!")


def test_calendar_events_and_weather_warnings(monkeypatch, tmp_path):
    from core.briefing import ical
    seen = {}

    def fake_events(url, day):
        seen["url"] = url
        return [{"time": None, "end": None, "title": "Mum's birthday"},
                {"time": "10:00", "end": "11:00", "title": "Dentist"}]
    monkeypatch.setattr(ical, "get_events", fake_events)
    extras = sources.get_extras({"extras": {"calendar_url": "https://cal.example/secret.ics"}}, NOW)
    assert seen["url"] == "https://cal.example/secret.ics" and len(extras["events"]) == 2
    assert sources.get_extras({"extras": {}}, NOW)["events"] == []          # no URL: no fetch

    p = your_day(events=extras["events"])
    assert p["text"] == "Your day: Today: Mum's birthday. At 10:00 a.m.: Dentist."
    assert [r["kind"] for r in p["card"]["rows"]] == ["event", "event"]

    with open(FIXTURE) as f:
        j1 = json.load(f)
    fc = sources.get_forecast("Brantford", today=datetime.date(2026, 10, 1), clock=lambda: NOW.timestamp(),
                              cache_dir=str(tmp_path), fetch=lambda loc: j1)
    assert fc["lat"] == pytest.approx(43.133)
    warning = {"id": "x", "kind": "warning", "title": "Freezing rain warning", "area": "Brant"}
    assert sources.get_warnings({}, fc, get=lambda lat, lon: [warning]) == [warning]
    assert sources.get_warnings({"alerts": False}, fc, get=lambda lat, lon: [warning]) == []
    assert sources.get_warnings({}, fc, get=lambda lat, lon: None) == []        # offline
    parts = script.build_script({"weather": sources._select_days(sources._parse_j1(j1, "Brantford", 0),
                                                                 datetime.date(2026, 10, 1)),
                                 "warnings": [warning]}, NOW)
    text = parts[0]["text"]
    warn = "Heads up! Environment Canada has a freezing rain warning for Brantford."
    assert warn in text and text.index(warn) < text.index("Right now")     # before the weather
    assert parts[0]["card"]["warnings"] == ["Freezing rain warning"]
