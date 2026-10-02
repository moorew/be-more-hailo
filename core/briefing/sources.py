"""Fetch everything the morning briefing talks about.

Each getter returns plain data (or None / [] when it has nothing) and never
raises, so one dead source only drops its own part of the briefing.
"""
import datetime
import html
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from core.briefing import holidays as holiday_calendar
from core.search import _day_stats, fetch_j1

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join("cache", "briefing")
FORECAST_MAX_AGE_S = 6 * 3600
HEADLINE_MAX_CHARS = 110
HEADLINE_MAX_AGE_H = 36
_UA = "Mozilla/5.0 (X11; Linux aarch64) BMO-morning-briefing"


# --- weather -----------------------------------------------------------------

def _sun_time(raw: str):
    """'07:19 AM' -> '07:19' (24 h), None for wttr.in's 'No sunrise'."""
    try:
        return datetime.datetime.strptime(raw.strip(), "%I:%M %p").strftime("%H:%M")
    except Exception:
        return None


def _parse_j1(data: dict, location: str, fetched_at: float) -> dict:
    now = data["current_condition"][0]
    days = []
    for day in data["weather"][:3]:
        stats = _day_stats(day)
        astro = (day.get("astronomy") or [{}])[0]
        stats["sunrise"] = _sun_time(astro.get("sunrise", ""))
        stats["sunset"] = _sun_time(astro.get("sunset", ""))
        stats["moon"] = astro.get("moon_phase")
        try:
            stats["uv"] = int(day.get("uvIndex"))
        except (TypeError, ValueError):
            stats["uv"] = None
        days.append(stats)
    area = (data.get("nearest_area") or [{}])[0]
    try:
        lat, lon = float(area["latitude"]), float(area["longitude"])
    except (KeyError, TypeError, ValueError):
        lat = lon = None
    return {
        "location": location,
        "lat": lat, "lon": lon,
        "fetched_at": fetched_at,
        "now": {"desc": now["weatherDesc"][0]["value"].strip(), "code": now.get("weatherCode"),
                "temp": int(now["temp_C"]), "feels": int(now["FeelsLikeC"])},
        "days": days,
    }


def _select_days(fc: dict, today: datetime.date):
    """Pick today/tomorrow by date, so a forecast cached late last night still lines up."""
    by_date = {d["date"]: d for d in fc["days"]}
    t = by_date.get(today.isoformat())
    if t is None:
        return None
    out = dict(fc)
    out["today"] = t
    out["tomorrow"] = by_date.get((today + datetime.timedelta(days=1)).isoformat())
    out["sunrise"], out["sunset"] = t.get("sunrise"), t.get("sunset")
    out["daylight"] = _daylight(t, out["tomorrow"])
    return out


def _minutes(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return h * 60 + m


def _daylight(today: dict, tomorrow):
    """{"minutes": today's daylight, "change": minutes gained (+) or lost (-)
    per day}, from wttr.in's own sun times for today and tomorrow."""
    try:
        length = _minutes(today["sunset"]) - _minutes(today["sunrise"])
    except Exception:
        return None
    change = None
    try:
        change = (_minutes(tomorrow["sunset"]) - _minutes(tomorrow["sunrise"])) - length
    except Exception:
        pass
    return {"minutes": length, "change": change}


def get_forecast(location: str, today: datetime.date = None, clock=time.time,
                 cache_dir: str = CACHE_DIR, fetch=fetch_j1):
    """Structured weather for the briefing, or None.

    Returns {"location", "fetched_at", "now": {desc, code, temp, feels},
    "today"/"tomorrow": {date, desc, code, high, low, rain, sunrise, sunset},
    "sunrise", "sunset"} with sun times as 24 h "HH:MM".  A successful fetch is
    cached; when wttr.in is down a cached forecast under 6 hours old is used."""
    today = today or datetime.date.fromtimestamp(clock())
    cache_path = os.path.join(cache_dir, "forecast.json")
    fc = None
    data = fetch(location)
    if data is not None:
        try:
            fc = _parse_j1(data, location, clock())
            os.makedirs(cache_dir, exist_ok=True)
            _write_json(cache_path, fc)
        except Exception as e:
            logger.warning(f"Briefing: bad wttr.in data: {e}")
            fc = None
    if fc is None:
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            age = clock() - cached["fetched_at"]
            if cached.get("location") == location and 0 <= age < FORECAST_MAX_AGE_S:
                logger.info(f"Briefing: wttr.in unavailable, using forecast cached {age / 60:.0f} min ago")
                fc = cached
        except Exception:
            pass
    return _select_days(fc, today) if fc else None


# --- headlines ---------------------------------------------------------------

_OUTLET_WORDS = r"(?:News|CBC|CTV|Global|Times|Post|Star|Globe|Mail|Press|Herald|Journal|Expositor|Today|Sun|Reuters|AP|Yahoo|MSN|Radio|TV)"
_SUFFIX_RE = re.compile(r"\s+[-–—|]\s+([^-–—|]{2,40})$")
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "at", "by",
         "with", "after", "as", "from", "says", "say", "be", "its", "it", "this", "that"}


# Techmeme-style credits: "... (Josh Butler/The Guardian)", "... (The Information)".
_CREDIT_RE = re.compile(r"\s*\((?:[^()]{0,40}/)?[^()/]{2,40}\)$")
# Places a long headline can stop and still be a sentence, best first.
_CLAUSE_TIERS = (("; ", " — "), (" after ", " amid ", " as ", " while ", " following ", " but "))


def _clause_cut(head: str, min_pos: int):
    for tier in _CLAUSE_TIERS:
        cut = max(head.rfind(b) for b in tier)
        if cut >= min_pos:
            return cut
    # A comma, but not one that leaves a dangling fragment (", a free").
    commas = [i for i in range(len(head)) if head.startswith(", ", i)]
    for n, cut in reversed(list(enumerate(commas))):
        start = commas[n - 1] + 2 if n else 0
        if cut >= min_pos and len(head[start:cut].split()) >= 3:
            return cut
    return -1


def clean_headline(title: str, source: str = None):
    """(title, truncated): unescaped, outlet suffix/credit trimmed, capped at 110 chars.

    Long titles are cut at the last clause break past half the cap ("...tax
    laws after widespread calls..." -> "...tax laws"), else at a word."""
    title = re.sub(r"\s+", " ", html.unescape(title or "")).strip()
    m = _SUFFIX_RE.search(title)
    if m:
        tail = m.group(1).strip()
        if (source and tail.lower() == source.lower()) or re.search(rf"\b{_OUTLET_WORDS}\b", tail):
            title = title[:m.start()].rstrip()
    title = _CREDIT_RE.sub("", title)
    truncated = False
    if len(title) > HEADLINE_MAX_CHARS:
        head = title[:HEADLINE_MAX_CHARS + 1]
        cut = _clause_cut(head, HEADLINE_MAX_CHARS // 2)
        title = head[:cut] if cut >= 0 else head.rsplit(" ", 1)[0]
        title = title.rstrip(" ,;:-–—")
        truncated = True
    return title, truncated


def _tokens(title: str) -> set:
    return {w for w in _WORD_RE.findall(title.lower()) if w not in _STOP}


def is_near_duplicate(a: str, b: str, threshold: float = 0.5) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name: str):
    for c in el:
        if _strip_ns(c.tag) == name:
            return (c.text or "").strip()
    return None


def _parse_date(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).timestamp()
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _item_image(item):
    for c in item:
        tag = _strip_ns(c.tag)
        if tag in ("thumbnail", "content") and c.get("url"):
            return c.get("url")
        if tag == "enclosure" and (c.get("type") or "").startswith("image") and c.get("url"):
            return c.get("url")
    return None


def parse_feed(xml_text, source: str = None) -> list:
    """RSS 2.0 or Atom -> [{title, source, published, url, image}] (raw titles)."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is not None:                                   # RSS 2.0
        items, feed_title = channel.findall("item"), channel.findtext("title")
    else:                                                     # Atom
        items = [e for e in root if _strip_ns(e.tag) == "entry"]
        feed_title = _child_text(root, "title")
    source = source or re.sub(r"\s*\|\s*", " ", (feed_title or "").strip()) or "the news"
    out = []
    for it in items:
        title = _child_text(it, "title")
        if not title:
            continue
        link = _child_text(it, "link")
        if not link:
            link = next((c.get("href") for c in it if _strip_ns(c.tag) == "link"), None)
        published = _parse_date(_child_text(it, "pubDate") or _child_text(it, "published")
                                or _child_text(it, "updated") or _child_text(it, "date"))
        out.append({"title": title, "source": source, "published": published,
                    "url": link, "image": _item_image(it)})
    return out


def _fetch_feed(url: str, timeout: float = 10) -> bytes:
    import requests
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
    resp.raise_for_status()
    return resp.content


def _ddgs_news(query: str, region: str, max_results: int) -> list:
    from core.search import DDGS
    with DDGS(timeout=10) as ddgs:
        return list(ddgs.news(query, region=region, max_results=max_results))


def _clean_source(source) -> str:
    """'Financial Post on MSN' -> 'Financial Post' (aggregator credits aren't the outlet)."""
    source = re.sub(r"\s+(?:on|via)\s+(?:MSN|Yahoo[\w ]*|Google News|Apple News)$", "", (source or "").strip())
    return source or "the news"


def _fresh(items, now_ts):
    cutoff = now_ts - HEADLINE_MAX_AGE_H * 3600
    items = [i for i in items if i["published"] is None or i["published"] >= cutoff]
    return sorted(items, key=lambda i: -(i["published"] or 0))


def _pick(streams: list, count: int) -> list:
    """Round-robin across sources (newest first in each), dropping near-duplicates."""
    picked = []
    streams = [list(s) for s in streams]
    while len(picked) < count and any(streams):
        for s in streams:
            while s:
                item = s.pop(0)
                title, truncated = clean_headline(item["title"], item["source"])
                if not title or any(is_near_duplicate(title, p["title"]) for p in picked):
                    continue
                picked.append({**item, "title": title, "truncated": truncated or item.get("truncated", False)})
                break
            if len(picked) >= count:
                break
    return picked


def get_headlines(news: dict, clock=time.time, fetch_feed=_fetch_feed, ddgs_news=_ddgs_news) -> list:
    """3-5 fresh headlines from the configured RSS feeds, else DuckDuckGo news.

    `news` is the settings block: feeds (URL strings or {"url", "name"}),
    count, region, query.  Returns [] when nothing could be fetched."""
    count = news.get("count", 4)
    now_ts = clock()
    streams = []
    for feed in news.get("feeds") or []:
        url, name = (feed, None) if isinstance(feed, str) else (feed.get("url"), feed.get("name"))
        try:
            items = _fresh(parse_feed(fetch_feed(url), name), now_ts)
            if items:
                streams.append(items)
            else:
                logger.info(f"Briefing: no fresh items in {url}")
        except Exception as e:
            logger.warning(f"Briefing: feed {url} failed: {e}")
    picked = _pick(streams, count)
    if len(picked) >= min(3, count):
        return picked
    try:
        raw = ddgs_news(news.get("query") or "Canada", news.get("region", "ca-en"), count * 3)
        items = [{"title": r.get("title", ""), "source": _clean_source(r.get("source")),
                  "published": _parse_date(r.get("date")), "url": r.get("url"),
                  "image": r.get("image")} for r in raw]
        fallback = _pick([_fresh(items, now_ts)], count)
    except Exception as e:
        logger.warning(f"Briefing: DuckDuckGo news failed: {e}")
        fallback = []
    # Keep whatever the feeds did give, topped up from the fallback.
    return _pick([picked, fallback], count) if picked else fallback


# --- your day ----------------------------------------------------------------

def _next_occurrence(spec: dict, today: datetime.date):
    raw = str(spec.get("date", ""))
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            d = datetime.date.fromisoformat(raw)
            if not spec.get("yearly"):
                return d
            month, day = d.month, d.day
        else:
            month, day = (int(x) for x in raw.split("-"))
        for year in (today.year, today.year + 1):
            try:
                d = datetime.date(year, month, day)
            except ValueError:                    # 29 Feb in a non-leap year
                d = datetime.date(year, 3, 1)
            if d >= today:
                return d
    except Exception:
        logger.warning(f"Briefing: bad countdown date {raw!r}")
    return None


def get_countdowns(specs: list, today: datetime.date, horizon_days: int = 14) -> list:
    """[{name, date, days}] for countdowns 0..14 days away, soonest first."""
    out = []
    for spec in specs or []:
        d = _next_occurrence(spec, today)
        if d is None:
            continue
        days = (d - today).days
        if 0 <= days <= horizon_days:
            out.append({"name": str(spec.get("name", "something")), "date": d.isoformat(), "days": days})
    return sorted(out, key=lambda c: c["days"])


_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def recurs_on(spec: dict, day: datetime.date) -> bool:
    """Does a repeating item fall on `day`?

    {"days": ["tue"], "every_weeks": 2, "start": "2026-10-06"}  every other Tuesday
    {"day_of_month": 1}                                        the 1st (or last day)"""
    try:
        if spec.get("day_of_month"):
            n = int(spec["day_of_month"])
            nxt = (day.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            last = (nxt - datetime.timedelta(days=1)).day
            return day.day == min(n, last)
        days = [str(d).lower()[:3] for d in spec.get("days", [])]
        if _DAY_NAMES[day.weekday()] not in days:
            return False
        every = max(1, int(spec.get("every_weeks", 1)))
        if every == 1:
            return True
        start = datetime.date.fromisoformat(spec["start"])
        weeks = ((day - datetime.timedelta(days=day.weekday()))
                 - (start - datetime.timedelta(days=start.weekday()))).days // 7
        return weeks % every == 0
    except Exception:
        logger.warning(f"Briefing: bad repeating item {spec!r}")
        return False


def get_recurring(specs: list, today: datetime.date) -> list:
    """[{name, time, when}]: items due today, plus tomorrow's when heads_up is set."""
    out = []
    for spec in specs or []:
        if recurs_on(spec, today):
            out.append({"name": str(spec.get("name", "something")), "time": spec.get("time"), "when": "today"})
        elif spec.get("heads_up") and recurs_on(spec, today + datetime.timedelta(days=1)):
            out.append({"name": str(spec.get("name", "something")), "time": spec.get("time"), "when": "tomorrow"})
    return sorted(out, key=lambda r: (r["when"] != "today", r["time"] or ""))


def get_extras(settings: dict, now: datetime.datetime, registry=None, forecast=None) -> dict:
    """Reminders due later today, repeating items, countdowns, holidays, and
    from the forecast: sun times, daylight, UV and the full moon."""
    extras = settings.get("extras", {})
    today = now.date()
    reminders = []
    if extras.get("reminders", True) and registry is not None:
        end = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time()).timestamp()
        for r in registry.due_between(now.timestamp(), end):
            t = datetime.datetime.fromtimestamp(r["due"])
            reminders.append({"time": t.strftime("%H:%M"), "message": r["message"], "kind": r.get("kind", "timer")})
    sun = None
    if extras.get("sun", True) and forecast and forecast.get("sunrise") and forecast.get("sunset"):
        sun = {"sunrise": forecast["sunrise"], "sunset": forecast["sunset"]}
    day = (forecast or {}).get("today") or {}
    daylight = forecast.get("daylight") if forecast and extras.get("daylight", True) else None
    uv = day.get("uv") if extras.get("uv", True) else None
    full_moon = extras.get("moon", True) and (day.get("moon") or "").lower() == "full moon"
    events = []
    if extras.get("calendar_url"):
        from core.briefing import ical
        events = ical.get_events(extras["calendar_url"], today)
    return {"reminders": reminders,
            "events": events,
            "recurring": get_recurring(extras.get("recurring"), today),
            "countdowns": get_countdowns(extras.get("countdowns"), today),
            "holidays": holiday_calendar.upcoming(today, extras.get("province", "ON"))
            if extras.get("holidays", True) else [],
            "sun": sun, "daylight": daylight, "uv": uv, "full_moon": bool(full_moon)}


def get_warnings(settings: dict, forecast, get=None) -> list:
    """Active Environment Canada alerts for the forecast's location ([] if none,
    off, outside Canada or offline)."""
    if not settings.get("alerts", True) or not forecast or forecast.get("lat") is None:
        return []
    if get is None:
        from core.weather_alerts import get_alerts as get
    return get(forecast["lat"], forecast["lon"]) or []


def gather(settings: dict, now: datetime.datetime, registry=None, **fetchers) -> dict:
    """Everything build_script needs.  `fetchers` lets tests swap the network calls."""
    forecast = get_forecast(settings["location"], today=now.date(),
                            **{k: v for k, v in fetchers.items() if k in ("fetch", "cache_dir", "clock")})
    headlines = get_headlines(settings["news"],
                              **{k: v for k, v in fetchers.items() if k in ("fetch_feed", "ddgs_news", "clock")})
    return {"date": now.date().isoformat(), "weather": forecast, "headlines": headlines,
            "warnings": get_warnings(settings, forecast, fetchers.get("get_alerts")),
            "extras": get_extras(settings, now, registry, forecast)}


def _write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)
