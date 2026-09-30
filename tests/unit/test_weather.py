"""Weather must come back as one short line.

The old wttr.in v2 table was ~18k chars: unreadable for a 1.7B model and big
enough to overflow hailo-ollama's context, which silently drops the request.
"""
import requests

from core.search import search_web


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


def _fake_get(calls, text="Overcast , +17°C (feels like +15°C), wind ↑16km/h, humidity 74%\n"):
    def get(url, timeout=None):
        calls.append(url)
        return _Resp(text)
    return get


def test_weather_is_one_compact_line(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", _fake_get(calls))
    out = search_web("what's the weather like today?")
    assert out == "Weather in Brantford right now: Overcast , +17°C (feels like +15°C), wind ↑16km/h, humidity 74%"
    assert "\n" not in out
    assert "format=v2" not in calls[0] and "&m" in calls[0]


def test_weather_location_from_question(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", _fake_get(calls))
    out = search_web("what's the weather in new york")
    assert "/new+york?" in calls[0]
    assert out.startswith("Weather in New York right now:")
