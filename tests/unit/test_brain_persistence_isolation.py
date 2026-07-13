"""The web app and the desktop agent must not fight over memory.json.

web_app constructs a Brain per HTTP request from browser-supplied history.  When
that Brain persisted, each request force-wrote the browser's history over the
long-lived desktop agent's memory — unsynchronised last-writer-wins on one file.
"""
import json

import pytest

import core.llm as llm


@pytest.fixture
def memfile(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    monkeypatch.setattr(llm, "MEMORY_FILE", str(path))
    return path


def _brain(persist):
    """Build a Brain without the network warmup __init__ would otherwise do."""
    b = llm.Brain.__new__(llm.Brain)
    b.persist = persist
    b.history = []
    b._save_dirty = False
    b._last_save_at = 0.0
    b._save_min_interval_s = 0.0
    return b


def test_non_persisting_brain_never_writes_memory_file(memfile):
    b = _brain(persist=False)
    b.history = [{"role": "user", "content": "from the browser"}]
    b.save_history(force=True)
    assert not memfile.exists()


def test_persisting_brain_writes_memory_file(memfile):
    b = _brain(persist=True)
    b.history = [{"role": "user", "content": "from the robot"}]
    b.save_history(force=True)
    assert json.loads(memfile.read_text()) == [{"role": "user", "content": "from the robot"}]


def test_web_brain_cannot_clobber_agent_memory(memfile):
    agent = _brain(persist=True)
    agent.history = [{"role": "user", "content": "agent memory"}]
    agent.save_history(force=True)

    web = _brain(persist=False)
    web.set_history([{"role": "user", "content": "browser memory"}])  # force-saves internally

    assert json.loads(memfile.read_text()) == [{"role": "user", "content": "agent memory"}]


def test_set_history_still_installs_system_prompt(memfile):
    web = _brain(persist=False)
    web.set_history([{"role": "user", "content": "hi"}])
    assert web.history[0]["role"] == "system"
