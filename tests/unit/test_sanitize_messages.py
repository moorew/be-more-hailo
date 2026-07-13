"""hailo-ollama's qwen3 prompt renderer rejects control characters in JSON
strings and 500s the request.  Newlines were the first offender; ANSI escapes
from wttr.in weather output and search snippets are the same class of bug.
"""
from core.llm import sanitize_messages


def content_of(messages):
    return [m["content"] for m in sanitize_messages(messages)]


def test_newlines_become_spaces():
    assert content_of([{"role": "user", "content": "Title: x\nSnippet: y"}]) == ["Title: x Snippet: y"]


def test_ansi_escape_sequences_are_removed():
    # wttr.in colourises its output; \x1b survives a naive \s+ collapse.
    weather = "Brantford: \x1b[38;5;226mSunny\x1b[0m 21C"
    assert "\x1b" not in content_of([{"role": "user", "content": weather}])[0]


def test_all_control_characters_are_removed():
    raw = "a\tb\rc\x00d\x07e"
    cleaned = content_of([{"role": "user", "content": raw}])[0]
    assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in cleaned)


def test_role_and_extra_keys_are_preserved():
    out = sanitize_messages([{"role": "system", "content": "hi", "name": "bmo"}])
    assert out == [{"role": "system", "content": "hi", "name": "bmo"}]


def test_non_string_content_does_not_crash():
    out = sanitize_messages([{"role": "user", "content": None}])
    assert out[0]["content"] is None


def test_ordinary_text_is_unchanged():
    assert content_of([{"role": "user", "content": "Hello BMO!"}]) == ["Hello BMO!"]


def test_input_is_not_mutated():
    original = {"role": "user", "content": "a\nb"}
    sanitize_messages([original])
    assert original["content"] == "a\nb"
