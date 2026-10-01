"""The briefing's day on a fake clock: prepare early, icon + one chime at
window start, fade at window end, and nothing at all before the clock syncs.

A double chime or a briefing that fires at 03:00 on a stale clock is exactly
the kind of thing nobody notices until it wakes them up.
"""
import datetime
import os
import struct
import wave

import pytest

from core.briefing import audio, scheduler as sch

DAY = datetime.date(2026, 10, 1)          # a Thursday


def at(hhmm, day=DAY):
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.datetime.combine(day, datetime.time(h, m))


def fake_wav(text, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(22050)
        w.writeframes(struct.pack("<h", 1000) * 2205 * max(1, len(text) // 10))


PARTS = [{"key": "weather", "card": {}, "text": "Hi", "speech": "Hi there"},
         {"key": "signoff", "card": None, "text": "Bye", "speech": "Bye now"}]


class World:
    """A BMO on a fake clock."""

    def __init__(self, tmp_path, settings=None, synced=True, online=True):
        self.now = at("05:00")
        self.synced, self.online, self.idle = synced, online, True
        self.complete = True
        self.prepares, self.chimes, self.icon = [], 0, []
        self.settings = {"enabled": True, "days": sch.DAY_NAMES, "window": ["07:00", "11:00"],
                         "prepare_minutes_before": 30, "chime": True, **(settings or {})}
        self.root = str(tmp_path / "briefing")
        self.make()

    def make(self):
        """(Re)start BMO: a fresh scheduler over the same cache."""
        self.s = sch.BriefingScheduler(
            settings_fn=lambda: self.settings, prepare_fn=self.prepare, now_fn=lambda: self.now,
            clock_synced=lambda: self.synced, is_idle=lambda: self.idle,
            chime_fn=self.chime, on_icon=self.icon.append, cache_root=self.root)

    def prepare(self, now, settings):
        self.prepares.append(now.strftime("%H:%M"))
        if not self.online:
            return None
        return audio.render_briefing(PARTS, now.date(), cache_root=self.root,
                                     complete=self.complete, to_wav=fake_wav)

    def chime(self):
        self.chimes += 1

    def run_until(self, hhmm, day=DAY):
        """Tick every 30 s from now up to (not including) `hhmm`; returns the statuses seen."""
        seen = []
        end = at(hhmm, day)
        while self.now < end:
            st = self.s.tick()
            if not seen or seen[-1] != st:
                seen.append(st)
            self.now += datetime.timedelta(seconds=sch.TICK_S)
        return seen


def test_whole_day(tmp_path):
    w = World(tmp_path)
    assert w.run_until("06:30") == [sch.BEFORE]
    assert w.prepares == []
    assert w.run_until("07:00") == [sch.PREPARED]
    assert w.prepares == ["06:30"]                       # 30 minutes early, once
    assert os.path.exists(os.path.join(w.root, "2026-10-01", "script.json"))
    assert w.icon == [] and w.chimes == 0
    assert w.run_until("11:00") == [sch.READY]
    assert w.icon == [True] and w.chimes == 1            # icon and chime at 07:00, once
    assert w.run_until("23:59") == [sch.EXPIRED]
    assert w.icon == [True, False]                       # faded at 11:00
    assert w.s.briefing_for_today(at("20:00")) is not None   # still replayable


def test_one_chime_a_day_across_restarts(tmp_path):
    w = World(tmp_path)
    w.run_until("07:10")
    assert w.chimes == 1
    w.make()                                             # reboot mid-window
    w.run_until("08:00")
    assert w.chimes == 1 and w.s.icon_visible            # icon back, no second chime
    assert w.prepares == ["06:30"]                       # cache reused


def test_reboot_in_window_with_no_cache_prepares_straight_away(tmp_path):
    w = World(tmp_path)
    w.now = at("08:15")
    w.run_until("08:16")
    assert w.prepares == ["08:15"] and w.s.icon_visible and w.chimes == 1


def test_played_hides_icon_for_the_day(tmp_path):
    w = World(tmp_path)
    w.run_until("07:05")
    w.s.mark_played(w.now)
    assert w.icon == [True, False]
    w.make()
    assert w.run_until("10:00") == [sch.PLAYED] and w.chimes == 1


def test_offline_retries_every_10_minutes_until_window_closes(tmp_path):
    w = World(tmp_path, online=False)
    w.run_until("07:05")
    assert w.prepares == ["06:30", "06:40", "06:50", "07:00"]
    w.online = True
    assert w.run_until("07:30")[-1] == sch.READY
    assert w.prepares[-1] == "07:10" and w.chimes == 1
    w2 = World(tmp_path / "b", online=False)
    w2.run_until("23:00")
    assert w2.prepares[-1] == "10:50" and w2.chimes == 0 and w2.icon == []


def test_incomplete_briefing_retried_only_before_the_window(tmp_path):
    w = World(tmp_path)
    w.complete = False
    w.run_until("07:30")
    assert w.prepares == ["06:30", "06:40", "06:50"]     # nothing re-rendered once it's showing


def test_skipped_days_and_disabled(tmp_path):
    w = World(tmp_path, settings={"days": ["sat", "sun"]})
    assert w.run_until("12:00") == [sch.OFF] and w.prepares == []
    w = World(tmp_path / "b", settings={"enabled": False})
    assert w.run_until("12:00") == [sch.OFF]


def test_chime_setting_off_still_shows_icon(tmp_path):
    w = World(tmp_path, settings={"chime": False})
    w.run_until("07:01")
    assert w.chimes == 0 and w.s.icon_visible


def test_busy_bmo_delays_icon_and_chime(tmp_path):
    w = World(tmp_path)
    w.run_until("07:00")
    w.idle = False
    assert w.run_until("07:20") == [sch.WAITING_IDLE]
    assert w.chimes == 0 and w.icon == [] and w.s.is_ready_unplayed()
    w.idle = True
    w.run_until("07:21")
    assert w.chimes == 1 and w.icon == [True]
    w.idle = False                                       # busy later: icon stays
    w.run_until("07:30")
    assert w.icon == [True]


def test_waits_for_clock_sync(tmp_path):
    w = World(tmp_path, synced=False)
    w.now = at("07:30")                                  # a stale clock could claim anything
    assert w.run_until("08:00") == [sch.WAITING_CLOCK]
    assert w.prepares == [] and w.chimes == 0
    w.synced = True
    w.run_until("08:01")
    assert w.prepares and w.chimes == 1


def test_new_day_starts_over(tmp_path):
    w = World(tmp_path)
    w.run_until("12:00")
    w.now = at("06:00", DAY + datetime.timedelta(days=1))
    w.run_until("07:01", DAY + datetime.timedelta(days=1))
    assert w.chimes == 2 and w.prepares == ["06:30", "06:30"]


# --- audio cache ---------------------------------------------------------------

def test_render_writes_wavs_then_script_and_load_finds_them(tmp_path):
    root = str(tmp_path)
    b = audio.render_briefing(PARTS, DAY, cache_root=root, to_wav=fake_wav)
    assert [p["wav"] for p in b["parts"]] == ["0.wav", "1.wav"] and b["parts"][0]["duration"] > 0
    loaded = audio.load_briefing(DAY, root)
    assert os.path.isabs(loaded["parts"][1]["path"])
    os.remove(os.path.join(root, "2026-10-01", "1.wav"))
    assert audio.load_briefing(DAY, root) is None        # never play a half-there briefing


def test_failed_render_leaves_no_script(tmp_path):
    def boom(text, path):
        raise RuntimeError("piper died")
    with pytest.raises(RuntimeError):
        audio.render_briefing(PARTS, DAY, cache_root=str(tmp_path), to_wav=boom)
    assert audio.load_briefing(DAY, str(tmp_path)) is None


def test_piper_runs_niced_into_a_temp_file(tmp_path):
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw["input"]))
        fake_wav("x" * 50, cmd[cmd.index("--output_file") + 1])
    out = str(tmp_path / "0.wav")
    audio.piper_to_wav("Hello", out, run=run, piper=("piper", "bmo.onnx"))
    cmd, stdin = calls[0]
    assert cmd[:3] == ["nice", "-n", "19"] and cmd[3:6] == ["piper", "--model", "bmo.onnx"]
    assert cmd[cmd.index("--output_file") + 1] != out and stdin == b"Hello"
    assert os.listdir(tmp_path) == ["0.wav"]


def test_cache_keeps_three_days(tmp_path):
    for i in range(5):
        os.makedirs(tmp_path / (DAY - datetime.timedelta(days=i)).isoformat())
    (tmp_path / "forecast.json").write_text("{}")
    audio.prune_cache(str(tmp_path), DAY)
    assert sorted(os.listdir(tmp_path)) == ["2026-09-29", "2026-09-30", "2026-10-01", "forecast.json"]


def test_prepare_briefing_marks_incomplete_when_news_missing(tmp_path):
    seen = {}

    def render(parts, day, cache_root, complete):
        seen["complete"] = complete
        return {"parts": parts}
    sch.prepare_briefing(at("06:30"), {}, gather=lambda s, n, r: {"weather": {"x": 1}, "headlines": []},
                         build=lambda d, n: PARTS, render=render, cache_root=str(tmp_path))
    assert seen["complete"] is False
    assert sch.prepare_briefing(at("06:30"), {}, gather=lambda s, n, r: {}, build=lambda d, n: [],
                                render=render) is None


def test_prepare_now_renders_on_request_and_shares_the_lock(tmp_path):
    w = World(tmp_path)
    w.now = at("19:30")                                  # long after the window
    b = w.s.prepare_now()
    assert b is not None and w.prepares == ["19:30"]
    assert w.s.briefing_for_today(w.now) is not None
    with w.s._prepare_lock:                              # an on-demand one is running...
        w.now = at("06:45", DAY + datetime.timedelta(days=1))
        w.s.tick()                                       # ...so the tick doesn't start another
    assert w.prepares == ["19:30"]
