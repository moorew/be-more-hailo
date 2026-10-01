"""settings.json access shared by the GUI (volume) and the morning briefing.

settings.json holds several independent blocks ({"volume": ..., "briefing":
{...}}), so writers must read, merge and write back rather than dump only
their own key: the old volume writer wiped every other setting.
"""
import copy
import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

SETTINGS_PATH = "settings.json"

DEFAULTS = {
    "enabled": True,
    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "window": ["07:00", "11:00"],
    "prepare_minutes_before": 30,
    "chime": True,
    "location": "Brantford",
    "news": {
        # Read round-robin, newest first (see sources.get_headlines).
        "feeds": [],
        "count": 4,
        "region": "ca-en",
        "query": "Canada",
    },
    "extras": {
        "reminders": True,
        "sun": True,
        "countdowns": [],
        "fun_fact": False,
    },
    "talk_mood": "happy",
}


def read_settings(path: str = SETTINGS_PATH) -> dict:
    """The whole settings.json as a dict ({} if missing or unreadable)."""
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
        return {}


def update_settings(updates: dict, path: str = SETTINGS_PATH) -> None:
    """Merge top-level `updates` into settings.json, keeping every other key.

    Written to a temp file and renamed so a crash never leaves half a file.
    If the existing file is unreadable it is left alone (we'd otherwise
    replace the user's hand-edited briefing block with just the volume)."""
    data = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"Not writing {path}: existing file unreadable ({e})")
            return
        if not isinstance(data, dict):
            return
    data.update(updates)
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _merge(defaults: dict, override: dict) -> dict:
    out = copy.deepcopy(defaults)
    for k, v in (override or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_briefing_settings(path: str = SETTINGS_PATH) -> dict:
    """The `briefing` block with defaults filled in for every missing key."""
    block = read_settings(path).get("briefing")
    if block is not None and not isinstance(block, dict):
        logger.warning("settings.json 'briefing' is not an object; using defaults")
        block = None
    s = _merge(DEFAULTS, block or {})
    s["days"] = [str(d).lower()[:3] for d in s["days"]]
    s["news"]["count"] = max(3, min(5, int(s["news"]["count"])))
    return s
