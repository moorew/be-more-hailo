"""Reading "Your day" from a calendar's secret iCal (.ics) address.

ICS snippets are built inline; the network is faked.  Times are checked in an
explicit zone (America/Toronto) so the tests don't depend on the Pi's TZ.
"""
import datetime
import os
import time

from core.briefing import ical

TZ = "America/Toronto"
FRI = datetime.date(2026, 10, 2)          # a Friday; Toronto is on EDT (UTC-4)


def cal(*events, extra=""):
    body = "".join(f"BEGIN:VEVENT\r\n{e.strip()}\r\nEND:VEVENT\r\n" for e in events)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n{extra}{body}END:VCALENDAR\r\n"


def ev(summary, dtstart, *lines, uid=None):
    parts = [f"UID:{uid or summary}", f"SUMMARY:{summary}", dtstart, *lines]
    return "\r\n".join(parts)


def titles(ics, day=FRI, tz=TZ):
    return [e["title"] for e in ical.parse_events(ics, day, tz=tz)]


# --- basic forms -------------------------------------------------------------

def test_all_day_event_with_exclusive_end():
    ics = cal(ev("Pizza day", "DTSTART;VALUE=DATE:20261002", "DTEND;VALUE=DATE:20261003"))
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": None, "end": None, "title": "Pizza day"}]
    assert titles(ics, FRI + datetime.timedelta(days=1)) == []      # DTEND is exclusive
    assert titles(ics, FRI - datetime.timedelta(days=1)) == []


def test_multi_day_all_day_event_counts_for_each_day():
    ics = cal(ev("Cottage", "DTSTART;VALUE=DATE:20260930", "DTEND;VALUE=DATE:20261004"))
    assert titles(ics, datetime.date(2026, 9, 30)) == ["Cottage"]
    for d in (1, 2, 3):
        assert titles(ics, datetime.date(2026, 10, d)) == ["Cottage"]
    assert titles(ics, datetime.date(2026, 10, 4)) == []


def test_utc_time_is_converted_to_the_given_zone():
    ics = cal(ev("Standup", "DTSTART:20261002T140000Z", "DTEND:20261002T143000Z"))
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": "10:00", "end": "10:30", "title": "Standup"}]
    assert ical.parse_events(ics, FRI, tz="Europe/London")[0]["time"] == "15:00"


def test_utc_late_evening_lands_on_the_local_day():
    # 01:30Z on the 3rd is 21:30 on the 2nd in Toronto
    ics = cal(ev("Late call", "DTSTART:20261003T013000Z", "DTEND:20261003T020000Z"))
    assert titles(ics, FRI) == ["Late call"]
    assert titles(ics, FRI + datetime.timedelta(days=1)) == []


def test_tzid_times_use_zoneinfo():
    ics = cal(ev("Dentist", "DTSTART;TZID=America/Vancouver:20261002T090000",
                 "DTEND;TZID=America/Vancouver:20261002T100000"))
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": "12:00", "end": "13:00", "title": "Dentist"}]


def test_unknown_tzid_is_treated_as_local():
    ics = cal(ev("Mystery", "DTSTART;TZID=Narnia/Cair_Paravel:20261002T090000",
                 "DTEND;TZID=Narnia/Cair_Paravel:20261002T091500"))
    assert ical.parse_events(ics, FRI, tz=TZ)[0] == {"time": "09:00", "end": "09:15", "title": "Mystery"}


def test_floating_time_is_local_wall_clock():
    ics = cal(ev("Lunch", "DTSTART:20261002T120000", "DTEND:20261002T130000"))
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": "12:00", "end": "13:00", "title": "Lunch"}]
    assert ical.parse_events(ics, FRI, tz="Asia/Tokyo")[0]["time"] == "12:00"


def test_duration_instead_of_dtend():
    ics = cal(ev("Run", "DTSTART:20261002T070000", "DURATION:PT45M"))
    assert ical.parse_events(ics, FRI, tz=TZ)[0] == {"time": "07:00", "end": "07:45", "title": "Run"}


def test_event_running_since_yesterday_has_no_start_time():
    ics = cal(ev("Overnight shift", "DTSTART:20261001T220000", "DTEND:20261002T060000"))
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": None, "end": "06:00", "title": "Overnight shift"}]
    # ...and on its first day it has a start but runs past midnight (no end)
    assert ical.parse_events(ics, datetime.date(2026, 10, 1), tz=TZ)[0] == {
        "time": "22:00", "end": None, "title": "Overnight shift"}


def test_sorted_all_day_first_then_by_time():
    ics = cal(ev("B late", "DTSTART:20261002T170000"),
              ev("A early", "DTSTART:20261002T080000"),
              ev("Holiday", "DTSTART;VALUE=DATE:20261002"))
    assert titles(ics) == ["Holiday", "A early", "B late"]


def test_event_on_another_day_is_ignored():
    assert titles(cal(ev("Tomorrow", "DTSTART:20261003T090000"))) == []


# --- text --------------------------------------------------------------------

def test_folded_lines_and_crlf():
    ics = cal("UID:f1\r\nSUMMARY:A very long meeting\r\n  title that wa\r\n\ts folded\r\n"
              "DTSTART;TZID=America/Tor\r\n onto:20261002T090000")
    assert ical.parse_events(ics, FRI, tz=TZ) == [
        {"time": "09:00", "end": None, "title": "A very long meeting title that was folded"}]


def test_lf_only_line_endings():
    ics = cal(ev("Unix", "DTSTART:20261002T090000")).replace("\r\n", "\n")
    assert titles(ics) == ["Unix"]


def test_escaped_text_is_unescaped_and_whitespace_collapsed():
    ics = cal(ev(r"Dinner\, drinks\; then\nhome \\ bed", "DTSTART:20261002T190000"))
    assert titles(ics) == ["Dinner, drinks; then home \\ bed"]


def test_title_is_capped_at_80_chars_and_missing_title_has_a_default():
    ics = cal(ev("x" * 200, "DTSTART:20261002T090000"),
              "UID:nt\r\nDTSTART:20261002T100000")
    got = titles(ics)
    assert len(got[0]) == 80 and got[1] == "Untitled event"


# --- status / components -----------------------------------------------------

def test_cancelled_event_is_skipped_transparent_is_kept():
    ics = cal(ev("Gone", "DTSTART:20261002T090000", "STATUS:CANCELLED"),
              ev("Free time", "DTSTART:20261002T100000", "TRANSP:TRANSPARENT"))
    assert titles(ics) == ["Free time"]


def test_nested_valarm_does_not_overwrite_event_fields():
    ics = cal(ev("Real title", "DTSTART:20261002T090000",
                 "BEGIN:VALARM", "ACTION:DISPLAY", "SUMMARY:Alarm title",
                 "DTSTART:20261005T000000", "TRIGGER:-PT15M", "END:VALARM",
                 "DTEND:20261002T100000"))
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": "09:00", "end": "10:00", "title": "Real title"}]


def test_vtodo_and_vtimezone_are_ignored():
    extra = ("BEGIN:VTIMEZONE\r\nTZID:America/Toronto\r\nBEGIN:DAYLIGHT\r\nDTSTART:19700308T020000\r\n"
             "END:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
             "BEGIN:VTODO\r\nUID:t\r\nSUMMARY:Todo\r\nDTSTART:20261002T090000\r\nEND:VTODO\r\n")
    assert titles(cal(ev("Event", "DTSTART:20261002T090000"), extra=extra)) == ["Event"]


# --- recurrence --------------------------------------------------------------

def test_daily_rule_years_old_is_found_quickly():
    ics = cal(ev("Meds", "DTSTART;TZID=America/Toronto:20100101T080000", "RRULE:FREQ=DAILY"))
    t0 = time.perf_counter()
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": "08:00", "end": None, "title": "Meds"}]
    assert time.perf_counter() - t0 < 0.5


def test_recurring_tzid_keeps_wall_clock_across_dst():
    # Started in winter (EST); still 09:00 local in October (EDT)
    ics = cal(ev("Class", "DTSTART;TZID=America/Toronto:20260105T090000", "RRULE:FREQ=WEEKLY;BYDAY=FR"))
    assert ical.parse_events(ics, FRI, tz=TZ)[0]["time"] == "09:00"


def test_weekly_byday_with_interval_2():
    # Starts Mon 2026-09-07; every other week on MO,WE,FR -> weeks of Sep 7, Sep 21, Oct 5...
    ics = cal(ev("Gym", "DTSTART:20260907T180000", "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR"))
    on = [datetime.date(2026, 9, d) for d in (7, 9, 11, 21, 23, 25)] + [datetime.date(2026, 10, 5)]
    off = [datetime.date(2026, 9, d) for d in (14, 16, 18, 22, 28, 30)] + [FRI]
    assert all(titles(ics, d) == ["Gym"] for d in on)
    assert all(titles(ics, d) == [] for d in off)


def test_monthly_bymonthday():
    ics = cal(ev("Rent", "DTSTART;VALUE=DATE:20250102", "RRULE:FREQ=MONTHLY;BYMONTHDAY=2"))
    assert titles(ics) == ["Rent"]
    assert titles(ics, datetime.date(2026, 10, 3)) == []


def test_monthly_without_byday_uses_dtstart_day_and_skips_short_months():
    ics = cal(ev("Payday", "DTSTART;VALUE=DATE:20260131", "RRULE:FREQ=MONTHLY"))
    assert titles(ics, datetime.date(2026, 3, 31)) == ["Payday"]
    assert titles(ics, datetime.date(2026, 2, 28)) == []


def test_monthly_second_monday_and_last_friday():
    ics = cal(ev("Book club", "DTSTART:20260112T190000", "RRULE:FREQ=MONTHLY;BYDAY=2MO"),
              ev("Pub", "DTSTART:20260130T170000", "RRULE:FREQ=MONTHLY;BYDAY=-1FR"))
    assert titles(ics, datetime.date(2026, 10, 12)) == ["Book club"]
    assert titles(ics, datetime.date(2026, 10, 5)) == []
    assert titles(ics, datetime.date(2026, 10, 30)) == ["Pub"]
    assert titles(ics, datetime.date(2026, 10, 23)) == []
    assert titles(ics, FRI) == []


def test_yearly_birthday():
    ics = cal(ev("Mum's birthday", "DTSTART;VALUE=DATE:19601002", "DTEND;VALUE=DATE:19601003",
                 "RRULE:FREQ=YEARLY"))
    assert titles(ics) == ["Mum's birthday"]
    assert titles(ics, datetime.date(2026, 10, 1)) == []


def test_yearly_bymonth_byday_thanksgiving():
    ics = cal(ev("Thanksgiving dinner", "DTSTART;VALUE=DATE:20201012",
                 "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=2MO"))
    assert titles(ics, datetime.date(2026, 10, 12)) == ["Thanksgiving dinner"]


def test_count_limits_occurrences():
    ics = cal(ev("Course", "DTSTART:20260928T090000", "RRULE:FREQ=DAILY;COUNT=5"))   # Sep 28..Oct 2
    assert titles(ics, FRI) == ["Course"]
    assert titles(ics, datetime.date(2026, 10, 3)) == []


def test_until_limits_occurrences_date_and_datetime():
    by_date = cal(ev("A", "DTSTART;VALUE=DATE:20260928", "RRULE:FREQ=DAILY;UNTIL=20261001"))
    by_dt = cal(ev("B", "DTSTART;TZID=America/Toronto:20260928T090000",
                   "RRULE:FREQ=DAILY;UNTIL=20261002T130000Z"))                   # 09:00 EDT = 13:00Z: included
    cut = cal(ev("C", "DTSTART;TZID=America/Toronto:20260928T090000",
                 "RRULE:FREQ=DAILY;UNTIL=20261002T125959Z"))
    assert titles(by_date, datetime.date(2026, 10, 1)) == ["A"] and titles(by_date) == []
    assert titles(by_dt) == ["B"]
    assert titles(cut) == [] and titles(cut, datetime.date(2026, 10, 1)) == ["C"]


def test_exdate_removes_occurrences_single_list_and_tzid():
    rule = "RRULE:FREQ=DAILY"
    ics = cal(ev("Walk", "DTSTART;TZID=America/Toronto:20260901T070000", rule,
                 "EXDATE;TZID=America/Toronto:20261002T070000"),
              ev("Swim", "DTSTART:20260901T120000Z", rule, "EXDATE:20260930T120000Z,20261002T120000Z"),
              ev("Read", "DTSTART;VALUE=DATE:20260901", rule, "EXDATE;VALUE=DATE:20261002"),
              ev("Kept", "DTSTART:20260901T120000Z", rule, "EXDATE:20261001T120000Z"))
    assert titles(ics) == ["Kept"]
    assert titles(ics, datetime.date(2026, 9, 30)) == ["Read", "Walk", "Kept"]


def test_recurrence_id_moves_and_renames_one_occurrence():
    master = ev("Weekly 1:1", "DTSTART;TZID=America/Toronto:20260904T100000",
                "DTEND;TZID=America/Toronto:20260904T103000", "RRULE:FREQ=WEEKLY", uid="w1")
    moved = ev("Weekly 1:1 (moved)", "DTSTART;TZID=America/Toronto:20261002T150000",
               "DTEND;TZID=America/Toronto:20261002T153000",
               "RECURRENCE-ID;TZID=America/Toronto:20261002T100000", uid="w1")
    ics = cal(master, moved)
    assert ical.parse_events(ics, FRI, tz=TZ) == [{"time": "15:00", "end": "15:30", "title": "Weekly 1:1 (moved)"}]
    assert ical.parse_events(ics, datetime.date(2026, 10, 9), tz=TZ)[0]["time"] == "10:00"


def test_recurrence_id_can_move_an_occurrence_to_another_day():
    master = ev("Sync", "DTSTART:20260904T140000Z", "RRULE:FREQ=WEEKLY", uid="s1")
    moved = ev("Sync", "DTSTART:20261001T140000Z", "RECURRENCE-ID:20261002T140000Z", uid="s1")
    ics = cal(master, moved)
    assert titles(ics) == []
    assert titles(ics, datetime.date(2026, 10, 1)) == ["Sync"]


def test_cancelled_override_removes_the_occurrence():
    master = ev("Piano", "DTSTART;TZID=America/Toronto:20260904T160000", "RRULE:FREQ=WEEKLY", uid="p1")
    cancelled = ev("Piano", "DTSTART;TZID=America/Toronto:20261002T160000",
                   "RECURRENCE-ID;TZID=America/Toronto:20261002T160000", "STATUS:CANCELLED", uid="p1")
    ics = cal(cancelled, master)              # override before master: order must not matter
    assert titles(ics) == []
    assert titles(ics, datetime.date(2026, 10, 9)) == ["Piano"]


def test_garbage_does_not_raise():
    assert ical.parse_events("", FRI, tz=TZ) == []
    assert ical.parse_events("not a calendar\nat all:", FRI, tz=TZ) == []
    broken = cal(ev("Bad date", "DTSTART:2026-10-02"), ev("Bad rule", "DTSTART:20261002T090000",
                                                          "RRULE:FREQ=WEEKLY;INTERVAL=x;COUNT=y;BYDAY=ZZ"),
                 "BEGIN:VALARM\r\nUID:x")
    assert titles(broken) == ["Bad rule"]


def test_default_zone_is_the_system_one():
    ics = cal(ev("Local", "DTSTART:20261002T090000"))       # floating -> same wall clock in any zone
    assert ical.parse_events(ics, FRI)[0]["time"] == "09:00"


# --- get_events --------------------------------------------------------------

GOOD = cal(ev("Standup", "DTSTART:20261002T140000Z")).encode()
URL = "https://calendar.google.com/calendar/ical/x/private-secret/basic.ics"


def boom(url):
    raise ConnectionError(f"cannot reach {url}")


def test_get_events_success_writes_cache(tmp_path):
    got = ical.get_events(URL, FRI, fetch=lambda u: GOOD, cache_dir=str(tmp_path), tz=TZ)
    assert got == [{"time": "10:00", "end": None, "title": "Standup"}]
    assert (tmp_path / "calendar.ics").read_bytes().replace(b"\r\n", b"\n") == GOOD.replace(b"\r\n", b"\n")


def test_get_events_falls_back_to_fresh_cache(tmp_path):
    ical.get_events(URL, FRI, fetch=lambda u: GOOD, cache_dir=str(tmp_path), tz=TZ)
    mtime = os.path.getmtime(tmp_path / "calendar.ics")
    got = ical.get_events(URL, FRI, fetch=boom, cache_dir=str(tmp_path), tz=TZ, clock=lambda: mtime + 23 * 3600)
    assert [e["title"] for e in got] == ["Standup"]


def test_non_calendar_response_does_not_replace_cache(tmp_path):
    ical.get_events(URL, FRI, fetch=lambda u: GOOD, cache_dir=str(tmp_path), tz=TZ)
    got = ical.get_events(URL, FRI, fetch=lambda u: b"<html>Sign in</html>", cache_dir=str(tmp_path), tz=TZ)
    assert [e["title"] for e in got] == ["Standup"]
    assert b"VCALENDAR" in (tmp_path / "calendar.ics").read_bytes()


def test_get_events_stale_cache_gives_nothing(tmp_path):
    ical.get_events(URL, FRI, fetch=lambda u: GOOD, cache_dir=str(tmp_path), tz=TZ)
    mtime = os.path.getmtime(tmp_path / "calendar.ics")
    assert ical.get_events(URL, FRI, fetch=boom, cache_dir=str(tmp_path), tz=TZ,
                           clock=lambda: mtime + 25 * 3600) == []


def test_get_events_no_cache_and_no_network(tmp_path):
    assert ical.get_events(URL, FRI, fetch=boom, cache_dir=str(tmp_path), tz=TZ) == []
    assert ical.get_events("", FRI, fetch=lambda u: GOOD, cache_dir=str(tmp_path), tz=TZ) == []


def test_get_events_never_raises_on_garbage(tmp_path):
    for junk in (b"\xff\xfe\x00garbage", b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:99999999T999999\nEND:VEVENT",
                 None, 42):
        assert ical.get_events(URL, FRI, fetch=lambda u, j=junk: j, cache_dir=str(tmp_path), tz=TZ) == []
    assert ical.get_events(URL, FRI, fetch=lambda u: GOOD, cache_dir=str(tmp_path / "f" / "\0bad"), tz=TZ) \
        == [{"time": "10:00", "end": None, "title": "Standup"}]


def test_secret_url_is_not_logged(tmp_path, caplog):
    with caplog.at_level("DEBUG"):
        ical.get_events(URL, FRI, fetch=boom, cache_dir=str(tmp_path), tz=TZ)
    assert "private-secret" not in caplog.text


def test_old_count_rule_is_counted_without_walking_and_still_correct():
    # Weekly since 2016 with COUNT big enough to reach today / too small to reach today
    reach = cal(ev("Long", "DTSTART:20160101T090000", "RRULE:FREQ=WEEKLY;BYDAY=FR;COUNT=1000"))
    short = cal(ev("Short", "DTSTART:20160101T090000", "RRULE:FREQ=WEEKLY;BYDAY=FR;COUNT=560"))
    assert titles(reach) == ["Long"] and titles(short) == []
