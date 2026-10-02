"""`python -m core.briefing --setup` (run by install.sh): location, up to 3
feeds, window.  Answers are checked before saving, and nothing else in
settings.json is touched."""
import json

from core.briefing.setup import MAX_FEEDS, PRESETS, run_setup

RSS = (b'<?xml version="1.0"?><rss><channel><title>Local Paper</title><item><title>Bridge reopens</title>'
       b'<pubDate>Thu, 01 Oct 2026 06:00:00 EDT</pubDate></item></channel></rss>')
NOW_TS = 1790849000.0   # 2026-10-01 morning


def j1_for(location, timeout=None):
    if location == "Nowhereville":
        return None
    return {"nearest_area": [{"areaName": [{"value": location}], "region": [{"value": "Ontario"}],
                              "country": [{"value": "Canada"}]}],
            "current_condition": [{"temp_C": "12"}]}


def feed(url):
    if "broken" in url:
        raise ConnectionError("offline")
    return RSS


def run(tmp_path, answers, existing=None):
    path = tmp_path / "settings.json"
    if existing is not None:
        path.write_text(json.dumps(existing))
    said = []
    answers = iter(answers)
    block = run_setup(str(path), ask=lambda prompt: next(answers), say=said.append,
                      fetch=j1_for, fetch_feed=feed, clock=lambda: NOW_TS)
    return block, json.loads(path.read_text()), "\n".join(said)


def test_choose_location_and_three_feeds(tmp_path):
    block, saved, said = run(tmp_path, [
        "",                                    # enabled (default yes)
        "Hamilton",                            # location
        "n",                                   # don't keep default feeds
        "1", "https://paper.example/rss", "The Local Paper",   # preset, URL + spoken name
        "7",                                   # third feed: Techmeme preset
        "06:30", "",                           # window start, keep end
        "",                                    # no repeating items
        "",                                    # no optional extras
    ], existing={"volume": 0.4, "briefing": {"chime": False, "news": {"count": 5}}})
    assert saved["volume"] == 0.4                                   # other settings kept
    assert saved["briefing"]["chime"] is False and saved["briefing"]["news"]["count"] == 5
    assert saved["briefing"]["location"] == "Hamilton"
    assert saved["briefing"]["window"] == ["06:30", "11:00"]
    assert saved["briefing"]["news"]["feeds"] == [
        {"url": PRESETS[0][1], "name": PRESETS[0][0]},
        {"url": "https://paper.example/rss", "name": "The Local Paper"},
        {"url": PRESETS[6][1], "name": "Techmeme"}]
    assert len(block["news"]["feeds"]) == MAX_FEEDS
    assert "Hamilton, Ontario, Canada (12°C now)" in said
    assert 'e.g. "Bridge reopens"' in said


def test_enter_everywhere_keeps_the_defaults(tmp_path):
    _, saved, _ = run(tmp_path, ["", "", "", "", "", "", ""])
    assert saved["briefing"]["location"] == "Brantford"
    assert [f["name"] for f in saved["briefing"]["news"]["feeds"]] == [
        "CBC News", "the Brantford Expositor", "Techmeme"]


def test_bad_answers_are_asked_again(tmp_path):
    _, saved, said = run(tmp_path, [
        "y",
        "Nowhereville", "n", "Paris",           # unknown place -> re-ask
        "n",
        "https://broken.example/rss",           # unreadable feed -> re-ask
        "cbc",                                  # neither number nor URL
        "99",                                   # not a list number
        "2", "2",                               # duplicate
        "",                                     # finish with one feed
        "7am", "07:00", "06:00", "12:00",       # bad time; end before start
        "",                                     # no repeating items
        "",                                     # no optional extras
    ])
    assert saved["briefing"]["location"] == "Paris"
    assert [f["url"] for f in saved["briefing"]["news"]["feeds"]] == [PRESETS[1][1]]
    assert saved["briefing"]["window"] == ["07:00", "12:00"]
    assert "Couldn't read that feed" in said and "Already added." in said
    assert "The end has to be later than the start." in said


def test_turning_it_off_only_saves_enabled(tmp_path):
    _, saved, _ = run(tmp_path, ["n", ""], existing={"volume": 0.4})
    assert saved == {"volume": 0.4, "briefing": {"enabled": False}}


def test_repeating_items(tmp_path):
    # NOW_TS is Thursday 1 October 2026.
    _, saved, said = run(tmp_path, [
        "", "", "", "", "",                    # enabled, location, feeds, window
        "Garbage day", "tue", "2", "n", "", "y",   # every other Tue, not the 6th: from the 13th
        "Rent", "1", "",  "",                  # day of month, no time, no heads-up
        "Piano", "wed,sat", "1", "4pm", "16:00", "",
        "",                                    # finish
        "",                                    # no optional extras
    ], existing={"briefing": {"extras": {"sun": False}}})
    extras = saved["briefing"]["extras"]
    assert extras["sun"] is False                                        # other extras kept
    assert extras["recurring"] == [
        {"name": "Garbage day", "days": ["tue"], "every_weeks": 2, "start": "2026-10-13", "heads_up": True},
        {"name": "Rent", "day_of_month": 1},
        {"name": "Piano", "days": ["wed", "sat"], "time": "16:00"}]
    assert "ok: Garbage day (every other Tue)" in said and "ok: Rent (the 1st of each month)" in said
    assert "Please use 24-hour HH:MM" in said
    # Running it again offers to keep them.
    _, saved2, said2 = run(tmp_path, ["", "", "", "", "", "", ""], existing=saved)
    assert saved2["briefing"]["extras"]["recurring"] == extras["recurring"]
    assert "Repeating items: Garbage day (every other Tue)" in said2


def test_optional_extras_calendar_home_assistant_and_camera(tmp_path):
    path = tmp_path / "settings.json"
    said = []

    def fetch(url):
        if "broken" in url:
            raise ConnectionError("offline")
        if "notacal" in url:
            return b"<html>sign in</html>"
        return b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nEND:VEVENT\nEND:VCALENDAR"

    class FakeHA:
        def __init__(self, url, token):
            self.token = token

        def entities(self, refresh=False):
            if self.token != "good":
                raise RuntimeError("Home Assistant didn't accept BMO's token.")
            return [{"entity_id": "light.kitchen"}, {"entity_id": "switch.fan"}]

    answers = iter(["", "", "", "", "", "",                 # enabled .. no repeating items
                    "y",                                    # optional extras
                    "https://broken.example/cal.ics", "https://notacal.example/x",
                    "https://cal.example/secret.ics",
                    "http://homeassistant.local:8123/", "bad", "y", "good",
                    "n"])                                   # no camera presence
    run_setup(str(path), ask=lambda p: next(answers), say=said.append, fetch=j1_for,
              fetch_feed=lambda url: fetch(url) if "cal" in url or "notacal" in url else RSS,
              clock=lambda: NOW_TS, ha_factory=FakeHA)
    saved = json.loads(path.read_text())
    assert saved["briefing"]["extras"]["calendar_url"] == "https://cal.example/secret.ics"
    assert saved["home_assistant"] == {"url": "http://homeassistant.local:8123", "token": "good"}
    assert saved["presence"] == {"enabled": False}
    text = "\n".join(said)
    assert "Couldn't read it" in text and "calendar found (1 events)" in text
    assert "Couldn't connect (Home Assistant didn't accept BMO's token.)" in text
    assert "BMO can see 2 lights" in text
