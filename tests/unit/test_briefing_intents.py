"""Asking for the briefing by voice.  Whole-utterance matches only, so
"good morning, what's the weather?" still gets the normal weather answer."""
import json

import pytest

from core.briefing.intents import BRIEFING, GOOD_MORNING, match
from core.llm import Brain


@pytest.mark.parametrize("text", [
    "Good morning!", "Good morning, BMO.", "Hey BMO, good morning friend!", "Morning!",
    "Good morning to you!", "B-M-O good morning",
])
def test_good_morning(text):
    assert match(text) == GOOD_MORNING


@pytest.mark.parametrize("text", [
    "Morning briefing.", "BMO, morning briefing please", "Can you show me my briefing?",
    "Show me the briefing", "Play my morning briefing again", "Give me the rundown", "Brief me.",
    "What's my day look like?", "What does my day look like today?", "How's my day looking?",
    "Catch me up", "Tell me about my day", "Could you read me today's briefing", "I want my briefing",
])
def test_briefing_requests(text):
    assert match(text) == BRIEFING


@pytest.mark.parametrize("text", [
    "Good morning, what's the weather?", "good morning bmo can you tell me a joke",
    "Show me a picture of a briefing", "What's the news?", "Tell me about the morning",
    "What's the weather like this morning?", "Thank you BMO", "", "Set a timer for 5 minutes",
])
def test_everything_else_is_left_alone(text):
    assert match(text) is None


def brain(ready):
    b = Brain(persist=False)
    b.briefing_ready = ready
    return b


def test_brain_routes_briefing_requests_without_the_llm():
    action = '{"action": "play_briefing"}'
    assert brain(lambda: False).think("Show me my briefing") == action
    assert list(brain(lambda: False).stream_think("morning briefing please")) == [action]
    assert brain(lambda: True).think("Good morning BMO!") == action           # ready and unplayed


def test_good_morning_only_plays_a_waiting_briefing():
    assert brain(lambda: True)._briefing_action("Good morning!") is not None
    assert brain(lambda: False)._briefing_action("Good morning!") is None     # BMO just chats


def test_no_routing_without_the_agent():
    # web_app / cli: no briefing_ready set, so nothing changes there.
    assert Brain(persist=False)._briefing_action("morning briefing") is None


def test_brain_routes_dated_reminders():
    out = Brain(persist=False).think("Remind me tomorrow at 9 to put the bins out")
    spoken, action = out.split(" {", 1)
    assert spoken == "Okay friend! I'll remind you tomorrow at 9 a.m. to put the bins out."
    payload = json.loads("{" + action)
    assert payload["action"] == "set_reminder" and payload["message"] == "Put the bins out!"


def test_alarm_and_bare_reminder_confirmations():
    b = Brain(persist=False)
    assert b._reminder_reply("Set an alarm for 6am")[0].startswith("Okay friend! I set an alarm for ")
    assert b._reminder_reply("Set an alarm for 6am")[0].endswith("at 6 a.m.")
    assert b._reminder_reply("Set a reminder for Monday at 10am")[0].endswith(" at 10 a.m.")
