"""Interactive morning-briefing setup: weather location, news feeds, window.

    python -m core.briefing --setup        # install.sh runs this too

Every answer is checked live (the location against wttr.in, each feed by
fetching and parsing it) before it's saved, and only the keys asked about
are written: anything else hand-edited in the `briefing` block is kept.
Press Enter at any prompt to keep the value shown in [brackets].
"""
import re
import time

from core.briefing import sources
from core.briefing.settings import MAX_FEEDS, SETTINGS_PATH, load_briefing_settings, read_settings, update_settings
from core.search import fetch_j1

# Offered by number so nobody has to hunt for RSS URLs.  Feeds that answer
# from the Pi and carry fresh items (checked 2026-10-01).
PRESETS = [
    ("CBC News", "https://www.cbc.ca/webfeed/rss/rss-canada"),
    ("CBC News top stories", "https://www.cbc.ca/webfeed/rss/rss-topstories"),
    ("Global News", "https://globalnews.ca/canada/feed/"),
    ("the Brantford Expositor", "https://www.brantfordexpositor.ca/feed"),
    ("CBC Hamilton", "https://www.cbc.ca/webfeed/rss/rss-canada-hamiltonnews"),
    ("CBC Kitchener-Waterloo", "https://www.cbc.ca/webfeed/rss/rss-canada-kitchenerwaterloo"),
    ("Techmeme", "https://www.techmeme.com/feed.xml"),
    ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
]
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _feed_name(feed):
    return feed.get("name") or feed.get("url") if isinstance(feed, dict) else feed


def check_location(location: str, fetch=fetch_j1):
    """'Brantford, Ontario, Canada (12°C now)', or None if wttr.in doesn't know it."""
    data = fetch(location, timeout=15)
    try:
        area = data["nearest_area"][0]
        parts = [area[k][0]["value"] for k in ("areaName", "region", "country") if area.get(k)]
        return f"{', '.join(p for p in parts if p)} ({data['current_condition'][0]['temp_C']}°C now)"
    except Exception:
        return None


def check_feed(url: str, name: str = None, fetch_feed=sources._fetch_feed, clock=time.time):
    """(feed title, fresh item count, newest title).  Raises if it can't be read."""
    items = sources.parse_feed(fetch_feed(url), name)
    fresh = sources._fresh(items, clock())
    title = items[0]["source"] if items else (name or url)
    newest = sources.clean_headline(fresh[0]["title"], title)[0] if fresh else None
    return title, len(fresh), newest


def _yes(answer: str, default=True) -> bool:
    answer = answer.strip().lower()
    return default if not answer else answer.startswith("y")


def _ask_location(current, ask, say, fetch):
    while True:
        location = ask(f"Weather location (town or city) [{current}]: ").strip() or current
        say("  checking wttr.in...")
        found = check_location(location, fetch)
        if found:
            say(f"  ok: {found}")
            return location
        say(f"  wttr.in couldn't find {location!r} (or is offline).")
        if _yes(ask("  Use it anyway? [y/N]: "), default=False):
            return location


def _ask_feed(n, ask, say, fetch_feed, clock):
    """One feed as {"url", "name"}, or None when the user is done."""
    while True:
        raw = ask(f"Feed {n}: a number from the list, an RSS URL, or Enter to finish: ").strip()
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(PRESETS):
            name, url = PRESETS[int(raw) - 1]
        elif re.match(r"https?://", raw):
            name, url = None, raw
        else:
            say("  That's not a list number or a URL starting with http:// or https://.")
            continue
        say("  checking feed...")
        try:
            title, fresh, newest = check_feed(url, name, fetch_feed, clock)
        except Exception as e:
            say(f"  Couldn't read that feed ({type(e).__name__}: {str(e)[:80]}).")
            continue
        if not fresh:
            say(f"  {title} works but has nothing from the last {sources.HEADLINE_MAX_AGE_H} hours.")
            if not _yes(ask("  Add it anyway? [y/N]: "), default=False):
                continue
        else:
            say(f'  ok: {fresh} recent headlines, e.g. "{newest}"')
        if name is None:
            name = ask(f'  What should BMO call it? ("From ...") [{title}]: ').strip() or title
        return {"url": url, "name": name}


def _ask_feeds(current, ask, say, fetch_feed, clock):
    if current:
        say("BMO reads headlines from: " + ", ".join(_feed_name(f) for f in current))
        if _yes(ask("Keep these feeds? [Y/n]: ")):
            return current
    say(f"Choose up to {MAX_FEEDS} news feeds; BMO takes turns reading the newest from each.")
    for i, (name, url) in enumerate(PRESETS, 1):
        say(f"  {i}) {name:<26} {url}")
    feeds = []
    while len(feeds) < MAX_FEEDS:
        feed = _ask_feed(len(feeds) + 1, ask, say, fetch_feed, clock)
        if feed is None:
            break
        if any(f["url"] == feed["url"] for f in feeds):
            say("  Already added.")
            continue
        feeds.append(feed)
    if not feeds:
        say("  No feeds chosen: BMO will use DuckDuckGo news instead.")
    return feeds


def _ask_time(prompt, current, ask, say):
    while True:
        raw = ask(f"{prompt} [{current}]: ").strip() or current
        m = _TIME_RE.match(raw)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        say("  Please use 24-hour HH:MM, e.g. 07:00.")


def run_setup(path: str = SETTINGS_PATH, ask=input, say=print, fetch=fetch_j1,
              fetch_feed=sources._fetch_feed, clock=time.time) -> dict:
    """Ask, check, and save.  Returns the briefing block as written."""
    current = load_briefing_settings(path)
    say("\nBMO's morning briefing: weather, headlines and your day, each morning.")
    say("Press Enter to keep the value in [brackets].\n")
    answers = {"enabled": _yes(ask(f"Turn on the morning briefing? [{'Y/n' if current['enabled'] else 'y/N'}]: "),
                               default=current["enabled"])}
    if answers["enabled"]:
        answers["location"] = _ask_location(current["location"], ask, say, fetch)
        say("")
        feeds = _ask_feeds(current["news"]["feeds"], ask, say, fetch_feed, clock)
        say("")
        start = _ask_time("Show the briefing from", current["window"][0], ask, say)
        end = _ask_time("until", current["window"][1], ask, say)
        while end <= start:
            say("  The end has to be later than the start.")
            end = _ask_time("until", current["window"][1], ask, say)
        answers["window"] = [start, end]

    # Merge into the saved block, not the defaults, so only these keys change.
    block = read_settings(path).get("briefing")
    block = dict(block) if isinstance(block, dict) else {}
    block.update(answers)
    if answers["enabled"]:
        block["news"] = {**(block.get("news") if isinstance(block.get("news"), dict) else {}), "feeds": feeds}
    update_settings({"briefing": block}, path=path)
    say(f"\nSaved to {path}. Change it any time with: python -m core.briefing --setup")
    return block
