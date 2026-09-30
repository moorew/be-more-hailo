"""Prompt must fit hailo-ollama's fixed context or the stream is dropped."""

from core.llm import _fit_context


def _conv(n_pairs, size=500):
    msgs = [{"role": "system", "content": "s" * 1000}]
    for i in range(n_pairs):
        msgs.append({"role": "user", "content": f"q{i}".ljust(size, ".")})
        msgs.append({"role": "assistant", "content": f"a{i}".ljust(size, ".")})
    msgs.append({"role": "user", "content": "latest"})
    return msgs


def _chars(msgs):
    return sum(len(m["content"]) for m in msgs)


def test_short_history_untouched():
    msgs = _conv(2)
    assert _fit_context(msgs, budget=10_000) == msgs


def test_long_history_trimmed_under_budget():
    out = _fit_context(_conv(10), budget=4500)
    assert _chars(out) <= 4500
    assert out[0]["role"] == "system"
    assert out[-1]["content"] == "latest"


def test_trimmed_history_starts_on_user_turn():
    out = _fit_context(_conv(10), budget=3200)
    assert out[1]["role"] == "user"
    roles = [m["role"] for m in out[1:]]
    assert all(a != b for a, b in zip(roles, roles[1:]))


def test_last_message_kept_even_if_oversized():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "x" * 9000}]
    assert _fit_context(msgs, budget=4500) == msgs


def test_does_not_mutate_input():
    msgs = _conv(10)
    before = list(msgs)
    _fit_context(msgs, budget=3000)
    assert msgs == before
