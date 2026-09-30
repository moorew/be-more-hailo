"""Weather must come back as one short line that includes tomorrow.

The old wttr.in v2 table was ~18k chars: unreadable for a 1.7B model and big
enough to overflow hailo-ollama's context, which silently drops the request.
With current conditions only, "what's it doing tomorrow?" got an invented answer.
"""
import requests

from core.search import _weather_location, get_weather, search_web


def _hour(time, desc, rain):
    return {"time": str(time), "weatherDesc": [{"value": desc}], "chanceofrain": str(rain)}


def _day(date, hi, lo, desc, rain):
    return {"date": date, "maxtempC": str(hi), "mintempC": str(lo),
            "hourly": [_hour(t, desc, rain if t == 1500 else 0) for t in range(0, 2400, 300)]}


J1 = {
    "current_condition": [{"weatherDesc": [{"value": "Overcast "}], "temp_C": "19", "FeelsLikeC": "17"}],
    "weather": [_day("2026-09-30", 23, 13, "Overcast", 23),
                _day("2026-10-01", 20, 15, "Light rain", 76),
                _day("2026-10-02", 18, 9, "Sunny", 10)],
}


class _Resp:
    status_code = 200

    def json(self):
        return J1


def _fake_get(calls):
    def get(url, timeout=None):
        calls.append(url)
        return _Resp()
    return get


def test_weather_includes_today_and_tomorrow(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", _fake_get(calls))
    out = get_weather("what's the weather doing tomorrow?")
    assert out == (
        "Weather in Brantford: now Overcast, 19°C (feels like 17°C). "
        "Today: Overcast, high 23°C, low 13°C, 23% chance of rain. "
        "Tomorrow: Light rain, high 20°C, low 15°C, 76% chance of rain. "
        "Friday: Sunny, high 18°C, low 9°C, 10% chance of rain."
    )
    assert "\n" not in out and len(out) < 400
    assert "format=j1" in calls[0] and "&m" in calls[0]


def test_search_web_uses_weather_lookup(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", _fake_get(calls))
    assert search_web("what's the weather like").startswith("Weather in Brantford: now")


def test_weather_failure_returns_none(monkeypatch):
    def boom(url, timeout=None):
        raise requests.exceptions.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", boom)
    assert get_weather("weather?") is None


def test_location_parsing():
    assert _weather_location("what's the weather in new york") == "new york"
    assert _weather_location("do i need an umbrella in toronto?") == "toronto"
    assert _weather_location("weather in paris tomorrow") == "paris"
    # times and vague places are not locations
    assert _weather_location("is it raining in the morning") == "Brantford"
    assert _weather_location("how cold is it outside") == "Brantford"
    assert _weather_location("will it rain in an hour") == "Brantford"
