"""python -m core.briefing --dry-run   # print today's script from live data
python -m core.briefing --setup     # choose location, news feeds and window"""
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
    ap.add_argument("--speech", action="store_true", help="also print the text handed to Piper")
    args = ap.parse_args(argv)
    if args.setup:
        from core.briefing.setup import run_setup
        try:
            run_setup()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled; nothing changed.")
        return
    if not args.dry_run:
        ap.error("choose --dry-run or --setup")
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


if __name__ == "__main__":
    main()
