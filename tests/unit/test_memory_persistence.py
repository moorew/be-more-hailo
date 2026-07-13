"""memory.json durability.

BMO runs 24/7 off an SD card and gets power-cut, not shut down.  A truncated or
non-list memory file must never take the robot down on next boot.
"""
import json

import pytest

import core.llm as llm


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A Brain whose memory file lives in a temp dir, with no network at init."""
    monkeypatch.setattr(llm, "MEMORY_FILE", str(tmp_path / "memory.json"))
    b = llm.Brain.__new__(llm.Brain)  # bypass __init__ (it warms the LLM)
    b.history = []
    b._save_dirty = False
    b._last_save_at = 0.0
    b._save_min_interval_s = 0.0
    return b


def test_save_then_load_roundtrip(brain):
    brain.history = [{"role": "user", "content": "hi"}]
    brain.save_history(force=True)
    brain.history = []
    brain.load_history()
    assert brain.history == [{"role": "user", "content": "hi"}]


def test_save_leaves_no_temp_file_behind(brain, tmp_path):
    brain.history = [{"role": "user", "content": "hi"}]
    brain.save_history(force=True)
    assert not (tmp_path / "memory.json.tmp").exists()


def test_save_is_atomic_no_partial_file_on_serialisation_failure(brain, tmp_path):
    brain.history = [{"role": "user", "content": "good"}]
    brain.save_history(force=True)

    # An unserialisable object must not clobber the previously-good file.
    brain.history = [{"role": "user", "content": object()}]
    brain.save_history(force=True)  # logs, does not raise

    with open(tmp_path / "memory.json") as f:
        assert json.load(f) == [{"role": "user", "content": "good"}]


def test_truncated_file_recovers_to_empty_history(brain, tmp_path):
    (tmp_path / "memory.json").write_text('[{"role": "user", "cont')
    brain.load_history()
    assert brain.history == []


def test_valid_json_that_is_not_a_message_list_is_rejected(brain, tmp_path):
    # Would otherwise crash later at history[0].get(...)
    (tmp_path / "memory.json").write_text('{"role": "user"}')
    brain.load_history()
    assert brain.history == []


def test_list_of_non_dicts_is_rejected(brain, tmp_path):
    (tmp_path / "memory.json").write_text('["hello", "world"]')
    brain.load_history()
    assert brain.history == []


def test_missing_file_leaves_history_untouched(brain):
    brain.history = [{"role": "system", "content": "s"}]
    brain.load_history()
    assert brain.history == [{"role": "system", "content": "s"}]


def test_save_is_throttled_unless_forced(brain, tmp_path):
    import time
    brain._save_min_interval_s = 3600
    brain._last_save_at = time.time()
    brain.history = [{"role": "user", "content": "throttled"}]
    brain.save_history()  # not forced → skipped
    assert not (tmp_path / "memory.json").exists()
    brain.save_history(force=True)
    assert (tmp_path / "memory.json").exists()
