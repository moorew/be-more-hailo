"""Pending timers and reminders, saved to reminders.json.

Timers used to be fire-and-forget threads with no list, so nothing could ask
"what's due today?" (the morning briefing) and a reboot silently lost them.
start_timer_thread adds an entry when a timer is set and removes it when it
fires; on startup the agent re-arms entries that are still in the future and
drops (and logs) the ones that passed while BMO was off, so a reboot doesn't
fire a burst of stale alarms.
"""
import json
import logging
import os
import tempfile
import threading
import time
import uuid

logger = logging.getLogger(__name__)

REMINDERS_PATH = "reminders.json"


class ReminderRegistry:
    def __init__(self, path: str = REMINDERS_PATH, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()
        self._items = {}
        self._load()

    # --- persistence ---
    def _load(self):
        try:
            with open(self.path) as f:
                items = json.load(f)
            self._items = {r["id"]: r for r in items
                           if isinstance(r, dict) and "id" in r and "due" in r}
        except FileNotFoundError:
            self._items = {}
        except Exception as e:
            logger.warning(f"Could not read {self.path}: {e}")
            self._items = {}

    def _save(self):
        items = sorted(self._items.values(), key=lambda r: r["due"])
        d = os.path.dirname(os.path.abspath(self.path))
        try:
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".reminders.", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(items, f, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning(f"Could not write {self.path}: {e}")

    # --- API ---
    def add(self, due: float, message: str, kind: str = "timer") -> str:
        """Register a reminder due at epoch seconds `due`; returns its id."""
        rid = uuid.uuid4().hex[:12]
        with self._lock:
            self._items[rid] = {"id": rid, "due": float(due), "message": str(message),
                                "kind": kind, "created": self.clock()}
            self._save()
        return rid

    def remove(self, rid: str) -> bool:
        """Forget a reminder (it fired or was cancelled). False if unknown."""
        with self._lock:
            if self._items.pop(rid, None) is None:
                return False
            self._save()
            return True

    def get(self, rid: str):
        with self._lock:
            r = self._items.get(rid)
            return dict(r) if r else None

    def pending(self) -> list:
        """Every saved reminder, soonest first."""
        with self._lock:
            return [dict(r) for r in sorted(self._items.values(), key=lambda r: r["due"])]

    def due_between(self, start: float, end: float) -> list:
        """Reminders due in [start, end), soonest first."""
        return [r for r in self.pending() if start <= r["due"] < end]

    def prune_past(self) -> list:
        """Drop reminders already due (missed while BMO was off); returns them."""
        now = self.clock()
        with self._lock:
            dropped = [r for r in self._items.values() if r["due"] <= now]
            for r in dropped:
                del self._items[r["id"]]
            if dropped:
                self._save()
        for r in dropped:
            logger.info(f"Dropping missed reminder {r['message']!r} "
                        f"(was due {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['due']))})")
        return sorted(dropped, key=lambda r: r["due"])
