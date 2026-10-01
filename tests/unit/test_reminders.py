"""The reminder registry behind "your day" and timers that survive a reboot.

A lost entry means a timer silently never fires after a restart; a stale one
means a burst of old alarms the moment BMO boots.
"""
import json

from core.reminders import ReminderRegistry


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_add_fire_and_cancel(tmp_path):
    reg = ReminderRegistry(str(tmp_path / "r.json"), clock=Clock())
    a = reg.add(1_000_600, "Stir the soup!")
    b = reg.add(1_000_300, "Call mum!")
    assert [r["message"] for r in reg.pending()] == ["Call mum!", "Stir the soup!"]  # soonest first
    assert reg.remove(b) is True           # fired
    assert reg.remove(b) is False          # already gone
    assert [r["id"] for r in reg.pending()] == [a]
    assert reg.remove(a) and reg.pending() == []


def test_survives_a_reload(tmp_path):
    path = str(tmp_path / "r.json")
    rid = ReminderRegistry(path, clock=Clock()).add(1_000_600, "Stir the soup!", kind="timer")
    again = ReminderRegistry(path, clock=Clock())
    assert again.get(rid)["message"] == "Stir the soup!"
    assert again.get(rid)["due"] == 1_000_600


def test_due_between_is_half_open(tmp_path):
    reg = ReminderRegistry(str(tmp_path / "r.json"), clock=Clock())
    reg.add(100, "a"), reg.add(200, "b"), reg.add(300, "c")
    assert [r["message"] for r in reg.due_between(100, 300)] == ["a", "b"]


def test_prune_past_drops_and_returns_missed(tmp_path):
    path = str(tmp_path / "r.json")
    clock = Clock(1_000_000)
    reg = ReminderRegistry(path, clock=clock)
    reg.add(999_000, "missed while off")
    keep = reg.add(1_000_500, "still to come")
    dropped = reg.prune_past()
    assert [r["message"] for r in dropped] == ["missed while off"]
    assert [r["id"] for r in ReminderRegistry(path, clock=clock).pending()] == [keep]


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{not json")
    reg = ReminderRegistry(str(path), clock=Clock())
    assert reg.pending() == []
    reg.add(5, "x")
    assert len(json.loads(path.read_text())) == 1
