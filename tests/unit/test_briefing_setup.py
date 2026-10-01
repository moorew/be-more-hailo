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
    _, saved, _ = run(tmp_path, ["", "", "", "", ""])
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
    ])
    assert saved["briefing"]["location"] == "Paris"
    assert [f["url"] for f in saved["briefing"]["news"]["feeds"]] == [PRESETS[1][1]]
    assert saved["briefing"]["window"] == ["07:00", "12:00"]
    assert "Couldn't read that feed" in said and "Already added." in said
    assert "The end has to be later than the start." in said


def test_turning_it_off_only_saves_enabled(tmp_path):
    _, saved, _ = run(tmp_path, ["n"], existing={"volume": 0.4})
    assert saved == {"volume": 0.4, "briefing": {"enabled": False}}
