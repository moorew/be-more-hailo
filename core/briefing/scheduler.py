"""The briefing's day: prepare -> ready (icon + chime) -> played / expired.

Ticked every 30 s from a background thread.  Everything time- or
system-dependent is injected (clock, clock-sync check, prepare, idle check,
chime), so tests drive whole days on a fake clock.

    prepare_at = window start - prepare_minutes_before
    [prepare_at, window end)   prepare; offline -> retry every 10 min.  A
                               briefing missing weather or news is retried
                               until the window opens, then kept as is.
    [window start, window end) icon shows once BMO is idle, with one chime a
                               day (remembered in state.json across restarts)
    window end ->              icon fades; "morning briefing" replays it until
                               midnight
"""
import datetime
import json
import logging
import os
import subprocess
import threading

from core.briefing import audio

logger = logging.getLogger(__name__)

TICK_S = 30
RETRY_S = 10 * 60
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Statuses, in a day's order.
WAITING_CLOCK = "waiting_clock"   # system clock not NTP-synced yet
OFF = "off"                       # disabled, or not a briefing day
BEFORE = "before"                 # earlier than prepare_at
PREPARING = "preparing"           # fetching/rendering, or waiting to retry
PREPARED = "prepared"             # cached, window not open yet
WAITING_IDLE = "waiting_idle"     # window open, BMO busy: icon and chime wait
READY = "ready"                   # icon showing
PLAYED = "played"                 # tapped/asked for today
EXPIRED = "expired"               # window closed (cached briefing still replayable)


def ntp_synchronized() -> bool:
    """True once systemd reports the clock as NTP-synchronised."""
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() == "yes"
    except Exception as e:
        logger.warning(f"Briefing: timedatectl failed ({e}); assuming the clock is not synced")
        return False


def _at(day: datetime.date, hhmm: str) -> datetime.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.datetime.combine(day, datetime.time(h, m))


class BriefingScheduler:
    def __init__(self, settings_fn, prepare_fn, now_fn=datetime.datetime.now,
                 clock_synced=ntp_synchronized, is_idle=lambda: True, chime_fn=None,
                 on_icon=None, cache_root: str = audio.CACHE_ROOT):
        self.settings_fn = settings_fn      # () -> briefing settings dict
        self.prepare_fn = prepare_fn        # (now, settings) -> saved briefing dict or None
        self.now_fn = now_fn
        self.clock_synced = clock_synced
        self.is_idle = is_idle              # () -> True when BMO can chime / show the icon
        self.chime_fn = chime_fn            # () -> None, plays the ready jingle
        self.on_icon = on_icon              # (visible: bool) -> None
        self.cache_root = cache_root
        self.status = WAITING_CLOCK
        self.icon_visible = False
        self._synced = False
        self._last_attempt = None
        self._day = None
        # One prepare at a time: the 30 s tick and an on-demand "show me my
        # briefing" both write today's cache folder.
        self._prepare_lock = threading.Lock()

    # --- per-day state (survives restarts) ---
    def _state_path(self, day):
        return os.path.join(audio.day_dir(day, self.cache_root), "state.json")

    def _state(self, day) -> dict:
        try:
            with open(self._state_path(day)) as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}

    def _set_state(self, day, **kv):
        state = {**self._state(day), **kv}
        os.makedirs(audio.day_dir(day, self.cache_root), exist_ok=True)
        audio.write_json_atomic(self._state_path(day), state)

    def mark_played(self, now: datetime.datetime = None) -> None:
        """Called when playback starts: the icon goes for the day."""
        now = now or self.now_fn()
        self._set_state(now.date(), played=True)
        self._show_icon(False)
        self.status = PLAYED

    def briefing_for_today(self, now: datetime.datetime = None):
        """Today's cached briefing (for playback or a replay), or None."""
        return audio.load_briefing((now or self.now_fn()).date(), self.cache_root)

    def prepare_now(self, now: datetime.datetime = None):
        """Fetch and render today's briefing right away (asked for by voice
        outside the morning, or the cached one is stale).  Waits for a
        prepare already in progress, then returns the fresh briefing or None."""
        now = now or self.now_fn()
        with self._prepare_lock:
            try:
                return self.prepare_fn(now, self.settings_fn())
            except Exception as e:
                logger.warning(f"Briefing: on-demand prepare failed: {e}")
                return None

    def is_ready_unplayed(self) -> bool:
        """For "good morning": a briefing is waiting and hasn't been played."""
        return self.status in (READY, WAITING_IDLE)

    # --- the tick ---
    def _show_icon(self, visible: bool):
        if visible != self.icon_visible:
            self.icon_visible = visible
            if self.on_icon:
                self.on_icon(visible)

    def tick(self) -> str:
        if not self._synced:
            self._synced = bool(self.clock_synced())
            if not self._synced:
                self.status = WAITING_CLOCK
                return self.status
        now = self.now_fn()
        today = now.date()
        if today != self._day:                       # new day (or first tick)
            self._day, self._last_attempt = today, None
            self._show_icon(False)
        s = self.settings_fn()
        if not s.get("enabled", True) or DAY_NAMES[today.weekday()] not in s.get("days", DAY_NAMES):
            self._show_icon(False)
            self.status = OFF
            return self.status

        start, end = _at(today, s["window"][0]), _at(today, s["window"][1])
        prepare_at = start - datetime.timedelta(minutes=int(s.get("prepare_minutes_before", 30)))
        state = self._state(today)

        if now < prepare_at:
            self.status = BEFORE
            return self.status
        if now >= end:
            self._show_icon(False)
            self.status = PLAYED if state.get("played") else EXPIRED
            return self.status
        if state.get("played"):
            self._show_icon(False)
            self.status = PLAYED
            return self.status

        briefing = audio.load_briefing(today, self.cache_root)
        wants_retry = briefing is None or (not briefing.get("complete", True) and now < start)
        if wants_retry and (self._last_attempt is None
                            or (now - self._last_attempt).total_seconds() >= RETRY_S):
            self._last_attempt = now
            fresh = None
            if self._prepare_lock.acquire(blocking=False):   # else an on-demand one is running
                try:
                    fresh = self.prepare_fn(now, s)
                except Exception as e:
                    logger.warning(f"Briefing: prepare failed: {e}")
                finally:
                    self._prepare_lock.release()
            if fresh is not None:
                briefing = fresh
                # A retry may have taken a while; re-read the clock.
                now = self.now_fn()
        if briefing is None:
            self.status = PREPARING
            return self.status
        if now < start:
            self.status = PREPARED
            return self.status

        # Window open, briefing cached, not played.
        if not self.icon_visible:
            if not self.is_idle():
                self.status = WAITING_IDLE
                return self.status
            self._show_icon(True)
            if not state.get("chimed"):
                self._set_state(today, chimed=True)   # before playing: a crash never re-chimes
                if s.get("chime", True) and self.chime_fn:
                    self.chime_fn()
        self.status = READY
        return self.status


def prepare_briefing(now: datetime.datetime, settings: dict, registry=None,
                     cache_root: str = audio.CACHE_ROOT, gather=None, build=None, render=None,
                     fun_fact=None):
    """Fetch, script and render today's briefing.  None when there's nothing to say.

    `fun_fact` () -> str or None is only called when extras.fun_fact is on."""
    from core.briefing import script, sources
    gather = gather or sources.gather
    build = build or script.build_script
    render = render or audio.render_briefing
    data = gather(settings, now, registry)
    if fun_fact is not None and settings.get("extras", {}).get("fun_fact"):
        try:
            data["fun_fact"] = script.clean_fun_fact(fun_fact())
        except Exception as e:
            logger.warning(f"Briefing: fun fact failed: {e}")
    parts = build(data, now)
    if not parts:
        logger.info("Briefing: nothing to say yet (offline?)")
        return None
    complete = bool(data.get("weather")) and bool(data.get("headlines"))
    return render(parts, now.date(), cache_root=cache_root, complete=complete)
