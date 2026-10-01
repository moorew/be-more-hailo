"""What the morning briefing fetches: weather, headlines and "your day".

Every source can fail on its own; a dead one must only drop its own part.
Network calls are faked, as in test_weather.py.
"""
import datetime
import json
import os

import pytest

from core.briefing import sources

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "wttr_brantford_j1.json")
NOW = datetime.datetime(2026, 10, 1, 6, 30)
NOW_TS = NOW.timestamp()


def j1():
    with open(FIXTURE) as f:
        return json.load(f)


# --- weather -----------------------------------------------------------------

def test_forecast_from_real_j1_includes_sun_times(tmp_path):
    fc = sources.get_forecast("Brantford", today=NOW.date(), clock=lambda: NOW_TS,
                              cache_dir=str(tmp_path), fetch=lambda loc: j1())
    assert fc["today"]["date"] == "2026-10-01" and fc["tomorrow"]["date"] == "2026-10-02"
    assert (fc["sunrise"], fc["sunset"]) == ("07:19", "19:02")
    assert fc["now"]["temp"] == 20 and fc["now"]["desc"] == "Patchy rain nearby"
    assert fc["today"]["high"] == 23 and fc["today"]["low"] == 17 and fc["today"]["rain"] == 39
    assert fc["tomorrow"]["desc"] == "Overcast" and fc["tomorrow"]["high"] == 17
    assert fc["today"]["code"] is not None


def test_cached_forecast_is_used_when_offline_if_under_6_hours(tmp_path):
    def get(**kw):
        return sources.get_forecast("Brantford", today=NOW.date(), cache_dir=str(tmp_path), **kw)

    def offline(loc):
        return None

    get(clock=lambda: NOW_TS, fetch=lambda loc: j1())
    assert get(clock=lambda: NOW_TS + 5 * 3600, fetch=offline)["now"]["temp"] == 20
    assert get(clock=lambda: NOW_TS + 7 * 3600, fetch=offline) is None


def test_cached_forecast_for_another_place_is_ignored(tmp_path):
    sources.get_forecast("Brantford", today=NOW.date(), clock=lambda: NOW_TS,
                         cache_dir=str(tmp_path), fetch=lambda loc: j1())
    assert sources.get_forecast("Paris", today=NOW.date(), clock=lambda: NOW_TS,
                                cache_dir=str(tmp_path), fetch=lambda loc: None) is None


def test_forecast_cached_last_night_lines_up_with_today(tmp_path):
    # Fetched for 2026-10-01; read on the 2nd, "today" must be the 2nd's forecast.
    sources.get_forecast("Brantford", today=NOW.date(), clock=lambda: NOW_TS,
                         cache_dir=str(tmp_path), fetch=lambda loc: j1())
    fc = sources.get_forecast("Brantford", today=datetime.date(2026, 10, 2), clock=lambda: NOW_TS + 3600,
                              cache_dir=str(tmp_path), fetch=lambda loc: None)
    assert fc["today"]["date"] == "2026-10-02" and fc["tomorrow"]["date"] == "2026-10-03"


# --- headlines -----------------------------------------------------------------

def rss(*items, title="CBC | Canada News"):
    body = "".join(
        f"<item><title><![CDATA[{t}]]></title><link>https://x/{i}</link>"
        f"<pubDate>{d}</pubDate></item>" for i, (t, d) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{body}</channel></rss>'.encode()


FRESH = "Thu, 01 Oct 2026 06:00:00 EDT"
OLDER = "Thu, 01 Oct 2026 04:00:00 EDT"
STALE = "Sun, 27 Sep 2026 06:00:00 EDT"


def test_rss_parsing_uses_feed_title_as_source_and_skips_stale():
    feed = rss(("Old story", STALE), ("Minimum wage up 35 cents", FRESH))
    items = sources._fresh(sources.parse_feed(feed), NOW_TS)
    assert [i["title"] for i in items] == ["Minimum wage up 35 cents"]
    assert items[0]["source"] == "CBC Canada News" and items[0]["url"] == "https://x/1"


def test_atom_feeds_parse():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Local</title>
      <entry><title>Bridge reopens</title><link href="https://l/1"/><updated>2026-10-01T09:00:00Z</updated></entry></feed>"""
    [item] = sources.parse_feed(atom, source="Brantford Expositor")
    assert item["title"] == "Bridge reopens" and item["url"] == "https://l/1" and item["published"]


@pytest.mark.parametrize("raw,source,expected", [
    ("Rates cut again - CBC News", None, "Rates cut again"),
    ("Rates cut again | Brantford Expositor", "Brantford Expositor", "Rates cut again"),
    ("Rates cut again &amp; again", None, "Rates cut again & again"),
    ("Leafs win - again", None, "Leafs win - again"),          # not an outlet: kept
])
def test_headline_cleanup(raw, source, expected):
    assert sources.clean_headline(raw, source)[0] == expected


def test_headline_capped_at_110_on_a_word_boundary():
    title, truncated = sources.clean_headline("word " * 40)
    assert truncated and len(title) <= 110 and title.endswith("word")


def test_near_duplicates_are_dropped():
    national = rss(("Ontario minimum wage rises 35 cents on Thursday", FRESH), ("Pipeline approved", OLDER))
    local = rss(("Minimum wage in Ontario rises 35 cents Thursday", FRESH), ("Bridge reopens", OLDER),
                title="Expositor")
    feeds = {"n": national, "l": local}
    out = sources.get_headlines({"feeds": ["n", "l"], "count": 3}, clock=lambda: NOW_TS,
                                fetch_feed=feeds.__getitem__, ddgs_news=_no_ddgs)
    assert [h["title"] for h in out] == ["Ontario minimum wage rises 35 cents on Thursday",
                                         "Bridge reopens", "Pipeline approved"]


def test_feeds_are_read_round_robin():
    a = rss(("A1", FRESH), ("A2", OLDER), ("A3", OLDER), title="A")
    b = rss(("B1 local", FRESH), ("B2 local", OLDER), title="B")
    out = sources.get_headlines({"feeds": [{"url": "a", "name": "Alpha"}, "b"], "count": 4},
                                clock=lambda: NOW_TS, fetch_feed={"a": a, "b": b}.__getitem__,
                                ddgs_news=_no_ddgs)
    assert [(h["source"], h["title"]) for h in out] == [
        ("Alpha", "A1"), ("B", "B1 local"), ("Alpha", "A2"), ("B", "B2 local")]


def _no_ddgs(*a):
    raise AssertionError("fallback should not run")


def _ddgs(query, region, n):
    assert region == "ca-en"
    return [{"title": f"Fallback {i} - CTV News", "source": "CTV News on MSN",
             "date": "2026-10-01T09:00:00+00:00", "url": f"u{i}"} for i in range(n)]


def test_ddgs_fallback_when_rss_fails():
    def broken(url):
        raise ConnectionError("offline")
    out = sources.get_headlines({"feeds": ["x"], "count": 3, "region": "ca-en"}, clock=lambda: NOW_TS,
                                fetch_feed=broken, ddgs_news=_ddgs)
    assert [h["title"] for h in out] == ["Fallback 0", "Fallback 1", "Fallback 2"]
    assert out[0]["source"] == "CTV News"


def test_nothing_online_gives_empty_parts(tmp_path):
    def broken(*a, **k):
        raise ConnectionError("offline")
    settings = {"location": "Brantford", "news": {"feeds": ["x"], "count": 4},
                "extras": {"reminders": True, "sun": True, "countdowns": []}}
    data = sources.gather(settings, NOW, registry=None, fetch=lambda loc: None, cache_dir=str(tmp_path),
                          clock=lambda: NOW_TS, fetch_feed=broken, ddgs_news=broken)
    assert data["weather"] is None and data["headlines"] == []
    assert data["extras"] == {"reminders": [], "recurring": [], "countdowns": [], "holidays": [],
                              "sun": None, "daylight": None, "uv": None, "full_moon": False}


# --- your day -----------------------------------------------------------------

class FakeRegistry:
    def __init__(self, items):
        self.items = items

    def due_between(self, start, end):
        return [r for r in self.items if start <= r["due"] < end]


def test_extras_lists_only_reminders_due_later_today():
    def at(h, m, d=1):
        return datetime.datetime(2026, 10, d, h, m).timestamp()

    reg = FakeRegistry([{"due": at(5, 0), "message": "already gone"},
                        {"due": at(9, 30), "message": "Stir the soup!"},
                        {"due": at(9, 0, d=2), "message": "tomorrow"}])
    extras = sources.get_extras({"extras": {}}, NOW, reg, {"sunrise": "07:19", "sunset": "19:02"})
    assert extras["reminders"] == [{"time": "09:30", "message": "Stir the soup!", "kind": "timer"}]
    assert extras["sun"] == {"sunrise": "07:19", "sunset": "19:02"}


def test_extras_respect_flags():
    reg = FakeRegistry([{"due": NOW_TS + 60, "message": "x"}])
    extras = sources.get_extras({"extras": {"reminders": False, "sun": False}}, NOW, reg,
                                {"sunrise": "07:19", "sunset": "19:02"})
    assert extras["reminders"] == [] and extras["sun"] is None


def test_techmeme_credits_trimmed_and_long_titles_cut_at_a_clause():
    title, truncated = sources.clean_headline(
        "DoorDash pulls support for a GOP bill that would have limited DC's ability to write its own tax "
        "laws after widespread calls for locals to boycott the service (Martin Austermuhle/The Washington Sun)")
    assert title == "DoorDash pulls support for a GOP bill that would have limited DC's ability to write its own tax laws"
    assert truncated
    title, _ = sources.clean_headline(
        "Strands Labs, AWS's experimental agent-development project, unveils Strands Decider 2B, a free, "
        "open-source Jev competitor fine-tuned from an Alibaba Qwen base (Carl Franzen/VentureBeat)")
    assert title == "Strands Labs, AWS's experimental agent-development project, unveils Strands Decider 2B"
    assert sources.clean_headline("SoftBank invests (again) (The Information)")[0] == "SoftBank invests (again)"
