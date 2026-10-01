"""Timer/reminder parsing.

A missed timer is a broken promise ("BMO will happily interrupt you later"), and
a phantom timer is worse — BMO shouting at you about a timer you never set.
"""
import pytest

from core.timers import MAX_MINUTES, MIN_MINUTES, describe_duration, parse_timer_request


@pytest.mark.parametrize("text,minutes", [
    ("Set a timer for 10 minutes", 10),
    ("set a timer for 1 minute", 1),
    ("Remind me in 30 seconds to stir the soup", 0.5),
    ("set an alarm for 2 hours", 120),
    ("timer for 90 mins", 90),
    ("Set a timer for five minutes", 5),
    ("remind me in an hour to call mum", 60),
    ("set a timer for 1.5 minutes", 1.5),
    ("timer for 45 s", 0.75),
])
def test_duration_and_unit_are_parsed(text, minutes):
    assert parse_timer_request(text)["minutes"] == pytest.approx(minutes)


def test_reminder_subject_becomes_the_message():
    assert parse_timer_request("Remind me in 30 seconds to stir the soup")["message"] == "Stir the soup!"


def test_timer_without_subject_gets_default_message():
    assert parse_timer_request("Set a timer for 10 minutes")["message"] == "Timer is up!"


def test_subject_after_duration_is_preferred():
    r = parse_timer_request("set a timer for 10 minutes to check the oven")
    assert r["minutes"] == 10 and r["message"] == "Check the oven!"


@pytest.mark.parametrize("text", [
    "What is the weather today?",
    "Set the mood please",
    "How many minutes until dinner?",   # duration word, no trigger
    "Set a timer",                       # trigger, no duration
    "",
])
def test_non_timer_utterances_return_none(text):
    assert parse_timer_request(text) is None


def test_duration_is_clamped_to_safe_bounds():
    assert parse_timer_request("set a timer for 9999 hours")["minutes"] == MAX_MINUTES
    assert parse_timer_request("set a timer for 1 second")["minutes"] >= MIN_MINUTES


def test_zero_duration_is_rejected():
    assert parse_timer_request("set a timer for 0 minutes") is None


def test_case_insensitive():
    assert parse_timer_request("SET A TIMER FOR 5 MINUTES")["minutes"] == 5


@pytest.mark.parametrize("minutes,expected", [
    (0.5, "30 seconds"), (1, "1 minute"), (10, "10 minutes"),
    (60, "1 hour"), (120, "2 hours"),
])
def test_describe_duration(minutes, expected):
    assert describe_duration(minutes) == expected


# --- reminders for a clock time or a day ---------------------------------------
import datetime as dt  # noqa: E402

from core.timers import describe_when, parse_reminder_request  # noqa: E402

THU_5PM = dt.datetime(2026, 10, 1, 17, 5)


def _due(text, now=THU_5PM):
    r = parse_reminder_request(text, now)
    return r and (dt.datetime.fromtimestamp(r["due"]).strftime("%a %H:%M"), r["message"])


@pytest.mark.parametrize("text,due,message", [
    ("Remind me tomorrow at 9 to put the bins out", "Fri 09:00", "Put the bins out!"),
    ("remind me at 3:30pm to call mum", "Fri 15:30", "Call mum!"),            # 3:30 p.m. has passed today
    ("Remind me on Friday to call the dentist", "Fri 09:00", "Call the dentist!"),
    ("set an alarm for 7am", "Fri 07:00", "Alarm!"),
    ("remind me to call mum tomorrow at 5", "Fri 17:00", "Call mum!"),          # 1-6 means p.m.
    ("remind me at 9 to take my pills", "Thu 21:00", "Take my pills!"),         # next 9 o'clock
    ("remind me tonight at 8 to water the plants", "Thu 20:00", "Water the plants!"),
    ("Remind me next Thursday to pay rent", "Thu 09:00", "Pay rent!"),
    ("remind me at noon tomorrow to eat lunch", "Fri 12:00", "Eat lunch!"),
    ("remind me tomorrow morning to buy milk", "Fri 09:00", "Buy milk!"),
    ("remind me at nine thirty to call dad", "Thu 21:30", "Call dad!"),
    ("set a reminder for Monday at 10 a.m. about the vet", "Mon 10:00", "The vet!"),
])
def test_reminder_parsing(text, due, message):
    assert _due(text) == (due, message)


def test_next_weekday_means_next_week_on_that_day():
    r = parse_reminder_request("Remind me next Thursday to pay rent", THU_5PM)
    assert dt.datetime.fromtimestamp(r["due"]).date() == dt.date(2026, 10, 8)


@pytest.mark.parametrize("text", [
    "remind me in 10 minutes to stir the soup",   # a timer
    "What time is it at 9?",                     # no trigger
    "remind me to call mum",                     # no time or day
])
def test_not_a_dated_reminder(text):
    assert parse_reminder_request(text, THU_5PM) is None


def test_am_is_not_a_minute():
    # "am" used to read as "a" (one) + "m" (minute): a one-minute timer.
    assert parse_timer_request("set an alarm for 7am") is None
    assert parse_timer_request("set an alarm for 7 a.m.") is None
    assert parse_timer_request("set a timer for 5m")["minutes"] == 5


@pytest.mark.parametrize("due,said", [
    (dt.datetime(2026, 10, 1, 21, 0), "tonight at 9 p.m."),
    (dt.datetime(2026, 10, 1, 17, 30), "today at 5:30 p.m."),
    (dt.datetime(2026, 10, 2, 9, 0), "tomorrow at 9 a.m."),
    (dt.datetime(2026, 10, 2, 12, 0), "tomorrow at noon"),
    (dt.datetime(2026, 10, 5, 10, 0), "on Monday at 10 a.m."),
    (dt.datetime(2026, 10, 12, 9, 0), "on Monday, October 12 at 9 a.m."),
])
def test_describe_when(due, said):
    assert describe_when(due.timestamp(), THU_5PM) == said
