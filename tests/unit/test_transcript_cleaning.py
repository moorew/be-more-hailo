"""Whisper output cleaning.

Two jobs: normalise the many ways Whisper spells "BMO", and drop the phantom
phrases Whisper emits for silence — an unfiltered hallucination makes BMO wake
up and answer a question nobody asked.
"""
import pytest

from core.stt import _clean_transcript


@pytest.mark.parametrize("heard", ["Bemo", "beemo", "BEAMO", "PMO", "B.M.O.", "b m o"])
def test_name_variants_normalise_to_bmo(heard):
    assert "BMO" in _clean_transcript(f"Hey {heard}, hello")


def test_real_word_containing_name_is_not_mangled():
    assert _clean_transcript("The bemoaned robot") == "The bemoaned robot"


@pytest.mark.parametrize("phantom", [
    "[silence]", "(silence)", "Thanks for watching!", "[BLANK_AUDIO]",
    "Thank you.", "you", "  ",
    "Subscribe to our channel for more videos!", "[Music]",
])
def test_hallucinations_are_filtered_to_empty(phantom):
    assert _clean_transcript(phantom) == ""


def test_parenthetical_only_output_is_filtered():
    assert _clean_transcript("(wind blowing)") == ""


def test_bracketed_timestamps_are_stripped():
    assert _clean_transcript("[00:00.000 --> 00:02.000] Hello there") == "Hello there"


def test_punctuation_only_is_filtered():
    assert _clean_transcript("...") == ""


def test_ordinary_speech_survives():
    assert _clean_transcript("What is the weather today?") == "What is the weather today?"


def test_real_sentence_mentioning_channel_is_kept():
    assert _clean_transcript("Change the channel please") == "Change the channel please"


def test_cpu_whisper_is_given_the_prompt(monkeypatch):
    """base.en heard "weather doing tomorrow" as "method doing to Murray" without it."""
    import core.stt as stt
    seen = {}

    def fake_check_output(cmd, **kw):
        seen["cmd"] = cmd
        return b" What's the weather doing tomorrow?"
    monkeypatch.setattr(stt.subprocess, "check_output", fake_check_output)
    assert stt._transcribe_cpu("x.wav") == "What's the weather doing tomorrow?"
    i = seen["cmd"].index("--prompt")
    assert seen["cmd"][i + 1] == stt.WHISPER_PROMPT and "weather" in stt.WHISPER_PROMPT
