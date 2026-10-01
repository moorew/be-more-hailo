"""python -m core.briefing --dry-run   # print today's script from live data
python -m core.briefing --setup     # choose location, news feeds and window
python -m core.briefing --render    # fetch + render today's briefing into cache/briefing/ now"""
import argparse
import datetime
import json
import logging

from core.briefing import script, sources
from core.briefing.settings import load_briefing_settings
from core.reminders import ReminderRegistry


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m core.briefing")
    ap.add_argument("--dry-run", action="store_true", help="fetch live data and print the script")
    ap.add_argument("--json", action="store_true", help="print the parts as JSON (cards included)")
    ap.add_argument("--setup", action="store_true", help="choose location, news feeds and window")
    ap.add_argument("--render", action="store_true",
                    help="fetch and render today's briefing to cache/briefing/<date>/ now (low priority)")
    ap.add_argument("--speech", action="store_true", help="also print the text handed to Piper")
    args = ap.parse_args(argv)
    if args.setup:
        from core.briefing.setup import run_setup
        try:
            run_setup()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled; nothing changed.")
        return
    if args.render:
        return render_now()
    if not args.dry_run:
        ap.error("choose --dry-run, --render or --setup")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_briefing_settings()
    now = datetime.datetime.now()
    data = sources.gather(settings, now, ReminderRegistry())
    parts = script.build_script(data, now)
    if args.json:
        print(json.dumps(parts, indent=2, ensure_ascii=False))
        return
    if not parts:
        print("(nothing to brief on: every source failed)")
    for p in parts:
        print(f"[{p['key']}] {p['text']}")
        if args.speech:
            print(f"    speech: {p['speech']}")


def render_now():
    import os
    import time
    from core.briefing.scheduler import prepare_briefing
    from core.config import ALSA_DEVICE

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    t0 = time.time()
    briefing = prepare_briefing(datetime.datetime.now(), load_briefing_settings(), ReminderRegistry())
    if briefing is None:
        print("Nothing to render: every source failed.")
        return
    total = sum(p["duration"] for p in briefing["parts"])
    print(f"\nRendered {len(briefing['parts'])} parts ({total:.0f} s of audio) in {briefing['render_s']:.1f} s "
          f"(fetch + render {time.time() - t0:.1f} s); complete={briefing['complete']}")
    d = os.path.join("cache", "briefing", briefing["date"])
    for i, p in enumerate(briefing["parts"]):
        print(f"  {i}.wav  {p['key']:<10} {p['duration']:5.1f} s")
    print(f"\nPlay part 0:  aplay -D {ALSA_DEVICE} -q --buffer-time=500000 {d}/0.wav")


if __name__ == "__main__":
    main()
