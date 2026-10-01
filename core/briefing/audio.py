"""Pre-render the briefing to WAVs so a tap plays instantly, even offline.

Each part goes through its own low-priority (`nice`) Piper process with the
same binary and voice as live speech, never the agent's warm _piper_proc,
and lands in cache/briefing/<YYYY-MM-DD>/<n>.wav.  Every file is written to a
temp name and renamed, and script.json is written last, so a half-rendered
briefing is never played: no script.json means not ready.
"""
import datetime
import json
import logging
import os
import shutil
import subprocess
import time
import wave

logger = logging.getLogger(__name__)

CACHE_ROOT = os.path.join("cache", "briefing")
KEEP_DAYS = 3
PIPER_TIMEOUT_S = 300


def day_dir(day: datetime.date, cache_root: str = CACHE_ROOT) -> str:
    return os.path.join(cache_root, day.isoformat())


def _piper_paths():
    from core.config import PIPER_CMD, PIPER_MODEL
    return PIPER_CMD, PIPER_MODEL


def piper_to_wav(text: str, out_path: str, run=subprocess.run, piper=None) -> None:
    """Speak `text` into `out_path` with Piper at nice 19.  Raises on failure."""
    cmd, model = piper or _piper_paths()
    tmp = out_path + ".tmp.wav"
    try:
        run(["nice", "-n", "19", cmd, "--model", model, "--output_file", tmp, "--quiet"],
            input=text.encode(), check=True, timeout=PIPER_TIMEOUT_S,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not os.path.exists(tmp) or os.path.getsize(tmp) <= 44:
            raise RuntimeError(f"Piper wrote no audio for {out_path}")
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def wav_duration(path: str) -> float:
    with wave.open(path) as w:
        return w.getnframes() / float(w.getframerate())


def render_briefing(parts: list, day: datetime.date, cache_root: str = CACHE_ROOT,
                    complete: bool = True, to_wav=piper_to_wav, clock=time.time) -> dict:
    """Render every part and write script.json; returns the saved briefing.

    `complete` records whether weather and news both made it, so the
    scheduler knows whether a retry before the window could do better."""
    d = day_dir(day, cache_root)
    os.makedirs(d, exist_ok=True)
    started = clock()
    saved = []
    for i, part in enumerate(parts):
        wav = f"{i}.wav"
        t0 = clock()
        to_wav(part["speech"], os.path.join(d, wav))
        saved.append({**part, "wav": wav, "duration": round(wav_duration(os.path.join(d, wav)), 2)})
        logger.info(f"Briefing: rendered {part['key']} in {clock() - t0:.1f} s")
    briefing = {"date": day.isoformat(), "created": clock(), "complete": complete,
                "render_s": round(clock() - started, 1), "parts": saved}
    write_json_atomic(os.path.join(d, "script.json"), briefing)
    prune_cache(cache_root, day)
    return briefing


def load_briefing(day: datetime.date, cache_root: str = CACHE_ROOT):
    """Today's rendered briefing with absolute WAV paths, or None if not (fully) there."""
    d = day_dir(day, cache_root)
    try:
        with open(os.path.join(d, "script.json")) as f:
            briefing = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    for p in briefing.get("parts", []):
        p["path"] = os.path.abspath(os.path.join(d, p["wav"]))
        if not os.path.exists(p["path"]):
            logger.warning(f"Briefing: {p['path']} missing; treating cache as not ready")
            return None
    return briefing


def prune_cache(cache_root: str, today: datetime.date, keep_days: int = KEEP_DAYS) -> None:
    """Delete day folders older than the last `keep_days` days (today included)."""
    oldest = today - datetime.timedelta(days=keep_days - 1)
    try:
        names = os.listdir(cache_root)
    except FileNotFoundError:
        return
    for name in names:
        try:
            day = datetime.date.fromisoformat(name)
        except ValueError:
            continue
        if day < oldest:
            shutil.rmtree(os.path.join(cache_root, name), ignore_errors=True)


def write_json_atomic(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
