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
