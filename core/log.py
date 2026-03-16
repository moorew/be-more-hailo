"""Colored console logging for BMO.

Provides:
- ``bmo_print(tag, msg)`` — drop-in replacement for ``print("[TAG] msg")``
- ``setup_logging()``      — one-call root logger config with colored output

Colors auto-disable when stdout is not a TTY (piped / redirected).
Honour ``NO_COLOR`` (https://no-color.org/) and ``FORCE_COLOR=1`` env vars.
"""

import logging
import os
import sys

# ---------------------------------------------------------------------------
#  Colour helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"

# Per-tag colours used by bmo_print()
_TAG_COLORS: dict[str, str] = {
    "STATE":       "\033[1;97m",   # Bold White
    "AGENT":       "\033[96m",     # Bright Cyan
    "LLM":         "\033[36m",     # Cyan
    "LLM-STREAM":  "\033[36m",     # Cyan
    "MUSIC":       "\033[95m",     # Bright Magenta
    "IMAGE":       "\033[35m",     # Magenta
    "TIMER SET":   "\033[93m",     # Bright Yellow
    "TIMER DONE":  "\033[1;93m",   # Bold Bright Yellow
    "MUTE":        "\033[91m",     # Bright Red
    "FOLLOW-UP":   "\033[32m",     # Green
    "SCREENSAVER": "\033[90m",     # Gray / Dim
    "WAKE":        "\033[1;92m",   # Bold Bright Green
    "STT":         "\033[94m",     # Bright Blue
    "TTS":         "\033[92m",     # Bright Green
    "AUDIO":       "\033[94m",     # Bright Blue
    "CAMERA":      "\033[35m",     # Magenta
    "ERROR":       "\033[91m",     # Bright Red
}

# Per-logger colours used by _ColoredFormatter
_LOGGER_COLORS: dict[str, str] = {
    "core.llm":    "\033[36m",     # Cyan
    "core.tts":    "\033[92m",     # Bright Green
    "core.stt":    "\033[94m",     # Bright Blue
    "core.search": "\033[34m",     # Blue
}

# Log-level colour overrides
_LEVEL_COLORS: dict[int, str] = {
    logging.WARNING:  "\033[33m",  # Yellow
    logging.ERROR:    "\033[91m",  # Bright Red
    logging.CRITICAL: "\033[1;91m",  # Bold Bright Red
}


def _use_color() -> bool:
    """Decide whether to emit ANSI colour codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") == "1":
        return True
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


_COLOR_ENABLED: bool | None = None


def _color_on() -> bool:
    global _COLOR_ENABLED
    if _COLOR_ENABLED is None:
        _COLOR_ENABLED = _use_color()
    return _COLOR_ENABLED


# ---------------------------------------------------------------------------
#  bmo_print  — replaces  print("[TAG] msg")
# ---------------------------------------------------------------------------

def bmo_print(tag: str, msg: str = "") -> None:
    """Print a tagged log line with optional ANSI colour."""
    if _color_on():
        color = _TAG_COLORS.get(tag, "")
        if color:
            print(f"{color}[{tag}]{_RESET} {msg}")
        else:
            print(f"[{tag}] {msg}")
    else:
        print(f"[{tag}] {msg}")


# ---------------------------------------------------------------------------
#  Colored logging.Formatter for Python logging module
# ---------------------------------------------------------------------------

class _ColoredFormatter(logging.Formatter):
    """Logging formatter that applies ANSI colours per logger name and level."""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if not _color_on():
            return msg

        # Level-based colour takes priority
        level_color = _LEVEL_COLORS.get(record.levelno)
        if level_color:
            return f"{level_color}{msg}{_RESET}"

        # Otherwise use logger-name colour
        logger_color = _LOGGER_COLORS.get(record.name)
        if logger_color:
            return f"{logger_color}{msg}{_RESET}"

        return msg


# ---------------------------------------------------------------------------
#  setup_logging  — call once at startup
# ---------------------------------------------------------------------------

_logging_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with a coloured console handler.

    Safe to call multiple times; only the first call takes effect.
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    handler = logging.StreamHandler(sys.stderr)
    formatter = _ColoredFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Remove any existing handlers to avoid duplicates
    root.handlers.clear()
    root.addHandler(handler)
