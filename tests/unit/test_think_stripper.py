"""Reasoning-token filtering for the streaming voice path.

qwen3 emits <think>…</think> chain-of-thought. strip_prompt_leakage() only ever
sees one sentence-buffer, so it cannot tell that reasoning begun in an earlier
buffer is still running — the bug this filter exists to prevent is BMO reciting
its own reasoning out loud.
"""
import pytest

from core.llm import ThinkStripper, strip_think_blocks


def feed_all(chunks):
    """Run chunks through a stripper and return everything it emitted."""
    s = ThinkStripper()
    out = "".join(s.feed(c) for c in chunks)
    return out + s.flush()


def test_reasoning_never_escapes_across_chunk_boundaries():
    # The regression: only the first chunk carries "<think>"; later reasoning
    # sentences look like ordinary prose and used to be spoken aloud.
    chunks = [
        "<think>Okay, the user greeted me. ",
        "I should respond warmly. ",
        "Keep it short.</think>",
        "Hi there, friend!",
    ]
    assert feed_all(chunks) == "Hi there, friend!"


def test_tag_split_across_chunks_is_still_detected():
    assert feed_all(["<thi", "nk>secret", "</thi", "nk>", "visible"]) == "visible"


def test_text_before_and_after_reasoning_is_kept():
    assert feed_all(["before <think>hidden</think> after"]) == "before  after"


def test_unclosed_reasoning_is_dropped_not_spoken():
    # Model cut off mid-thought: emitting the partial reasoning would be worse
    # than saying nothing.
    assert feed_all(["<think>I was cut off mid-th"]) == ""


def test_stream_without_reasoning_passes_through_verbatim():
    assert feed_all(["Hello ", "world", "!"]) == "Hello world!"


def test_multiple_reasoning_blocks():
    assert feed_all(["<think>a</think>one <think>b</think>two"]) == "one two"


def test_lone_angle_bracket_is_not_held_forever():
    # "<" could start "<think>", but flush() must release it once the stream ends.
    assert feed_all(["5 < 6"]) == "5 < 6"


def test_in_think_state_is_observable():
    s = ThinkStripper()
    s.feed("<think>reasoning")
    assert s.in_think is True
    s.feed("</think>done")
    assert s.in_think is False


@pytest.mark.parametrize("case", ["<THINK>x</THINK>ok", "<Think>x</Think>ok"])
def test_tags_are_case_insensitive(case):
    assert feed_all([case]) == "ok"


class TestStripThinkBlocks:
    """Whole-reply stripping, used before a turn is persisted to history."""

    def test_removes_complete_block(self):
        assert strip_think_blocks("<think>reasoning</think>Hello!") == "Hello!"

    def test_removes_unclosed_block_and_trailing_text(self):
        assert strip_think_blocks("Hi <think>cut off") == "Hi"

    def test_leaves_ordinary_text_untouched(self):
        assert strip_think_blocks("Just a normal reply.") == "Just a normal reply."

    def test_empty_input(self):
        assert strip_think_blocks("") == ""
