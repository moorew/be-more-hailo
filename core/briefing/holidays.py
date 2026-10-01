"""Canadian holidays and a few well-loved observances, worked out offline.

No API and nothing to configure beyond the province (for the February and
August long weekends): dates are computed from the usual rules, Easter from
the Gregorian computus.
"""
import datetime

# February holiday by province (third Monday); others have none.
_FEBRUARY = {"ON": "Family Day", "AB": "Family Day", "BC": "Family Day", "SK": "Family Day",
             "NB": "Family Day", "MB": "Louis Riel Day", "PE": "Islander Day", "NS": "Heritage Day"}
# First Monday of August goes by many names; these are the common ones.
_AUGUST = {"ON": "Civic Holiday", "AB": "Heritage Day", "BC": "British Columbia Day",
           "SK": "Saskatchewan Day", "NB": "New Brunswick Day", "NS": "Natal Day",
           "MB": "Terry Fox Day", "NT": "Civic Holiday", "NU": "Civic Holiday"}


def easter(year: int) -> datetime.date:
    """Gregorian Easter Sunday (anonymous / Meeus algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return datetime.date(year, month, day)


def _nth_weekday(year, month, weekday, n):
    """n-th (1-based) `weekday` (Mon=0) of the month."""
    first = datetime.date(year, month, 1)
    return first + datetime.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def holidays(year: int, province: str = "ON") -> dict:
    """{date: name} for the year."""
    province = (province or "").upper()
    e = easter(year)
    victoria = datetime.date(year, 5, 24)
    victoria -= datetime.timedelta(days=victoria.weekday())          # Monday on or before 24 May
    days = {
        datetime.date(year, 1, 1): "New Year's Day",
        datetime.date(year, 2, 14): "Valentine's Day",
        datetime.date(year, 3, 17): "St. Patrick's Day",
        e - datetime.timedelta(days=2): "Good Friday",
        e: "Easter Sunday",
        _nth_weekday(year, 5, 6, 2): "Mother's Day",
        victoria: "Victoria Day",
        _nth_weekday(year, 6, 6, 3): "Father's Day",
        datetime.date(year, 7, 1): "Canada Day",
        _nth_weekday(year, 9, 0, 1): "Labour Day",
        datetime.date(year, 9, 30): "the National Day for Truth and Reconciliation",
        _nth_weekday(year, 10, 0, 2): "Thanksgiving",
        datetime.date(year, 10, 31): "Halloween",
        datetime.date(year, 11, 11): "Remembrance Day",
        datetime.date(year, 12, 24): "Christmas Eve",
        datetime.date(year, 12, 25): "Christmas Day",
        datetime.date(year, 12, 26): "Boxing Day",
        datetime.date(year, 12, 31): "New Year's Eve",
    }
    if province in _FEBRUARY:
        days[_nth_weekday(year, 2, 0, 3)] = _FEBRUARY[province]
    if province in _AUGUST:
        days[_nth_weekday(year, 8, 0, 1)] = _AUGUST[province]
    return days


def upcoming(today: datetime.date, province: str = "ON", horizon_days: int = 3) -> list:
    """[{name, date, days}] for holidays today or within `horizon_days`, soonest first."""
    out = []
    for year in {today.year, (today + datetime.timedelta(days=horizon_days)).year}:
        for d, name in holidays(year, province).items():
            days = (d - today).days
            if 0 <= days <= horizon_days:
                out.append({"name": name, "date": d.isoformat(), "days": days})
    return sorted(out, key=lambda h: h["days"])
