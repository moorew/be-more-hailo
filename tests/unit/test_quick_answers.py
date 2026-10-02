"""Instant answers for time, date, countdowns, arithmetic and unit conversions.

A wrong "no" just costs a few seconds of LLM time; a wrong "yes" hijacks a real
conversation.  So the negatives below matter as much as the positives.
"""
import datetime

import pytest

from core.quick_answers import answer

NOW = datetime.datetime(2026, 10, 2, 15, 42)     # a Friday afternoon


def ask(text, now=NOW):
    return answer(text, now)


# ------------------------------------------------------------------ time

@pytest.mark.parametrize("text", [
    "what time is it",
    "What time is it?",
    "what's the time",
    "What is the time?",
    "time please",
    "Hey BMO, what time is it?",
    "BMO what time is it right now",
    "do you know what time it is",
    "can you tell me the time please",
    "what time is it now",
])
def test_time_questions(text):
    assert ask(text) == "It's 3:42 p.m."


@pytest.mark.parametrize("now,reply", [
    (datetime.datetime(2026, 10, 2, 15, 0), "It's 3 p.m."),
    (datetime.datetime(2026, 10, 2, 9, 5), "It's 9:05 a.m."),
    (datetime.datetime(2026, 10, 2, 0, 30), "It's 12:30 a.m."),
    (datetime.datetime(2026, 10, 2, 12, 0), "It's 12 p.m."),
])
def test_time_format(now, reply):
    assert ask("what time is it", now) == reply


# ------------------------------------------------------------------ date

@pytest.mark.parametrize("text", [
    "what's the date",
    "what's today's date",
    "what is the date today",
    "what day is it",
    "what day is it today",
    "hey bmo, do you know what day it is?",
])
def test_date_questions(text):
    assert ask(text) == "It's Friday, October 2nd."


@pytest.mark.parametrize("day,ordinal", [(1, "1st"), (11, "11th"), (12, "12th"), (13, "13th"),
                                         (21, "21st"), (22, "22nd"), (23, "23rd"), (31, "31st")])
def test_date_ordinals(day, ordinal):
    assert ask("what's the date", datetime.datetime(2026, 10, day, 9)).endswith(f"October {ordinal}.")


def test_year_and_month():
    assert ask("what year is it?") == "It's 2026."
    assert ask("what month is it") == "It's October."


# ------------------------------------------------------------------ days until

@pytest.mark.parametrize("text,reply", [
    ("how many days until Christmas", "Christmas is in 84 days!"),
    ("how many days till christmas?", "Christmas is in 84 days!"),
    ("how many sleeps until christmas", "Christmas is in 84 days!"),
    ("how long until Halloween", "Halloween is in 29 days!"),
    ("how many days until October 31st", "October 31st is in 29 days!"),
    ("how many days until december 25", "December 25th is in 84 days!"),
    ("days until the 3rd of october", "October 3rd is tomorrow!"),
    ("how many days until new year's", "New Year's Day is in 91 days!"),
    ("how long until the new year", "New Year's Day is in 91 days!"),
    ("how many days until thanksgiving", "Thanksgiving is in 10 days!"),     # 2nd Monday of Oct 2026
    ("how many days until canada day", "Canada Day is in 272 days!"),        # already passed: next year
    ("how many days until easter", "Easter is in 177 days!"),                # 28 March 2027
    ("how many days until valentine's", "Valentine's Day is in 135 days!"),
    ("how long until christmas eve", "Christmas Eve is in 83 days!"),
])
def test_days_until(text, reply):
    assert ask(text) == reply


def test_days_until_today_and_tomorrow():
    assert ask("how many days until halloween", datetime.datetime(2026, 10, 31, 8)) == "It's Halloween today!"
    assert ask("how many days until halloween", datetime.datetime(2026, 10, 30, 8)) == "Halloween is tomorrow!"
    assert ask("how many days until christmas", datetime.datetime(2026, 12, 25, 8)) == "It's Christmas today!"


def test_leap_day_countdown_skips_to_next_leap_year():
    assert ask("how many days until february 29th") == "February 29th is in 515 days!"   # 29 Feb 2028


@pytest.mark.parametrize("text", [
    "how many days until my birthday",
    "how long until the meeting",
    "how long until dinner",
    "how many days until february 30th",
    "how long to cook rice",
])
def test_unknown_countdown_targets_return_none(text):
    assert ask(text) is None


# ------------------------------------------------------------------ arithmetic

@pytest.mark.parametrize("text,reply", [
    ("what's 12 times 7", "12 times 7 is 84."),
    ("twelve times seven", "12 times 7 is 84."),
    ("what is 15 percent of 80", "15 percent of 80 is 12."),
    ("15% of 80", "15 percent of 80 is 12."),
    ("what's 144 divided by 12", "144 divided by 12 is 12."),
    ("what's 2 plus 2", "2 plus 2 is 4."),
    ("what's 2 + 2?", "2 plus 2 is 4."),
    ("square root of 81", "The square root of 81 is 9."),
    ("what's the square root of 2", "The square root of 2 is about 1.41."),
    ("what's 3 to the power of 4", "3 to the power of 4 is 81."),
    ("what's five squared", "5 squared is 25."),
    ("what's 7 minus 10", "7 minus 10 is -3."),
    ("what is 2 plus 3 times 4", "2 plus 3 times 4 is 14."),
    ("what's 10 divided by 3", "10 divided by 3 is about 3.33."),
    ("what's 1.5 times 4", "1.5 times 4 is 6."),
    ("what is one hundred and twenty plus five", "120 plus 5 is 125."),
    ("what is two thousand times three", "2000 times 3 is 6000."),
    ("what's 12 x 12", "12 times 12 is 144."),
    ("can you tell me what 12 times 12 is", "12 times 12 is 144."),
    ("what does 6 times 7 equal", "6 times 7 is 42."),
    ("calculate 100 minus 1", "100 minus 1 is 99."),
])
def test_arithmetic(text, reply):
    assert ask(text) == reply


@pytest.mark.parametrize("text", ["what is 5 divided by 0", "what's 0 divided by 0", "7 / 0"])
def test_divide_by_zero(text):
    assert ask(text) == "Even BMO can't divide by zero!"


@pytest.mark.parametrize("text", [
    "what's 2 plus 2 equals fish",
    "what is 5",                        # a number but no operation
    "what is a hundred",
    "what is x",
    "what is 2 plus",
    "what is 10 to the power of 1000",  # refuse absurd sizes rather than hang or overflow
    "what is the square root of negative 4",
    "two and three",
])
def test_bad_arithmetic_returns_none(text):
    assert ask(text) is None


# ------------------------------------------------------------------ units

@pytest.mark.parametrize("text,reply", [
    ("how many ml in a cup", "1 cup is 250 millilitres."),
    ("convert 5 miles to km", "5 miles is about 8.05 kilometres."),
    ("what's 70 fahrenheit in celsius", "70 degrees Fahrenheit is about 21 degrees Celsius."),
    ("100 degrees celsius in fahrenheit", "100 degrees Celsius is 212 degrees Fahrenheit."),
    ("convert -40 c to f", "-40 degrees Celsius is -40 degrees Fahrenheit."),
    ("how many grams in a pound", "1 pound is about 453.59 grams."),
    ("10 inches in cm", "10 inches is 25.4 centimetres."),
    ("3 tablespoons in teaspoons", "3 tablespoons is 9 teaspoons."),
    ("how many ounces in a kilogram", "1 kilogram is about 35.27 ounces."),
    ("how many ounces in a cup", "1 cup is about 8.45 fluid ounces."),         # volume, not weight
    ("how many feet in a mile", "1 mile is 5280 feet."),
    ("how many teaspoons are in a tablespoon", "1 tablespoon is 3 teaspoons."),
    ("how many gallons is 10 litres", "10 litres is about 2.64 gallons."),
    ("convert 2 litres to cups", "2 litres is 8 cups."),
    ("1 mile in km", "1 mile is about 1.61 kilometres."),
    ("what's two kilograms in pounds", "2 kilograms is about 4.41 pounds."),
    ("how many metres in a kilometre", "1 kilometre is 1000 metres."),
])
def test_unit_conversions(text, reply):
    assert ask(text) == reply


@pytest.mark.parametrize("text", [
    "convert 5 miles to kg",            # incompatible dimensions
    "how many miles to the moon",
    "how many cups of coffee did i drink",
    "convert 20 degrees to fahrenheit",  # no source scale
])
def test_bad_conversions_return_none(text):
    assert ask(text) is None


# ------------------------------------------------------------------ negatives

@pytest.mark.parametrize("text", [
    "what time do you go to bed",
    "tell me about the time machine",
    "what time does the store open",
    "what time is it in tokyo",
    "is it time for bed",
    "time to go",
    "what's the date tomorrow",
    "what's the weather",
    "what is love",
    "play some music",
    "set a timer for 5 minutes",
    "remind me tomorrow at 9",
    "good morning",
    "morning briefing",
    "how are you",
    "how many people live in canada",
    "one direction",
    "tell me a joke",
    "what day is your birthday",
    "",
    "   ",
])
def test_conversation_is_left_to_the_llm(text):
    assert ask(text) is None


def test_none_input_and_default_now():
    assert answer(None) is None
    assert answer("what time is it").startswith("It's ")
