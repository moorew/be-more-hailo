"""Interactive morning-briefing setup: weather location, news feeds, window.

    python -m core.briefing --setup        # install.sh runs this too

Every answer is checked live (the location against wttr.in, each feed by
fetching and parsing it) before it's saved, and only the keys asked about
are written: anything else hand-edited in the `briefing` block is kept.
Press Enter at any prompt to keep the value shown in [brackets].
"""
import datetime
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


MAX_RECURRING = 6
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def describe_recurring(spec: dict) -> str:
    """'Garbage day (every other Tue)', 'Rent (the 1st of each month)'."""
    if spec.get("day_of_month"):
        from core.briefing.speech import ordinal_suffix
        when = f"the {ordinal_suffix(int(spec['day_of_month']))} of each month"
    else:
        days = "/".join(d.title() for d in spec.get("days", []))
        when = f"every other {days}" if int(spec.get("every_weeks", 1)) == 2 else f"every {days}"
    if spec.get("time"):
        when += f" at {spec['time']}"
    return f"{spec.get('name', '?')} ({when})"


def _ask_one_recurring(n, ask, say, today):
    name = ask(f"Repeating item {n}: what is it? (e.g. Garbage day; Enter to finish): ").strip()
    if not name:
        return None
    while True:
        raw = ask("  Which day? e.g. tue, or tue,fri, or a date like 1 for the 1st of each month: ")
        raw = raw.strip().lower()
        if raw.isdigit() and 1 <= int(raw) <= 31:
            spec = {"name": name, "day_of_month": int(raw)}
            break
        days = [d.strip()[:3] for d in re.split(r"[,\s/]+", raw) if d.strip()]
        if days and all(d in _DAYS for d in days):
            spec = {"name": name, "days": days}
            every = ask("  Every week, or every other week? [1/2]: ").strip()
            if every == "2":
                first = min(days, key=lambda d: (_DAYS.index(d) - today.weekday()) % 7)
                nxt = today + datetime.timedelta(days=(_DAYS.index(first) - today.weekday()) % 7)
                if _yes(ask(f"  Is the next one {_DAY_FULL[nxt.weekday()]} {nxt:%B} {nxt.day}? [Y/n]: ")):
                    start = nxt
                else:
                    start = nxt + datetime.timedelta(days=7)
                spec.update(every_weeks=2, start=start.isoformat())
            break
        say("  Please give day names (mon, tue, ...) or a day of the month (1-31).")
    while True:
        t = ask("  At a time? (HH:MM, Enter for none): ").strip()
        if not t:
            break
        if _TIME_RE.match(t):
            h, m = t.split(":")
            spec["time"] = f"{int(h):02d}:{m}"
            break
        say("  Please use 24-hour HH:MM, e.g. 16:30.")
    if _yes(ask("  Mention it the day before too? [y/N]: "), default=False):
        spec["heads_up"] = True
    say(f"  ok: {describe_recurring(spec)}")
    return spec


def _ask_recurring(current, ask, say, today):
    if current:
        say("Repeating items: " + "; ".join(describe_recurring(r) for r in current))
        if _yes(ask("Keep these? [Y/n]: ")):
            return current
    say("Anything that repeats, like bin day or a weekly lesson? BMO mentions it on the day.")
    items = []
    while len(items) < MAX_RECURRING:
        item = _ask_one_recurring(len(items) + 1, ask, say, today)
        if item is None:
            break
        items.append(item)
    return items


def _ask_calendar(current, ask, say, fetch_feed):
    """A calendar's secret iCal address (no sign-in), checked before saving."""
    if current:
        say("Calendar: set.")
        if _yes(ask("Keep it? [Y/n]: ")):
            return current
    say("Calendar (optional): paste its secret iCal address. In Google Calendar: Settings ->")
    say("your calendar -> Integrate calendar -> 'Secret address in iCal format'.")
    while True:
        url = ask("Calendar address (Enter to skip): ").strip()
        if not url:
            return ""
        try:
            body = fetch_feed(url)
            if b"BEGIN:VCALENDAR" not in body[:2000]:
                raise ValueError("that address didn't return a calendar")
            say(f"  ok: calendar found ({body.count(b'BEGIN:VEVENT')} events).")
            return url
        except Exception as e:
            say(f"  Couldn't read it ({str(e)[:80]}).")


def _ask_home_assistant(current, ask, say, ha_factory):
    """Home Assistant on the local network: address + long-lived token."""
    if current.get("url") and current.get("token"):
        say(f"Home Assistant: {current['url']}")
        if _yes(ask("Keep it? [Y/n]: ")):
            return current
    url = ask("Home Assistant address, e.g. http://homeassistant.local:8123 (Enter to skip): ").strip().rstrip("/")
    if not url:
        return {}
    say("  Make a token in Home Assistant: your profile -> Security -> Long-lived access tokens.")
    while True:
        token = ask("  Long-lived access token (Enter to skip): ").strip()
        if not token:
            return {}
        try:
            n = len(ha_factory(url, token).entities(refresh=True))
            say(f"  ok: BMO can see {n} lights, switches and other devices.")
            return {"url": url, "token": token}
        except Exception as e:
            say(f"  Couldn't connect ({str(e)[:80]}).")
            if not _yes(ask("  Try another token? [Y/n]: ")):
                return {}


def _default_ha(url, token):
    from core.home_assistant import HomeAssistant
    return HomeAssistant(url, token)      # entities() raises with BMO's reason on 401 / no answer


def run_setup(path: str = SETTINGS_PATH, ask=input, say=print, fetch=fetch_j1,
              fetch_feed=sources._fetch_feed, clock=time.time, ha_factory=None) -> dict:
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
        say("")
        today = datetime.date.fromtimestamp(clock())
        recurring = _ask_recurring(current["extras"].get("recurring") or [], ask, say, today)

    # Merge into the saved block, not the defaults, so only these keys change.
    block = read_settings(path).get("briefing")
    block = dict(block) if isinstance(block, dict) else {}
    block.update(answers)
    if answers["enabled"]:
        block["news"] = {**(block.get("news") if isinstance(block.get("news"), dict) else {}), "feeds": feeds}
        block["extras"] = {**(block.get("extras") if isinstance(block.get("extras"), dict) else {}),
                           "recurring": recurring}
    updates = {"briefing": block}

    say("")
    if _yes(ask("Set up the optional extras: calendar, smart home, camera? [y/N]: "), default=False):
        say("")
        extras = block.get("extras") if isinstance(block.get("extras"), dict) else {}
        url = _ask_calendar(extras.get("calendar_url") or current["extras"].get("calendar_url", ""),
                            ask, say, fetch_feed)
        block["extras"] = {**extras, "calendar_url": url}
        say("")
        saved = read_settings(path)
        updates["home_assistant"] = _ask_home_assistant(saved.get("home_assistant") or {}, ask, say,
                                                        ha_factory or _default_ha)
        say("")
        presence = dict(saved.get("presence") or {})
        presence["enabled"] = _yes(ask("Let BMO use the camera to notice when someone walks in? [Y/n]: "))
        updates["presence"] = presence
    update_settings(updates, path=path)
    say(f"\nSaved to {path}. Change it any time with: python -m core.briefing --setup")
    return block
