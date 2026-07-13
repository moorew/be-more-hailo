"""Parsing of the JSON actions the model emits (set_timer, display_image, …).

A dropped action means BMO silently ignores "set a timer for 10 minutes"; a
mis-parsed span means fragments of JSON get spoken aloud.
"""
from core.llm import extract_json_object


def test_extracts_simple_action():
    parsed, span = extract_json_object('{"action": "take_photo"}')
    assert parsed == {"action": "take_photo"}
    assert span == (0, 24)


def test_extracts_action_embedded_in_speech():
    text = 'Sure thing! {"action": "set_timer", "minutes": 10} Timer set.'
    parsed, span = extract_json_object(text)
    assert parsed["action"] == "set_timer" and parsed["minutes"] == 10
    # The span must let the caller excise exactly the JSON, leaving clean speech.
    assert (text[:span[0]] + text[span[1]:]).strip() == "Sure thing!  Timer set."


def test_handles_nested_objects():
    parsed, _ = extract_json_object('{"action": "x", "opts": {"a": {"b": 1}}}')
    assert parsed["opts"]["a"]["b"] == 1


def test_braces_inside_strings_do_not_break_balance():
    parsed, _ = extract_json_object('{"action": "say", "message": "use {curly} braces"}')
    assert parsed["message"] == "use {curly} braces"


def test_escaped_quote_inside_string():
    parsed, _ = extract_json_object(r'{"action": "say", "message": "she said \"hi\""}')
    assert parsed["message"] == 'she said "hi"'


def test_skips_malformed_object_and_finds_the_next_valid_one():
    parsed, _ = extract_json_object('{not json} then {"action": "play_music"}')
    assert parsed == {"action": "play_music"}


def test_returns_none_when_no_object_present():
    assert extract_json_object("just talking") == (None, None)


def test_returns_none_for_unclosed_object():
    assert extract_json_object('{"action": "set_timer"') == (None, None)


def test_empty_input():
    assert extract_json_object("") == (None, None)


def test_multiple_actions_can_be_drained_in_sequence():
    # _handle_response_chunk loops until no object remains; simulate that here so
    # a second action (e.g. set_timer after set_expression) is never lost.
    chunk = '{"action": "set_expression", "value": "happy"} Okay! {"action": "set_timer", "minutes": 5}'
    found = []
    while True:
        parsed, span = extract_json_object(chunk)
        if parsed is None:
            break
        found.append(parsed["action"])
        chunk = (chunk[:span[0]] + chunk[span[1]:]).strip()
    assert found == ["set_expression", "set_timer"]
    assert chunk == "Okay!"
