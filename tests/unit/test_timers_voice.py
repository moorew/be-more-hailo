"""Named timers, asking about / cancelling timers and reminders, and the
chips that show running timers on screen."""
import time

import pytest

from core.llm import Brain
from core.reminders import ReminderRegistry
from core.timer_chips import TimerChips, countdown
from core.timers import match_reminders, parse_reminder_query, parse_timer_request


@pytest.mark.parametrize("text,name", [
    ("Set a pasta timer for 10 minutes", "pasta"), ("set an egg timer for 6 minutes", "egg"),
    ("set a laundry timer for an hour", "laundry"), ("set a 10 minute timer", None),
    ("set a timer for five minutes", None), ("set a quick timer for 2 minutes", None),
])
def test_timer_names(text, name):
    t = parse_timer_request(text)
    assert t.get("name") == name
    if name:
        assert t["message"] == f"The {name} timer is done!"


@pytest.mark.parametrize("text,query", [
    ("What reminders do I have?", {"action": "list"}),
    ("what timers are running", {"action": "list"}),
    ("Do I have any reminders?", {"action": "list"}),
    ("Cancel the pasta timer", {"action": "cancel", "target": "pasta", "all": False}),
    ("cancel my reminder about the bins", {"action": "cancel", "target": "bins", "all": False}),
    ("cancel all my timers", {"action": "cancel", "target": None, "all": True}),
    ("How long left on the pasta timer?", {"action": "left", "target": "pasta"}),
    ("How much time is left on the timer", {"action": "left", "target": None}),
    ("cancel my appointment", None), ("what time is it", None), ("how long is the movie", None),
])
def test_reminder_queries(text, query):
    assert parse_reminder_query(text) == query


def brain(tmp_path, now=None):
    b = Brain(persist=False)
    b.reminders = ReminderRegistry(str(tmp_path / "r.json"))
    return b


def test_list_left_and_cancel(tmp_path):
    b = brain(tmp_path)
    now = time.time()
    pasta = b.reminders.add(now + 250, "The pasta timer is done!", name="pasta")
    b.reminders.add(now + 20 * 3600, "Put the bins out!", kind="reminder")
    listed = b._instant_reply("What reminders do I have?")
    assert listed.startswith("You have 2 things set: the pasta timer has 4 minutes left; "
                             "your reminder to put the bins out is ")
    assert not listed.endswith("..")
    assert b._instant_reply("How long left on the pasta timer?") == "The pasta timer has 4 minutes left."
    assert b._instant_reply("Cancel the pasta timer") == "Okay, I cancelled the pasta timer."
    assert b.reminders.get(pasta) is None
    assert b._instant_reply("cancel the pasta timer") == "Hmm, BMO couldn't find that one."


def test_ambiguous_cancel_asks_which(tmp_path):
    b = brain(tmp_path)
    b.reminders.add(time.time() + 100, "The pasta timer is done!", name="pasta")
    b.reminders.add(time.time() + 200, "The egg timer is done!", name="egg")
    assert b._instant_reply("cancel the timer") == "Which one? You have the pasta timer or the egg timer."
    assert b._instant_reply("cancel all timers") == "Okay! Everything's cancelled."
    assert b.reminders.pending() == []


def test_no_registry_means_no_routing():
    assert Brain(persist=False)._reminder_query_reply("What reminders do I have?") is None


def test_instant_answers_route_before_the_llm(tmp_path):
    b = brain(tmp_path)
    assert b._instant_reply("what is 15% of 80") == "15 percent of 80 is 12."
    assert b._instant_reply("tell me a joke") is None


def test_home_assistant_is_asked_last(tmp_path):
    b = brain(tmp_path)

    class Home:
        def handle(self, text):
            return "Okay! Kitchen lights are off." if "kitchen" in text else None
    b.home = Home()
    assert b._instant_reply("turn off the kitchen lights") == "Okay! Kitchen lights are off."
    assert b._instant_reply("what time is it").startswith("It's ")


@pytest.mark.parametrize("secs,text", [(272, "4:32"), (8.2, "0:09"), (3725, "1:02:05"), (0.2, "0:01")])
def test_countdown(secs, text):
    assert countdown(secs) == text


def test_chips_show_running_timers_not_reminders(tmp_path):
    from PIL import Image
    reg = ReminderRegistry(str(tmp_path / "r.json"))
    chips = TimerChips(reg, clock=lambda: 1000.0)
    blank = Image.new("RGB", (800, 480), "#C9E4C3")
    assert chips.apply(blank.copy(), 1000.0).tobytes() == blank.tobytes()
    reg.add(1000 + 20 * 3600, "Bins!", kind="reminder")          # a reminder: no chip
    chips._items_at = -1
    assert chips.apply(blank.copy(), 1000.0).tobytes() == blank.tobytes()
    reg.add(1000 + 300, "The pasta timer is done!", name="pasta")
    chips._items_at = -1
    assert chips.apply(blank.copy(), 1000.0).getpixel((40, 28)) != blank.getpixel((40, 28))


def test_match_reminders_prefers_names():
    items = [{"id": 1, "name": "pasta", "message": "x"}, {"id": 2, "message": "Put the pasta water on!"}]
    assert [r["id"] for r in match_reminders(items, "pasta")] == [1]
    assert [r["id"] for r in match_reminders(items, "water")] == [2]
