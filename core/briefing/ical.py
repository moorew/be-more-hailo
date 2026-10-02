"""Today's events from a calendar's secret iCal address, for "Your day".

Google Calendar (and most others) can publish a private "secret address in
iCal format": a plain .ics URL that anyone holding it can read, so there is no
OAuth to set up.  This module fetches that file and answers one question:
what is on for `day`?

Only the part of RFC 5545 that real calendars use is handled: folded lines,
escaped text, all-day / UTC / floating / TZID times, RRULE (DAILY, WEEKLY,
MONTHLY, YEARLY with INTERVAL, COUNT, UNTIL, BYDAY incl. ordinals like 2MO or
-1FR, BYMONTHDAY, BYMONTH, BYSETPOS, WKST), RDATE, EXDATE and RECURRENCE-ID
overrides.  Recurrences are never walked from the beginning of time: rules
without COUNT jump straight to the period containing `day`, and COUNT rules
stop as soon as they pass it.

Choices worth knowing:
* A timed event that began before `day` and is still running gets
  "time": None (it sorts with the all-day events, i.e. "ongoing") rather than
  a start time that belongs to yesterday; its "end" is set if it ends today.
* "end" is None for all-day events and for events running to/past midnight.
* TRANSP:TRANSPARENT ("show me as free") events are kept - they are still on
  the calendar.  STATUS:CANCELLED events, and cancelled overrides of a single
  occurrence, are dropped.
* The secret URL is never logged: it is a credential.
"""
import datetime
import logging
import os
import re
import time
import zoneinfo

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join("cache", "briefing")
CACHE_NAME = "calendar.ics"
CACHE_MAX_AGE_S = 24 * 3600
TITLE_MAX_CHARS = 80
_UA = "Mozilla/5.0 (X11; Linux aarch64) BMO-morning-briefing"
_MAX_PERIODS = 100_000          # hard stop for one rule's expansion (COUNT rules walk from DTSTART)
_DAY = datetime.timedelta(days=1)
_UTC = datetime.timezone.utc
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
# Outlook/Exchange feeds name zones the Windows way; map the common ones.
_WINDOWS_TZ = {
    "Eastern Standard Time": "America/Toronto",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Edmonton",
    "Pacific Standard Time": "America/Vancouver",
    "Atlantic Standard Time": "America/Halifax",
    "Newfoundland Standard Time": "America/St_Johns",
    "GMT Standard Time": "Europe/London",
    "UTC": "UTC",
}

_DT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?$")
_DUR_RE = re.compile(r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_BYDAY_RE = re.compile(r"^([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)$")


# --- time zones --------------------------------------------------------------

def _local_tz():
    """The system zone: $TZ, then /etc/localtime's zoneinfo name, then a fixed offset."""
    name = os.environ.get("TZ", "").lstrip(":")
    if name:
        try:
            return zoneinfo.ZoneInfo(name)
        except Exception:
            pass
    try:
        path = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in path:
            return zoneinfo.ZoneInfo(path.split("zoneinfo/", 1)[1])
    except Exception:
        pass
    return datetime.datetime.now().astimezone().tzinfo


def _resolve_tz(tz):
    if isinstance(tz, datetime.tzinfo):
        return tz
    if tz:
        try:
            return zoneinfo.ZoneInfo(tz)
        except Exception:
            logger.warning(f"Briefing: unknown time zone {tz!r}, using the system one")
    return _local_tz()


def _zone(name, fallback):
    """TZID -> tzinfo; unknown names (or none) fall back to `fallback` (local)."""
    if not name:
        return fallback
    name = _WINDOWS_TZ.get(name, name)
    try:
        return zoneinfo.ZoneInfo(name)
    except Exception:
        pass
    # e.g. "/mozilla.org/20050126_1/America/Toronto": try the trailing segments
    parts = name.strip("/").split("/")
    for n in (2, 3):
        if len(parts) > n:
            try:
                return zoneinfo.ZoneInfo("/".join(parts[-n:]))
            except Exception:
                pass
    return fallback


# --- lexing ------------------------------------------------------------------

def _unfold(text: str) -> list:
    """Physical lines -> logical lines (a leading space/tab continues the previous one)."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def _split_line(line: str):
    """'DTSTART;TZID="A/B":2026...' -> ('DTSTART', {'TZID': 'A/B'}, '2026...'); None if malformed."""
    parts, buf, quoted, value = [], [], False, None
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
            buf.append(ch)
        elif ch == ";" and not quoted:
            parts.append("".join(buf))
            buf = []
        elif ch == ":" and not quoted:
            parts.append("".join(buf))
            value = line[i + 1:]
            break
        else:
            buf.append(ch)
    if value is None:
        return None
    name = parts[0].strip().upper().rsplit(".", 1)[-1]     # drop "item1." style group prefixes
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.strip().upper()] = v.strip().strip('"')
    return name, params, value


def _read_events(lines: list) -> list:
    """Property dicts {NAME: [(params, value), ...]} for each VEVENT.

    Nested components (VALARM) are skipped so their DESCRIPTION/TRIGGER etc.
    never overwrite the event's own fields; VTODO/VJOURNAL/VTIMEZONE likewise.
    """
    events, stack, current = [], [], None
    for line in lines:
        parsed = _split_line(line)
        if not parsed:
            continue
        name, params, value = parsed
        if name == "BEGIN":
            comp = value.strip().upper()
            stack.append(comp)
            if comp == "VEVENT":
                current = {}
        elif name == "END":
            comp = value.strip().upper()
            if comp in stack:
                while stack and stack.pop() != comp:
                    pass
            if comp == "VEVENT" and current is not None:
                events.append(current)
                current = None
        elif current is not None and stack and stack[-1] == "VEVENT":
            current.setdefault(name, []).append((params, value))
    return events


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), text)


def _clean_title(raw) -> str:
    title = " ".join(_unescape(raw or "").split())
    if len(title) > TITLE_MAX_CHARS:
        title = title[:TITLE_MAX_CHARS].rstrip()
    return title or "Untitled event"


def _parse_value(raw: str, params: dict, tz):
    """DATE -> date, DATE-TIME -> aware datetime (floating/unknown TZID use `tz`); None if bad."""
    m = _DT_RE.match((raw or "").strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss, z = m.groups()
    if hh is None or params.get("VALUE", "").upper() == "DATE":
        return datetime.date(int(y), int(mo), int(d))
    zone = _UTC if z else _zone(params.get("TZID"), tz)
    return datetime.datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), tzinfo=zone)


def _parse_duration(raw: str):
    m = _DUR_RE.match((raw or "").strip().upper())
    if not m or raw.strip().upper() in ("P", "PT"):
        return None
    sign, w, d, h, mi, s = m.groups()
    delta = datetime.timedelta(weeks=int(w or 0), days=int(d or 0), hours=int(h or 0),
                               minutes=int(mi or 0), seconds=int(s or 0))
    return -delta if sign == "-" else delta


def _is_dt(v) -> bool:
    return isinstance(v, datetime.datetime)


def _date_of(v) -> datetime.date:
    """Wall-clock date in the value's own zone."""
    return v.date() if _is_dt(v) else v


def _keys(v) -> set:
    """Match keys for an occurrence start (EXDATE / RECURRENCE-ID lookups)."""
    if _is_dt(v):
        return {("dt", v.astimezone(_UTC)), ("d", v.date())}
    return {("d", v)}


def _key(v):
    return ("dt", v.astimezone(_UTC)) if _is_dt(v) else ("d", v)


# --- RRULE -------------------------------------------------------------------

def _ints(raw):
    out = []
    for x in (raw or "").split(","):
        try:
            out.append(int(x))
        except ValueError:
            pass
    return out


def _parse_rrule(raw: str, start):
    """RRULE text -> dict, or None when the rule is absent/unsupported (then: a single event)."""
    parts = {}
    for part in (raw or "").split(";"):
        k, _, v = part.partition("=")
        parts[k.strip().upper()] = v.strip().upper()
    freq = parts.get("FREQ")
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return None
    byday = []
    for item in (parts.get("BYDAY") or "").split(","):
        m = _BYDAY_RE.match(item.strip())
        if m:
            byday.append((int(m.group(1)) if m.group(1) else None, _WEEKDAYS[m.group(2)]))
    until = None
    if parts.get("UNTIL"):
        until = _parse_value(parts["UNTIL"], {}, start.tzinfo if _is_dt(start) else _UTC)
    try:
        count = int(parts["COUNT"]) if parts.get("COUNT") else None
    except ValueError:
        count = None
    return {
        "freq": freq,
        "interval": max(1, (_ints(parts.get("INTERVAL")) or [1])[0]),
        "count": count,
        "until": until,
        "byday": byday,
        "bymonthday": [d for d in _ints(parts.get("BYMONTHDAY")) if d],
        "bymonth": [m for m in _ints(parts.get("BYMONTH")) if 1 <= m <= 12],
        "bysetpos": [p for p in _ints(parts.get("BYSETPOS")) if p],
        "wkst": _WEEKDAYS.get(parts.get("WKST"), 0),
    }


def _add_months(d: datetime.date, n: int):
    total = d.year * 12 + d.month - 1 + n
    return total // 12, total % 12 + 1


def _month_days(y: int, m: int) -> list:
    first = datetime.date(y, m, 1)
    nxt = datetime.date(y + m // 12, m % 12 + 1, 1)
    return [first + datetime.timedelta(days=i) for i in range((nxt - first).days)]


def _select_byday(span: list, byday: list) -> set:
    """BYDAY within `span`: plain weekdays match all, '2MO' the 2nd Monday, '-1FR' the last Friday."""
    out = set()
    for n, wd in byday:
        matches = [d for d in span if d.weekday() == wd]
        if n is None:
            out.update(matches)
        elif 0 < n <= len(matches):
            out.add(matches[n - 1])
        elif n < 0 and -n <= len(matches):
            out.add(matches[n])
    return out


def _select_monthday(span: list, monthdays: list) -> set:
    out = set()
    for md in monthdays:
        idx = md - 1 if md > 0 else len(span) + md
        if 0 <= idx < len(span):
            out.add(span[idx])
    return out


def _in_month(y, m, rule, anchor) -> set:
    span = _month_days(y, m)
    if rule["bymonthday"] or rule["byday"]:
        sel = None
        if rule["bymonthday"]:
            sel = _select_monthday(span, rule["bymonthday"])
        if rule["byday"]:
            days = _select_byday(span, rule["byday"])
            sel = days if sel is None else sel & days
        return sel
    return _select_monthday(span, [anchor.day]) if anchor.day <= len(span) else set()


def _week_start(d: datetime.date, wkst: int) -> datetime.date:
    return d - datetime.timedelta(days=(d.weekday() - wkst) % 7)


def _period_start(rule, anchor, k):
    step = rule["interval"] * k
    freq = rule["freq"]
    if freq == "DAILY":
        return anchor + datetime.timedelta(days=step)
    if freq == "WEEKLY":
        return _week_start(anchor, rule["wkst"]) + datetime.timedelta(weeks=step)
    if freq == "MONTHLY":
        return datetime.date(*_add_months(anchor, step), 1)
    return datetime.date(anchor.year + step, 1, 1)


def _period_dates(rule, anchor, k) -> list:
    """Sorted candidate dates of period k (before BYSETPOS / DTSTART filtering)."""
    freq, start = rule["freq"], _period_start(rule, anchor, k)
    if freq == "DAILY":
        days = {start}
        if rule["bymonthday"]:
            days &= _select_monthday(_month_days(start.year, start.month), rule["bymonthday"])
        if rule["byday"]:
            days = {d for d in days if d.weekday() in {wd for _, wd in rule["byday"]}}
    elif freq == "WEEKLY":
        weekdays = {wd for _, wd in rule["byday"]} or {anchor.weekday()}
        days = {start + datetime.timedelta(days=i) for i in range(7)}
        days = {d for d in days if d.weekday() in weekdays}
    elif freq == "MONTHLY":
        days = _in_month(start.year, start.month, rule, anchor)
    else:
        y = start.year
        if rule["bymonth"]:
            days = set()
            for m in rule["bymonth"]:
                days |= _in_month(y, m, rule, anchor)
        elif rule["bymonthday"]:
            days = set()
            for m in range(1, 13):
                days |= _in_month(y, m, rule, anchor)
        elif rule["byday"]:                                   # e.g. 20MO = 20th Monday of the year
            span = [d for m in range(1, 13) for d in _month_days(y, m)]
            days = _select_byday(span, rule["byday"])
        else:
            days = _in_month(y, anchor.month, rule, anchor)
    if rule["bymonth"] and freq != "YEARLY":
        days = {d for d in days if d.month in rule["bymonth"]}
    days = sorted(days)
    if rule["bysetpos"]:
        n = len(days)
        days = sorted({days[p - 1 if p > 0 else p] for p in rule["bysetpos"] if -n <= p <= n})
    return days


def _first_period(rule, anchor, target) -> int:
    """Index of the period containing `target` (or the last one starting before it)."""
    if target <= anchor:
        return 0
    freq = rule["freq"]
    if freq == "DAILY":
        diff = (target - anchor).days
    elif freq == "WEEKLY":
        diff = (_week_start(target, rule["wkst"]) - _week_start(anchor, rule["wkst"])).days // 7
    elif freq == "MONTHLY":
        diff = (target.year - anchor.year) * 12 + target.month - anchor.month
    else:
        diff = target.year - anchor.year
    return diff // rule["interval"]


def _fixed_per_period(rule) -> bool:
    """DAILY/WEEKLY rules with nothing that varies by month have a constant count per period."""
    if rule["bymonth"] or rule["bymonthday"] or rule["bysetpos"]:
        return False
    return rule["freq"] == "WEEKLY" or (rule["freq"] == "DAILY" and not rule["byday"])


def _rule_dates(rule, anchor, lo, hi):
    """Occurrence dates (DTSTART's wall-clock dates), ascending, up to `hi`.

    With COUNT every occurrence since DTSTART must be counted, so the walk
    starts there; otherwise it jumps straight to the period holding `lo`.
    """
    count = rule["count"]
    k = 0 if count is not None else _first_period(rule, anchor, lo)
    seen = 0
    if count is not None and _fixed_per_period(rule):
        # Every period after the first holds the same number of dates, so the
        # occurrences before `lo` can be counted without walking them.
        k1 = _first_period(rule, anchor, lo)
        if k1 > 0:
            first = sum(1 for d in _period_dates(rule, anchor, 0) if d >= anchor)
            seen = first + (k1 - 1) * len(_period_dates(rule, anchor, 1))
            if seen >= count:
                return
            k = k1
    for _ in range(_MAX_PERIODS):
        try:
            if _period_start(rule, anchor, k) > hi:
                return
            dates = _period_dates(rule, anchor, k)
        except (OverflowError, ValueError):                   # walked past year 9999
            return
        for d in dates:
            if d < anchor:
                continue
            if count is not None:
                if seen >= count:
                    return
                seen += 1
            yield d
        k += 1


def _past_until(occ, until) -> bool:
    if _is_dt(until):
        return occ > until if _is_dt(occ) else occ > until.date()
    return _date_of(occ) > until


def _at(start, d: datetime.date):
    """`start` moved to date d, keeping its wall-clock time and zone."""
    return start.replace(year=d.year, month=d.month, day=d.day) if _is_dt(start) else d


# --- events ------------------------------------------------------------------

def _first(props, name):
    values = props.get(name)
    return values[0] if values else ({}, None)


def _date_list(props, name, tz) -> list:
    out = []
    for params, raw in props.get(name, []):
        if params.get("VALUE", "").upper() == "PERIOD":
            continue
        for piece in raw.split(","):
            v = _parse_value(piece, params, tz)
            if v is not None:
                out.append(v)
    return out


def _build(props, tz):
    """Property dict -> normalised event dict, or None if it has no usable DTSTART."""
    params, raw = _first(props, "DTSTART")
    start = _parse_value(raw, params, tz)
    if start is None:
        return None
    end = None
    params, raw = _first(props, "DTEND")
    if raw:
        end = _parse_value(raw, params, tz)
        if end is not None and _is_dt(end) != _is_dt(start):
            end = None
    if end is None:
        dur = _parse_duration(_first(props, "DURATION")[1])
        if dur is not None:
            end = start + dur if _is_dt(start) else start + datetime.timedelta(days=dur.days)
    if _is_dt(start):
        # absolute length (via UTC), so a DST change mid-event doesn't skew it
        duration = datetime.timedelta(0)
        if end is not None:
            duration = max(duration, end.astimezone(_UTC) - start.astimezone(_UTC))
    else:
        duration = max(_DAY, (end - start) if end is not None else _DAY)
    params, raw = _first(props, "RECURRENCE-ID")
    rid = _parse_value(raw, params, tz) if raw else None
    return {
        "uid": (_first(props, "UID")[1] or "").strip(),
        "title": _clean_title(_first(props, "SUMMARY")[1]),
        "start": start,
        "duration": duration,
        "cancelled": (_first(props, "STATUS")[1] or "").strip().upper() == "CANCELLED",
        "rrule": None if rid else _parse_rrule(_first(props, "RRULE")[1], start),
        "rdate": [] if rid else _date_list(props, "RDATE", tz),
        "exdate": {_key(v) for v in _date_list(props, "EXDATE", tz)},
        "recurrence_id": rid,
    }


def _occurrences(ev, day):
    """Start values of `ev` that could touch `day` (overlap is checked later)."""
    start = ev["start"]
    if not ev["rrule"] and not ev["rdate"]:
        return [start]
    span = ev["duration"].days
    if _is_dt(start):                       # its own zone may sit up to ~26 h off the target zone
        lo, hi = day - datetime.timedelta(days=span + 2), day + datetime.timedelta(days=2)
    else:
        lo, hi = day - datetime.timedelta(days=span), day
    anchor = _date_of(start)
    out = []
    if lo <= anchor <= hi:
        out.append(start)                   # DTSTART is always the first instance
    rule = ev["rrule"]
    if rule and not (rule["until"] is not None and _date_of(rule["until"]) < lo - _DAY):
        for d in _rule_dates(rule, anchor, lo, hi):
            if d > hi:
                break
            if d < lo:
                continue
            occ = _at(start, d)
            if rule["until"] is not None and _past_until(occ, rule["until"]):
                break
            if occ != start:
                out.append(occ)
    for r in ev["rdate"]:
        if _is_dt(r) != _is_dt(start):
            r = _at(start, r) if not _is_dt(r) else r.date()
        if lo <= _date_of(r) <= hi and r not in out:
            out.append(r)
    return [o for o in out if not (_keys(o) & ev["exdate"])]


def _entry(occ, duration, title, day, tz):
    """{"time", "end", "title"} if this occurrence is on `day` (in `tz`), else None."""
    if not _is_dt(occ):
        if occ <= day < occ + datetime.timedelta(days=max(1, duration.days)):
            return {"time": None, "end": None, "title": title}
        return None
    day_start = datetime.datetime.combine(day, datetime.time(0), tzinfo=tz)
    day_end = datetime.datetime.combine(day + _DAY, datetime.time(0), tzinfo=tz)
    s = occ.astimezone(_UTC)
    e = s + duration
    if not (s < day_end and e > day_start) and not (not duration and day_start <= s < day_end):
        return None
    # Started yesterday and still running -> "time": None (ongoing), see module docstring.
    return {
        "time": s.astimezone(tz).strftime("%H:%M") if s >= day_start else None,
        "end": e.astimezone(tz).strftime("%H:%M") if duration and e < day_end else None,
        "title": title,
    }


def parse_events(ics_text: str, day: datetime.date, tz=None) -> list:
    """[{"time": "HH:MM" | None, "end": "HH:MM" | None, "title": str}] on `day`.

    All-day (and already-running) events come first, then timed ones by start.
    `tz` is a zone name or tzinfo (default: the system zone); times are in it.
    """
    zone = _resolve_tz(tz)
    events = []
    for props in _read_events(_unfold(ics_text or "")):
        try:
            ev = _build(props, zone)
        except Exception as e:
            logger.debug(f"Briefing: skipping unreadable VEVENT ({type(e).__name__}: {e})")
            continue
        if ev:
            events.append(ev)

    # RECURRENCE-ID overrides replace (or, when cancelled, remove) one occurrence of their master.
    overridden = {}
    for ev in events:
        if ev["recurrence_id"] is not None:
            overridden.setdefault(ev["uid"], set()).add(_key(ev["recurrence_id"]))

    out = []
    for ev in events:
        if ev["cancelled"]:
            continue
        try:
            replaced = overridden.get(ev["uid"], set()) if ev["recurrence_id"] is None else set()
            for occ in _occurrences(ev, day):
                if replaced and _keys(occ) & replaced:
                    continue
                entry = _entry(occ, ev["duration"], ev["title"], day, zone)
                if entry and entry not in out:
                    out.append(entry)
        except Exception as e:
            logger.debug(f"Briefing: skipping event {ev['title']!r} ({type(e).__name__}: {e})")
    return sorted(out, key=lambda x: (x["time"] is not None, x["time"] or ""))


# --- fetching ----------------------------------------------------------------

def _fetch(url: str, timeout: float = 10) -> bytes:
    import requests
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
    resp.raise_for_status()
    return resp.content


def _decode(data) -> str:
    if isinstance(data, str):
        return data
    return bytes(data).decode("utf-8-sig", errors="replace")


def _write_cache(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _read_cache(path: str, clock):
    try:
        age = clock() - os.path.getmtime(path)
        if 0 <= age < CACHE_MAX_AGE_S:
            with open(path, encoding="utf-8") as f:
                logger.info(f"Briefing: calendar unavailable, using copy cached {age / 3600:.1f} h ago")
                return f.read()
    except OSError:
        pass
    return None


def cache_path_for(url: str, cache_dir: str = CACHE_DIR) -> str:
    """cache_dir/calendar-<12 hex>.ics: per calendar, without the secret URL in the name."""
    import hashlib
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return os.path.join(cache_dir, CACHE_NAME.replace(".ics", f"-{digest}.ics"))


def get_events(url: str, day: datetime.date, fetch=None, cache_dir: str = CACHE_DIR,
               clock=time.time, tz=None) -> list:
    """Events on `day` from the iCal feed at `url`; never raises.

    A good download is cached to cache_dir/calendar-<hash of url>.ics (one per
    calendar, so several don't overwrite each other's copy); when the feed is
    unreachable (or returns something that isn't a calendar), a cached copy
    under 24 h old is used instead, else [].
    """
    if not url:
        return []
    cache_path = cache_path_for(url, cache_dir)
    text = None
    try:
        text = _decode((fetch or _fetch)(url))
        if "BEGIN:VCALENDAR" not in text[:4096].upper():
            raise ValueError("response is not an iCalendar file")
    except Exception as e:
        # Only the exception type: requests' messages embed the URL, which is a secret.
        logger.warning(f"Briefing: calendar fetch failed ({type(e).__name__})")
        text = None
    if text is not None:
        try:
            _write_cache(cache_path, text)
        except Exception as e:
            logger.warning(f"Briefing: could not cache calendar ({type(e).__name__}: {e})")
    else:
        text = _read_cache(cache_path, clock)
        if text is None:
            return []
    try:
        return parse_events(text, day, tz=tz)
    except Exception as e:
        logger.warning(f"Briefing: could not read calendar ({type(e).__name__}: {e})")
        return []
